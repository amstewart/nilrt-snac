"""Tests for firewalld configuration behavior."""

import argparse
import logging
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

from nilrt_snac import opkg
from nilrt_snac._configs import _firewall_config


def test_configure_dry_run_logs_package_installs(caplog):
    config = _firewall_config._FirewallConfig()
    packages = [
        "firewalld",
        "firewalld-offline-cmd",
        "firewalld-log-rotate",
        "ni-firewalld-servicedefs",
        "ni-firewall-dropins",
    ]
    caplog.set_level(logging.INFO, logger="nilrt_snac")

    with (
        patch.object(config._opkg_helper, "_dry_run", True, create=True),
        patch.object(config._opkg_helper, "_installed_packages", []),
        patch.object(opkg, "run_with_logging") as package_command,
        patch.object(_firewall_config, "_offlinecmd") as offlinecmd,
        patch.object(_firewall_config, "_cmd") as cmd,
        patch.object(_firewall_config, "run_with_logging") as system_command,
    ):
        config.configure(argparse.Namespace(dry_run=True))

        assert config._opkg_helper._installed_packages == packages
        assert caplog.messages == [
            f"Installing IPK: {package}" for package in packages
        ]
        package_command.assert_not_called()
        offlinecmd.assert_not_called()
        cmd.assert_not_called()
        system_command.assert_not_called()


def test_configure_allows_ni_orb_rpc_server():
    config = _firewall_config._FirewallConfig()
    calls = []
    system_calls = []

    def offlinecmd(*args):
        calls.append(args)

    def run_with_logging(*args, **kwargs):
        system_calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0)

    with (
        patch.object(config._opkg_helper, "install"),
        patch.object(_firewall_config, "_offlinecmd", side_effect=offlinecmd),
        patch.object(_firewall_config, "_cmd"),
        patch.object(_firewall_config, "run_with_logging", side_effect=run_with_logging),
        patch.object(
            _firewall_config.subprocess,
            "run",
            side_effect=[
                subprocess.TimeoutExpired(["firewall-cmd", "--state"], timeout=2),
                subprocess.CompletedProcess(
                    ["firewall-cmd", "--state"], 0, stdout="running"
                ),
            ],
        ),
    ):
        config.configure(argparse.Namespace(dry_run=False))

    assert (
        "--policy=work-in",
        "--add-service=ni-labview-realtime",
        "--add-service=ni-labview-viserver",
        "--add-service=ni-logos-xt",
        "--add-service=ni-mxs",
        "--add-service=ni-orb-rpc-server",
        "--add-service=ni-service-locator",
    ) in calls
    assert not any("--add-rich-rule=" in arg for call in calls for arg in call)
    assert (
        ("nirtcfg", "--set", "section=SystemSettings,token=firewall.enabled,value=True"),
        {"check": True},
    ) in system_calls
    assert (("/etc/init.d/firewalld", "start"), {"check": True}) in system_calls

    test_path = Path(__file__).resolve()
    source_definition = (
        test_path.parents[2] / "src/firewalld/services/ni-orb-rpc-server.xml"
    )
    if source_definition.is_file():
        service_definition = source_definition
    else:
        service_definition = next(
            (
                parent / "usr/lib/firewalld/services/ni-orb-rpc-server.xml"
                for parent in test_path.parents
                if (parent / "usr/lib/firewalld/services/ni-orb-rpc-server.xml").is_file()
            ),
            Path("/usr/lib/firewalld/services/ni-orb-rpc-server.xml"),
        )
    service = ET.parse(service_definition).getroot()
    assert service.find("./port").attrib == {"protocol": "tcp", "port": "43973"}


def test_verify_fails_when_firewall_is_disabled():
    config = _firewall_config._FirewallConfig()
    with (
        patch.object(
            _firewall_config.subprocess,
            "getoutput",
            side_effect=["123", "false"],
        ),
        patch.object(_firewall_config, "_cmd"),
        patch.object(_firewall_config, "_check_target", return_value=True),
        patch.object(_firewall_config, "_check_service", return_value=True),
        patch.object(_firewall_config, "_check_service_info", return_value=True),
        patch.object(_firewall_config, "_check_dropins", return_value=True),
        patch.object(_firewall_config, "_check_core_services_not_public", return_value=True),
    ):
        assert not config.verify(argparse.Namespace())


def _configure_recording_order(apply_returncode=0):
    """Runs configure() with firewalld mocked out; returns the ordered calls."""
    config = _firewall_config._FirewallConfig()
    events = []

    def run_with_logging(*args, **kwargs):
        events.append(("run", args))
        return subprocess.CompletedProcess(
            args, apply_returncode if args == ("ni-firewall-apply",) else 0
        )

    with (
        patch.object(config._opkg_helper, "install"),
        patch.object(_firewall_config, "_offlinecmd",
                     side_effect=lambda *a: events.append(("offline", a))),
        patch.object(_firewall_config, "_cmd", side_effect=lambda *a: events.append(("cmd", a))),
        patch.object(_firewall_config, "run_with_logging", side_effect=run_with_logging),
        patch.object(_firewall_config, "_firewalld_is_running", return_value=True),
    ):
        config.configure(argparse.Namespace(dry_run=False))
    return events


def test_configure_applies_dropins_after_reload():
    events = _configure_recording_order()

    assert events.index(("offline", ("--reset-to-defaults",))) < events.index(("cmd", ("--reload",)))
    assert events.index(("cmd", ("--reload",))) < events.index(("run", ("ni-firewall-apply",)))
    offline_args = [arg for kind, args in events if kind == "offline" for arg in args]
    assert not any(_firewall_config.DROPINS_POLICY in arg for arg in offline_args), (
        "SNAC must not modify the ni-dropins policy itself"
    )


def test_configure_warns_when_dropins_apply_fails(caplog):
    caplog.set_level(logging.WARNING, logger="nilrt_snac")

    events = _configure_recording_order(apply_returncode=1)

    assert ("run", ("ni-firewall-apply",)) in events
    assert any("ni-firewall-apply failed" in m for m in caplog.messages)


def test_declared_dropin_services_matches_ni_firewall_apply(tmp_path):
    (tmp_path / "10-multi").write_text("opcua\n# comment\n\n  modbus  # inline\nopcua\n")
    (tmp_path / "20-dnp3.conf").write_text("")
    (tmp_path / "ni-veristand-engine").write_text("# only a comment\n")
    (tmp_path / "30-dup").write_text("modbus\n")
    (tmp_path / ".hidden").write_text("ssh\n")
    (tmp_path / "subdir").mkdir()

    assert _firewall_config._declared_dropin_services(tmp_path) == [
        "opcua",
        "modbus",
        "dnp3",
        "ni-veristand-engine",
    ]


def test_declared_dropin_services_without_open_d(tmp_path):
    assert _firewall_config._declared_dropin_services(tmp_path / "missing") == []


def _check_dropins_with(outputs, declared=()):
    """Runs _check_dropins() with firewall-cmd output keyed by its trailing option."""

    def getoutput(cmd):
        for option, output in outputs.items():
            if cmd.endswith(option):
                return output
        raise AssertionError(f"unexpected command: {cmd}")

    with (
        patch.object(_firewall_config.subprocess, "getoutput", side_effect=getoutput),
        patch.object(_firewall_config, "_declared_dropin_services", return_value=list(declared)),
    ):
        return _firewall_config._check_dropins()


GOOD_DROPINS = {
    "--get-policies": "allow-host-ipv6 ni-dropins public-in work-in",
    "--get-target": "CONTINUE",
    "--list-ingress-zones": "public work",
    "--list-egress-zones": "HOST",
    "--list-services": "modbus opcua",
}


def test_check_dropins_passes_when_policy_matches_markers():
    assert _check_dropins_with(GOOD_DROPINS, declared=["opcua", "modbus"])


def test_check_dropins_fails_when_declared_service_missing(caplog):
    assert not _check_dropins_with(GOOD_DROPINS, declared=["opcua", "dnp3"])
    assert any("drop-in service dnp3" in m for m in caplog.messages)


def test_check_dropins_fails_without_policy(caplog):
    assert not _check_dropins_with({**GOOD_DROPINS, "--get-policies": "public-in work-in"})
    assert any("MISSING: firewalld policy ni-dropins" in m for m in caplog.messages)


def test_check_dropins_fails_on_wrong_ingress_zones():
    assert not _check_dropins_with({**GOOD_DROPINS, "--list-ingress-zones": "work"})
    assert not _check_dropins_with({**GOOD_DROPINS, "--list-ingress-zones": "ANY"})


def test_check_dropins_fails_on_wrong_egress_or_target():
    assert not _check_dropins_with({**GOOD_DROPINS, "--list-egress-zones": "public"})
    assert not _check_dropins_with({**GOOD_DROPINS, "--get-target": "ACCEPT"})


def _check_core_services_with(public_services):
    with patch.object(
        _firewall_config.subprocess, "getoutput", return_value=public_services
    ) as getoutput:
        result = _firewall_config._check_core_services_not_public()
    getoutput.assert_called_once_with("firewall-cmd --permanent --zone=public --list-services")
    return result


def test_check_core_services_not_public_passes_on_snac_public_zone():
    assert _check_core_services_with("dhcpv6-client ssh")


def test_check_core_services_not_public_fails_on_each_core_service(caplog):
    for service in _firewall_config.CORE_NI_SERVICES:
        caplog.clear()
        assert not _check_core_services_with(f"dhcpv6-client {service} ssh"), service
        assert any(f"service {service}:" in m for m in caplog.messages), service


def test_check_core_services_not_public_reports_every_exposed_service(caplog):
    assert not _check_core_services_with(
        "dhcpv6-client http https mdns ni-logos-xt ni-mxs ni-service-locator ssh"
    )
    reported = [m for m in caplog.messages if "--zone=public service" in m]
    assert len(reported) == len(_firewall_config.CORE_NI_SERVICES)
