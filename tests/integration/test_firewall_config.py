"""Tests for firewalld configuration behavior."""

import argparse
import logging
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

import pytest

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


def _policy_info_output(services="modbus opcua", ingress="public work", egress="HOST",
                        target="CONTINUE", header="ni-dropins"):
    return (
        f"{header}\n  priority: 100\n  target: {target}\n  ingress-zones: {ingress}\n"
        f"  egress-zones: {egress}\n  services: {services}\n  ports: \n  rich rules: \n"
    )


GOOD_PERMANENT = _policy_info_output()
GOOD_RUNTIME = _policy_info_output(header="ni-dropins (active)")


def _check_dropins_with(permanent=GOOD_PERMANENT, runtime=GOOD_RUNTIME, running=True,
                        declared=("opcua", "modbus")):
    """Runs _check_dropins() against --info-policy output for each configuration;
    None means firewalld does not know the policy there.
    """
    commands = []

    def getstatusoutput(cmd):
        commands.append(cmd)
        output = permanent if "--permanent" in cmd else runtime
        if output is None:
            return 140, "Error: INVALID_POLICY: ni-dropins"
        return 0, output

    with (
        patch.object(_firewall_config.subprocess, "getstatusoutput", side_effect=getstatusoutput),
        patch.object(_firewall_config, "_declared_dropin_services", return_value=list(declared)),
        patch.object(_firewall_config, "_firewalld_is_running", return_value=running),
    ):
        result = _firewall_config._check_dropins()
    return result, commands


def test_check_dropins_passes_when_both_configs_match_markers():
    result, commands = _check_dropins_with()
    assert result
    assert commands == [
        "firewall-cmd --permanent --info-policy=ni-dropins",
        "firewall-cmd --info-policy=ni-dropins",
    ]


def test_check_dropins_fails_when_declared_service_missing_at_runtime(caplog):
    result, _ = _check_dropins_with(runtime=_policy_info_output(services="modbus"))
    assert not result
    assert any("drop-in service opcua in policy ni-dropins (runtime)" in m for m in caplog.messages)
    assert not any("(permanent)" in m for m in caplog.messages)


def test_check_dropins_fails_when_declared_service_missing_permanently(caplog):
    result, _ = _check_dropins_with(permanent=_policy_info_output(services="opcua"))
    assert not result
    assert any("drop-in service modbus in policy ni-dropins (permanent)" in m for m in caplog.messages)


def test_check_dropins_fails_without_policy(caplog):
    result, _ = _check_dropins_with(permanent=None)
    assert not result
    assert any("MISSING: firewalld policy ni-dropins (permanent)" in m for m in caplog.messages)


def test_check_dropins_fails_when_runtime_lacks_policy(caplog):
    result, _ = _check_dropins_with(runtime=None)
    assert not result
    assert any("MISSING: firewalld policy ni-dropins (runtime)" in m for m in caplog.messages)


def test_check_dropins_checks_only_permanent_when_firewalld_stopped():
    result, commands = _check_dropins_with(runtime=None, running=False)
    assert result
    assert commands == ["firewall-cmd --permanent --info-policy=ni-dropins"]


@pytest.mark.parametrize("view", ["permanent", "runtime"])
@pytest.mark.parametrize(
    "wrong",
    [
        {"ingress": "work"},
        {"ingress": "ANY"},
        {"egress": "public"},
        {"target": "ACCEPT"},
    ],
)
def test_check_dropins_fails_on_wrong_policy_wiring(view, wrong, caplog):
    result, _ = _check_dropins_with(**{view: _policy_info_output(**wrong)})
    assert not result
    assert any(f"({view})" in m for m in caplog.messages)


def _check_core_services_with(permanent="dhcpv6-client ssh", runtime="dhcpv6-client ssh",
                              running=True):
    """Runs _check_core_services_not_public(); an output of None makes that
    configuration's query fail.
    """
    commands = []

    def getstatusoutput(cmd):
        commands.append(cmd)
        output = permanent if "--permanent" in cmd else runtime
        if output is None:
            return 1, "Error: DBUS_ERROR: Failed to get services"
        return 0, output

    with (
        patch.object(_firewall_config.subprocess, "getstatusoutput", side_effect=getstatusoutput),
        patch.object(_firewall_config, "_firewalld_is_running", return_value=running),
    ):
        result = _firewall_config._check_core_services_not_public()
    return result, commands


def test_check_core_services_not_public_passes_on_snac_public_zone():
    result, commands = _check_core_services_with()
    assert result
    assert commands == [
        "firewall-cmd --permanent --zone=public --list-services",
        "firewall-cmd --zone=public --list-services",
    ]


def test_check_core_services_not_public_fails_on_each_core_service(caplog):
    for service in _firewall_config.CORE_NI_SERVICES:
        caplog.clear()
        result, _ = _check_core_services_with(permanent=f"dhcpv6-client {service} ssh")
        assert not result, service
        assert any(f"service {service} (permanent):" in m for m in caplog.messages), service


def test_check_core_services_not_public_detects_runtime_only_exposure(caplog):
    result, _ = _check_core_services_with(runtime="dhcpv6-client http ssh")
    assert not result
    assert any("service http (runtime):" in m for m in caplog.messages)
    assert not any("(permanent)" in m for m in caplog.messages)


def test_check_core_services_not_public_reports_every_exposed_service(caplog):
    exposed = "dhcpv6-client http https mdns ni-logos-xt ni-mxs ni-service-locator ssh"
    result, _ = _check_core_services_with(permanent=exposed, runtime=exposed)
    assert not result
    reported = [m for m in caplog.messages if "--zone=public service" in m]
    assert len(reported) == 2 * len(_firewall_config.CORE_NI_SERVICES)


@pytest.mark.parametrize("view", ["permanent", "runtime"])
def test_check_core_services_not_public_fails_when_query_fails(view, caplog):
    result, _ = _check_core_services_with(**{view: None})
    assert not result
    assert any(
        f"could not list --zone=public services ({view}): Error: DBUS_ERROR" in m
        for m in caplog.messages
    )


def test_check_core_services_not_public_only_permanent_when_firewalld_stopped():
    result, commands = _check_core_services_with(runtime="http", running=False)
    assert result
    assert commands == ["firewall-cmd --permanent --zone=public --list-services"]

