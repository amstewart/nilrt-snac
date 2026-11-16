import argparse
import pathlib
import subprocess
import time

from nilrt_snac._configs._base_config import _BaseConfig
from nilrt_snac._logging import run_with_logging

from nilrt_snac import Errors, SNACError, logger
from nilrt_snac.opkg import opkg_helper

# Policy that ni-firewall-dropins ships and opens declared services in.
DROPINS_POLICY = "ni-dropins"
DROPINS_OPEN_D = pathlib.Path("/etc/ni/firewall/open.d")
DROPINS_INGRESS_ZONES = {"public", "work"}
DROPINS_PACKAGE = "ni-firewall-dropins"
# 1.1 ships the ni-dropins policy; 1.0 reopens drop-ins in the default zone,
# which the WireGuard tunnel cannot reach.
DROPINS_MIN_VERSION = "1.1"

# Always-on NI services that the ni-firewalld-servicedefs postinst opens in the
# default zone (CORE_NI_SERVICES in its recipe). In SNAC mode they must only be
# reachable through the WireGuard tunnel, but that postinst reopens them in
# "public" whenever the package is installed or upgraded.
CORE_NI_SERVICES = ["ni-service-locator", "ni-mxs", "ni-logos-xt", "http", "https", "mdns"]


def _cmd(*args: str):
    "Syntactic sugar for firewall-cmd -q."
    run_with_logging("firewall-cmd", "-q", *args, check=True)


def _offlinecmd(*args: str):
    "Syntactic sugar for firewall-offline-cmd -q."
    run_with_logging("firewall-offline-cmd", "-q", *args, check=True)


def _check_target(policy: str, expected: str = "REJECT") -> bool:
    "Verifies firewall-cmd --policy=POLICY --get-target matches what is expected."

    actual: str = subprocess.getoutput(f"firewall-cmd --permanent --policy={policy} --get-target")
    if expected == actual:
        return True
    logger.error(f"ERROR: policy {policy} target: expected {expected}, observed {actual}")
    return False


def _check_service(Q: str, service: str, expected: str = "yes") -> bool:
    """Verifies firewall-cmd (--policy=POLICY/--zone=ZONE/etc.) --query-service=SERVICE
    matches what is expected.
    """

    actual: str = subprocess.getoutput(f"firewall-cmd --permanent {Q} --query-service={service}")
    if expected == actual:
        return True
    logger.error(f"ERROR: {Q} service {service}: expected {expected}, observed {actual}")
    return False


def _check_service_info(service: str, Q: str, expected: str) -> bool:
    """Verifies firewall-cmd --service=SERVICE (--get-ports/--get-description/etc.)
    matches what is expected.
    """

    actual: str = subprocess.getoutput(f"firewall-cmd --permanent --service={service} {Q}")
    if expected == actual:
        return True
    logger.error(f"ERROR: service {service} {Q}: expected {expected}, observed {actual}")
    return False


def _declared_dropin_services(open_d: pathlib.Path = DROPINS_OPEN_D) -> list:
    """Returns the services declared by NI firewall drop-in markers.

    Parses the markers the same way ni-firewall-apply does: one service per
    line, '#' starts a comment, whitespace is ignored, and a marker without
    service lines declares the service named after the file, minus any leading
    "NN-" prefix and trailing ".conf" suffix.
    """
    services: list = []
    if not open_d.is_dir():
        return services
    for marker in sorted(open_d.iterdir()):
        if marker.name.startswith(".") or not marker.is_file():
            continue
        declared = [
            "".join(line.split("#", 1)[0].split())
            for line in marker.read_text().splitlines()
        ]
        declared = [svc for svc in declared if svc]
        if not declared:
            name = marker.name.removesuffix(".conf")
            if len(name) > 3 and name[:2].isdigit() and name[2] == "-":
                name = name[3:]
            declared = [name]
        for svc in declared:
            if svc not in services:
                services.append(svc)
    return services


def _firewall_views() -> list:
    """Returns the firewalld configurations to verify, as (name, firewall-cmd
    option) pairs: the permanent one, and the runtime one while firewalld runs.

    A runtime change takes effect at once but is lost on reload; a permanent
    one takes effect only on reload. Both must be right.
    """
    views = [("permanent", ["--permanent"])]
    if _firewalld_is_running():
        views.append(("runtime", []))
    return views


def _check_core_services_not_public() -> bool:
    """Verifies that no always-on NI service is enabled in the public zone."""
    valid = True
    for view, option in _firewall_views():
        command = " ".join(["firewall-cmd", *option, "--zone=public", "--list-services"])
        status, output = subprocess.getstatusoutput(command)
        if status != 0:
            # A failed query names no services; don't mistake it for a clean zone.
            logger.error(f"ERROR: could not list --zone=public services ({view}): {output}")
            valid = False
            continue
        enabled = output.split()
        for service in CORE_NI_SERVICES:
            if service in enabled:
                logger.error(
                    f"ERROR: --zone=public service {service} ({view}): expected no, "
                    "observed yes (re-run nilrt-snac configure)"
                )
                valid = False
    return valid


def _policy_info(option: list) -> dict:
    """Returns the ni-dropins policy settings from 'firewall-cmd --info-policy'
    as a dict of lists, or None if firewalld does not know the policy.
    """
    command = " ".join(["firewall-cmd", *option, f"--info-policy={DROPINS_POLICY}"])
    status, output = subprocess.getstatusoutput(command)
    if status != 0:
        return None
    info = {}
    for line in output.splitlines()[1:]:
        key, separator, value = line.partition(":")
        if separator:
            info[key.strip()] = value.split()
    return info


def _check_dropins() -> bool:
    """Verifies the ni-dropins policy is wired to the plain network and the
    WireGuard tunnel, and opens every service declared by a drop-in marker.
    """
    valid = True
    declared = _declared_dropin_services()
    for view, option in _firewall_views():
        info = _policy_info(option)
        if info is None:
            logger.error(f"MISSING: firewalld policy {DROPINS_POLICY} ({view})")
            valid = False
            continue

        target = info.get("target", [])
        if target != ["CONTINUE"]:
            logger.error(
                f"ERROR: policy {DROPINS_POLICY} target ({view}): expected CONTINUE, "
                f"observed {' '.join(target)}"
            )
            valid = False
        ingress = set(info.get("ingress-zones", []))
        if ingress != DROPINS_INGRESS_ZONES:
            logger.error(
                f"ERROR: policy {DROPINS_POLICY} ingress zones ({view}): expected "
                f"{sorted(DROPINS_INGRESS_ZONES)}, observed {sorted(ingress)}"
            )
            valid = False
        egress = info.get("egress-zones", [])
        if egress != ["HOST"]:
            logger.error(
                f"ERROR: policy {DROPINS_POLICY} egress zones ({view}): expected HOST, "
                f"observed {' '.join(egress)}"
            )
            valid = False

        enabled = info.get("services", [])
        for service in declared:
            if service not in enabled:
                logger.error(
                    f"MISSING: drop-in service {service} in policy {DROPINS_POLICY} ({view})"
                )
                valid = False
    return valid


def _installed_version(package: str) -> str:
    """Returns the installed version of an IPK, or "" if it is not installed."""
    version = ""
    installed = False
    for line in subprocess.getoutput(f"opkg status {package}").splitlines():
        if line.startswith("Version:"):
            version = line.split(":", 1)[1].strip()
        elif line.startswith("Status:"):
            installed = line.split()[-1] == "installed"
    return version if installed else ""


def _version_at_least(version: str, minimum: str) -> bool:
    """Compares IPK versions the way opkg does."""
    result = subprocess.run(
        ["opkg", "compare-versions", version, ">=", minimum],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def _firewalld_is_running(timeout: float = 2) -> bool:
    try:
        result = subprocess.run(
            ["firewall-cmd", "--state"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return False
    return result.returncode == 0 and result.stdout.strip() == "running"


def _wait_for_firewalld() -> bool:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        if _firewalld_is_running(timeout=min(2, remaining)):
            return True
        time.sleep(min(1, max(0, deadline - time.monotonic())))
    return False


class _FirewallConfig(_BaseConfig):
    def __init__(self):
        super().__init__("firewall")
        self._opkg_helper = opkg_helper

    def _ensure_dropins_version(self, dry_run: bool) -> None:
        """Brings ni-firewall-dropins up to DROPINS_MIN_VERSION, or stops.

        OpkgHelper.install() leaves an already installed package alone, and
        an older ni-firewall-dropins would reopen the declared services in the
        default zone after the reset below, out of reach of the tunnel.
        """
        version = _installed_version(DROPINS_PACKAGE)
        if version and _version_at_least(version, DROPINS_MIN_VERSION):
            return
        if dry_run:
            # Not installed: install() above would install the feed's version.
            if version:
                logger.info(f"Upgrading IPK: {DROPINS_PACKAGE} {version}")
            return

        logger.info(f"Upgrading IPK: {DROPINS_PACKAGE} {version or '(not installed)'}")
        run_with_logging("opkg", "upgrade", DROPINS_PACKAGE, check=False)
        version = _installed_version(DROPINS_PACKAGE)
        if not (version and _version_at_least(version, DROPINS_MIN_VERSION)):
            raise SNACError(
                f"{DROPINS_PACKAGE} {version or '(not installed)'} is too old; SNAC needs "
                f"{DROPINS_MIN_VERSION} or later. Make a package feed that provides it "
                "available (then run 'opkg update'), and run nilrt-snac configure again.",
                Errors.EX_BAD_ENVIRONMENT,
            )

    def configure(self, args: argparse.Namespace) -> None:
        print("Configuring firewall...")
        dry_run: bool = args.dry_run

        # nftables installed via deps
        self._opkg_helper.install("firewalld")
        self._opkg_helper.install("firewalld-offline-cmd")
        self._opkg_helper.install("firewalld-log-rotate")
        self._opkg_helper.install("ni-firewalld-servicedefs")
        self._opkg_helper.install(DROPINS_PACKAGE)
        # Before the reset, so a failure leaves the firewall untouched.
        self._ensure_dropins_version(dry_run)

        if dry_run:
            return

        _offlinecmd("--reset-to-defaults")

        _offlinecmd("--zone=work", "--add-interface=wglv0")
        _offlinecmd("--zone=work", "--remove-forward")
        _offlinecmd("--zone=public", "--remove-forward")

        _offlinecmd("--new-policy=work-in")
        _offlinecmd("--policy=work-in", "--add-ingress-zone=work")
        _offlinecmd("--policy=work-in", "--add-egress-zone=HOST")
        _offlinecmd("--policy=work-in", "--add-protocol=icmp")
        _offlinecmd("--policy=work-in", "--add-protocol=ipv6-icmp")
        _offlinecmd(
            "--policy=work-in",
            "--add-service=ssh",
            "--add-service=mdns",
        )

        _offlinecmd("--new-policy=work-out")
        _offlinecmd("--policy=work-out", "--add-ingress-zone=HOST")
        _offlinecmd("--policy=work-out", "--add-egress-zone=work")
        _offlinecmd("--policy=work-out", "--add-protocol=icmp")
        _offlinecmd("--policy=work-out", "--add-protocol=ipv6-icmp")
        _offlinecmd(
            "--policy=work-out",
            "--add-service=ssh",
            "--add-service=http",
            "--add-service=https",
            "--add-service=syslog",
            "--add-service=ni-logos-xt",
        )
        _offlinecmd("--policy=work-out", "--set-target=REJECT")

        _offlinecmd("--new-policy=public-in")
        _offlinecmd("--policy=public-in", "--add-ingress-zone=public")
        _offlinecmd("--policy=public-in", "--add-egress-zone=HOST")
        _offlinecmd("--policy=public-in", "--add-protocol=icmp")
        _offlinecmd("--policy=public-in", "--add-protocol=ipv6-icmp")
        _offlinecmd(
            "--policy=public-in",
            "--add-service=ssh",
            "--add-service=wireguard",
        )

        _offlinecmd("--new-policy=public-out")
        _offlinecmd("--policy=public-out", "--add-ingress-zone=HOST")
        _offlinecmd("--policy=public-out", "--add-egress-zone=public")
        _offlinecmd("--policy=public-out", "--add-protocol=icmp")
        _offlinecmd("--policy=public-out", "--add-protocol=ipv6-icmp")
        _offlinecmd(
            "--policy=public-out",
            "--add-service=dhcp",
            "--add-service=dhcpv6",
            "--add-service=http",
            "--add-service=https",
            "--add-service=wireguard",
            "--add-service=dns",
            "--add-service=ntp",
        )
        _offlinecmd("--policy=public-out", "--set-target=REJECT")

        _offlinecmd(
            "--policy=work-in",
            "--add-service=ni-labview-realtime",
            "--add-service=ni-labview-viserver",
            "--add-service=ni-logos-xt",
            "--add-service=ni-mxs",
            "--add-service=ni-orb-rpc-server",
            "--add-service=ni-service-locator",
        )
        _offlinecmd(
            "--policy=work-in",
            # Temporary port add; see x-niroco-static-port.ini
            "--add-port=55184/tcp",
        )
        _offlinecmd(
            "--policy=work-out",
            "--add-service=amqp",
            "--add-service=salt-master",
        )

        run_with_logging(
            "nirtcfg",
            "--set",
            "section=SystemSettings,token=firewall.enabled,value=True",
            check=True,
        )
        if not _firewalld_is_running():
            run_with_logging("/etc/init.d/firewalld", "start", check=True)
            if not _wait_for_firewalld():
                raise RuntimeError("firewalld did not become available after starting")

        _cmd("--reload")

        # The reset above also emptied the ni-dropins policy. Reopen the
        # services that installed NI packages declare; they are reachable on
        # both the plain network and the WireGuard tunnel. Run it only after
        # the reload, so it sees the reset configuration rather than the
        # daemon's stale one.
        result = run_with_logging("ni-firewall-apply", check=False)
        if result.returncode != 0:
            logger.warning(
                "ni-firewall-apply failed; services declared by NI packages may not be open"
            )

    def verify(self, args: argparse.Namespace) -> bool:
        print("Verifying firewall configuration...")
        valid: bool = True

        try:
            pid: int = int(subprocess.getoutput("pidof -x /usr/sbin/firewalld"))
        except ValueError:
            logger.error(f"MISSING: running firewalld")
            valid = False

        try:
            _cmd("--check-config")
        except FileNotFoundError:
            logger.error(f"MISSING: firewall-cmd")
            valid = False

        firewall_enabled = subprocess.getoutput(
            "nirtcfg --get section=SystemSettings,token=firewall.enabled,value=false"
        )
        if firewall_enabled.strip().lower() != "true":
            logger.error("MISSING: SystemSettings firewall.enabled is not True")
            valid = False

        valid &= all(
            [
                _check_target("work-in", "CONTINUE"),
                _check_target("work-out"),
                _check_target("public-in", "CONTINUE"),
                _check_target("public-out"),
                _check_service("--policy=work-in", "ni-labview-realtime"),
                _check_service("--policy=work-in", "ni-orb-rpc-server"),
                _check_service("--policy=public-in", "ni-labview-realtime", "no"),
                _check_service("--zone=public", "ni-labview-realtime", "no"),
                _check_service_info("ni-labview-realtime", "--get-ports", "3079/tcp"),
                _check_service_info("ni-orb-rpc-server", "--get-ports", "43973/tcp"),
                _check_dropins(),
                _check_core_services_not_public(),
            ]
        )

        return valid
