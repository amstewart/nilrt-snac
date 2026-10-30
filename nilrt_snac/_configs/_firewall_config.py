import argparse
import subprocess
import time
from typing import Dict, Tuple

from nilrt_snac._configs._base_config import _BaseConfig
from nilrt_snac._logging import run_with_logging

from nilrt_snac import logger
from nilrt_snac.opkg import opkg_helper


# Reject unmatched traffic before the distro's zone service openings are evaluated.
_POLICY_PRIORITY = "-1000"
_POLICIES = (
    (
        "work-in", "work", "HOST",
        (
            "ssh", "dhcpv6-client", "mdns", "ni-labview-realtime", "ni-labview-viserver",
            "ni-logos-xt", "ni-mxs", "ni-service-locator",
        ),
        # The distro no longer supplies ni-rpc-server (43973/tcp).
        ("43973/tcp", "55184/tcp"),
    ),
    (
        "work-out", "HOST", "work",
        ("ssh", "http", "https", "syslog", "ni-logos-xt", "amqp", "salt-master"),
        (),
    ),
    (
        "public-in", "public", "HOST",
        ("ssh", "wireguard", "dhcpv6-client"),
        (),
    ),
    (
        "public-out", "HOST", "public",
        ("dhcp", "dhcpv6", "http", "https", "wireguard", "dns", "ntp"),
        (),
    ),
)


def _cmd(*args: str):
    "Syntactic sugar for firewall-cmd -q."
    run_with_logging("firewall-cmd", "-q", *args, check=True)


def _offlinecmd(*args: str):
    "Syntactic sugar for firewall-offline-cmd -q."
    run_with_logging("firewall-offline-cmd", "-q", *args, check=True)


def _check_setting(
    *args: str, expected: str, permanent: bool = True, expected_returncode: int = 0
) -> bool:
    command = ("firewall-cmd", "--permanent") if permanent else ("firewall-cmd",)
    result = run_with_logging(*command, *args, check=False, stream_output=False)
    actual = result.stdout.strip()
    if result.returncode == expected_returncode and sorted(actual.split()) == sorted(expected.split()):
        return True
    logger.error(
        f"ERROR: {' '.join(command + args)}: expected {expected!r}, "
        f"observed {actual!r} (exit {result.returncode})"
    )
    return False


def _check_policy(
    name: str, ingress: str, egress: str,
    services: Tuple[str, ...], ports: Tuple[str, ...], permanent: bool
) -> bool:
    command = ("firewall-cmd", "--permanent") if permanent else ("firewall-cmd",)
    result = run_with_logging(
        *command, f"--policy={name}", "--list-all", check=False, stream_output=False
    )
    if result.returncode != 0:
        logger.error(f"ERROR: cannot read policy {name}: {result.stdout.strip()}")
        return False

    actual: Dict[str, str] = {}
    key = ""
    for line in result.stdout.splitlines()[1:]:
        if line.startswith("  ") and not line.startswith("    "):
            key, _, value = line.strip().partition(":")
            actual[key] = value.strip()
        elif key:
            actual[key] += " " + line.strip()

    valid = True
    for key, expected in (
        ("priority", _POLICY_PRIORITY),
        ("target", "REJECT"),
        ("ingress-zones", ingress),
        ("egress-zones", egress),
        ("services", " ".join(services)),
        ("ports", " ".join(ports)),
        ("protocols", "icmp ipv6-icmp"),
        ("masquerade", "no"),
        ("forward-ports", ""),
        ("source-ports", ""),
        ("icmp-blocks", ""),
        ("rich rules", ""),
    ):
        observed = actual.get(key)
        if observed is None or sorted(observed.split()) != sorted(expected.split()):
            logger.error(
                f"ERROR: policy {name} {key} (permanent={permanent}): "
                f"expected {expected!r}, observed {observed!r}"
            )
            valid = False
    return valid


class _FirewallConfig(_BaseConfig):
    def __init__(self):
        super().__init__("firewall")
        self._opkg_helper = opkg_helper

    def configure(self, args: argparse.Namespace) -> None:
        print("Configuring firewall...")
        dry_run: bool = args.dry_run
        if dry_run:
            return

        # nftables installed via deps
        self._opkg_helper.install("firewalld")
        self._opkg_helper.install("firewalld-offline-cmd")
        self._opkg_helper.install("firewalld-log-rotate")
        self._opkg_helper.install("ni-firewalld-servicedefs")

        # Preserve distro-owned zones, services and drop-ins; replace only our policies.
        policies = run_with_logging(
            "firewall-offline-cmd", "--get-policies", check=True, stream_output=False
        ).stdout.split()
        for name, ingress, egress, services, ports in _POLICIES:
            if name in policies:
                _offlinecmd(f"--delete-policy={name}")
            _offlinecmd(f"--new-policy={name}")
            for option in (
                f"--add-ingress-zone={ingress}",
                f"--add-egress-zone={egress}",
                f"--set-priority={_POLICY_PRIORITY}",
                "--set-target=REJECT",
                "--add-protocol=icmp",
                "--add-protocol=ipv6-icmp",
            ):
                _offlinecmd(f"--policy={name}", option)
            _offlinecmd(
                f"--policy={name}",
                *(f"--add-service={service}" for service in services),
            )
            if ports:
                _offlinecmd(f"--policy={name}", *(f"--add-port={port}" for port in ports))

        default_zone = run_with_logging(
            "firewall-offline-cmd", "--get-default-zone", check=True, stream_output=False
        ).stdout.strip()
        if default_zone != "public":
            _offlinecmd("--set-default-zone=public")
        work_interfaces = run_with_logging(
            "firewall-offline-cmd", "--zone=work", "--list-interfaces",
            check=True, stream_output=False,
        ).stdout.split()
        if "wglv0" not in work_interfaces:
            _offlinecmd("--zone=work", "--change-interface=wglv0")
        _offlinecmd("--zone=work", "--remove-forward")
        _offlinecmd("--zone=public", "--remove-forward")
        _offlinecmd("--check-config")

        run_with_logging(
            "nirtcfg", "--set", "section=SystemSettings,token=firewall.enabled,value=True",
            check=True,
        )
        run_with_logging("/etc/init.d/firewalld", "start", check=True)
        for attempt in range(11):
            state = run_with_logging(
                "firewall-cmd", "--state", check=False, stream_output=False
            )
            if state.returncode == 0:
                break
            if state.returncode != 252 or attempt == 10:
                logger.error(f"ERROR: firewalld did not become ready: {state.stdout.strip()}")
                raise subprocess.CalledProcessError(state.returncode, state.args, output=state.stdout)
            time.sleep(1)
        _cmd("--reload")

    def verify(self, args: argparse.Namespace) -> bool:
        print("Verifying firewall configuration...")
        valid: bool = True

        try:
            _cmd("--state")
            _cmd("--check-config")
        except (FileNotFoundError, subprocess.CalledProcessError) as error:
            logger.error(f"ERROR: firewalld is unavailable or its configuration is invalid: {error}")
            return False

        enabled = run_with_logging(
            "nirtcfg", "--get", "section=SystemSettings,token=firewall.enabled,value=False",
            check=False, stream_output=False,
        )
        if enabled.returncode != 0 or enabled.stdout.strip().lower() != "true":
            logger.error(f"ERROR: firewall.enabled must be True; observed {enabled.stdout.strip()!r}")
            valid = False

        valid = _check_setting("--get-default-zone", expected="public", permanent=False) and valid
        valid = _check_setting(
            "--service=ni-labview-realtime", "--get-ports", expected="3079/tcp"
        ) and valid
        for permanent in (True, False):
            checks = [
                _check_setting("--get-zone-of-interface=wglv0", expected="work", permanent=permanent),
            ]
            for zone in ("work", "public"):
                checks.append(_check_setting(
                    f"--zone={zone}", "--query-forward", expected="no",
                    permanent=permanent, expected_returncode=1,
                ))

            for name, ingress, egress, services, ports in _POLICIES:
                checks.append(_check_policy(name, ingress, egress, services, ports, permanent))
            valid = all(checks) and valid

        return valid
