"""Firewall configuration regressions independent of installed NILRT packages."""

import argparse
import subprocess
from unittest.mock import Mock

import pytest

from nilrt_snac._configs import _firewall_config as firewall


SERVICES = {
    "work-in": (
        "ssh dhcpv6-client mdns ni-labview-realtime ni-labview-viserver "
        "ni-logos-xt ni-mxs ni-service-locator"
    ),
    "work-out": "ssh http https syslog ni-logos-xt amqp salt-master",
    "public-in": "ssh wireguard dhcpv6-client",
    "public-out": "dhcp dhcpv6 http https wireguard dns ntp",
}


def policy_output(name):
    zone, direction = name.split("-")
    ingress, egress = (zone, "HOST") if direction == "in" else ("HOST", zone)
    ports = "43973/tcp 55184/tcp" if name == "work-in" else ""
    return (
        f"{name} (active)\n"
        "  priority: -1000\n"
        "  target: REJECT\n"
        f"  ingress-zones: {ingress}\n"
        f"  egress-zones: {egress}\n"
        f"  services: {SERVICES[name]}\n"
        f"  ports: {ports}\n"
        "  protocols: icmp ipv6-icmp\n"
        "  masquerade: no\n"
        "  forward-ports: \n"
        "  source-ports: \n"
        "  icmp-blocks: \n"
        "  rich rules: \n"
    )


@pytest.fixture
def commands(monkeypatch):
    def run(*args, **kwargs):
        output, returncode = "", 0
        if "--get-policies" in args:
            output = "allow-host-ipv6 work-in work-out public-in public-out"
        elif "--get-default-zone" in args:
            output = "public"
        elif "--list-interfaces" in args:
            output = "wglv0"
        elif "--get-zone-of-interface=wglv0" in args:
            output = "work"
        elif "--query-forward" in args:
            output, returncode = "no", 1
        elif "--get-ports" in args:
            output = "3079/tcp"
        elif args[0] == "nirtcfg" and "--get" in args:
            output = "True"
        elif "--list-all" in args:
            name = next(arg.split("=", 1)[1] for arg in args if arg.startswith("--policy="))
            output = policy_output(name)
        return subprocess.CompletedProcess(args, returncode, stdout=output)

    mock = Mock(side_effect=run)
    monkeypatch.setattr(firewall, "run_with_logging", mock)
    monkeypatch.setattr(firewall, "opkg_helper", Mock())
    return mock


def test_configure_preserves_distro_configuration(commands):
    config = firewall._FirewallConfig()
    config.configure(argparse.Namespace(dry_run=False))
    calls = [call.args for call in commands.call_args_list]
    assert not any("--reset-to-defaults" in call for call in calls)
    assert not any("--delete-policy=allow-host-ipv6" in call for call in calls)
    assert not any("--add-service=ni-rpc-server" in call for call in calls)
    assert not any("--set-default-zone=public" in call for call in calls)
    assert not any("--change-interface=wglv0" in call for call in calls)
    for name in SERVICES:
        assert ("firewall-offline-cmd", "-q", f"--delete-policy={name}") in calls
        assert ("firewall-offline-cmd", "-q", f"--new-policy={name}") in calls
        service_call = next(call for call in calls if f"--policy={name}" in call
                            and any(arg.startswith("--add-service=") for arg in call))
        assert set(service_call[3:]) == {f"--add-service={s}" for s in SERVICES[name].split()}
        assert ("firewall-offline-cmd", "-q", f"--policy={name}", "--set-target=REJECT") in calls
        assert ("firewall-offline-cmd", "-q", f"--policy={name}", "--set-priority=-1000") in calls
    assert (
        "firewall-offline-cmd", "-q", "--policy=work-in",
        "--add-port=43973/tcp", "--add-port=55184/tcp",
    ) in calls
    enable = ("nirtcfg", "--set", "section=SystemSettings,token=firewall.enabled,value=True")
    assert calls.index(enable) < calls.index(("/etc/init.d/firewalld", "start"))
    assert calls[-1] == ("firewall-cmd", "-q", "--reload")


def test_configure_new_policies_and_interface(commands):
    original = commands.side_effect

    def run(*args, **kwargs):
        result = original(*args, **kwargs)
        if "--get-policies" in args:
            result.stdout = "allow-host-ipv6"
        elif "--get-default-zone" in args:
            result.stdout = "work"
        elif "--list-interfaces" in args:
            result.stdout = ""
        return result

    commands.side_effect = run
    firewall._FirewallConfig().configure(argparse.Namespace(dry_run=False))
    calls = [call.args for call in commands.call_args_list]
    assert not any(any(arg.startswith("--delete-policy=") for arg in call) for call in calls)
    assert ("firewall-offline-cmd", "-q", "--set-default-zone=public") in calls
    assert ("firewall-offline-cmd", "-q", "--zone=work", "--change-interface=wglv0") in calls


def test_configure_dry_run(commands):
    config = firewall._FirewallConfig()
    config.configure(argparse.Namespace(dry_run=True))
    commands.assert_not_called()
    config._opkg_helper.install.assert_not_called()


@pytest.mark.parametrize("returncode", [252, 2])
def test_configure_waits_or_reports_startup_failure(commands, monkeypatch, returncode):
    original = commands.side_effect
    sleep = Mock()
    monkeypatch.setattr(firewall.time, "sleep", sleep)
    attempts = 0

    def run(*args, **kwargs):
        nonlocal attempts
        if args == ("firewall-cmd", "--state"):
            attempts += 1
            if attempts == 1:
                return subprocess.CompletedProcess(args, returncode, stdout="not running")
        return original(*args, **kwargs)

    commands.side_effect = run
    if returncode == 252:
        firewall._FirewallConfig().configure(argparse.Namespace(dry_run=False))
        assert attempts == 2
        sleep.assert_called_once_with(1)
    else:
        with pytest.raises(subprocess.CalledProcessError):
            firewall._FirewallConfig().configure(argparse.Namespace(dry_run=False))
        sleep.assert_not_called()


def test_configure_startup_timeout(commands, monkeypatch):
    original = commands.side_effect
    monkeypatch.setattr(firewall.time, "sleep", Mock())

    def run(*args, **kwargs):
        if args == ("firewall-cmd", "--state"):
            return subprocess.CompletedProcess(args, 252, stdout="not running")
        return original(*args, **kwargs)

    commands.side_effect = run
    with pytest.raises(subprocess.CalledProcessError):
        firewall._FirewallConfig().configure(argparse.Namespace(dry_run=False))
    assert not any(call.args[-1] == "--reload" for call in commands.call_args_list)


def test_verify_accepts_distro_zone_openings(commands):
    assert firewall._FirewallConfig().verify(argparse.Namespace())
    calls = [call.args for call in commands.call_args_list]
    assert not any("--zone=public" in call and "--query-service=ni-labview-realtime" in call
                   for call in calls)
    for name in SERVICES:
        assert ("firewall-cmd", "--permanent", f"--policy={name}", "--list-all") in calls
        assert ("firewall-cmd", f"--policy={name}", "--list-all") in calls


@pytest.mark.parametrize("permanent", [True, False])
@pytest.mark.parametrize("old,new", [
    ("target: REJECT", "target: CONTINUE"),
    ("priority: -1000", "priority: 1000"),
    ("ingress-zones: public", "ingress-zones: work"),
    ("services: ssh wireguard dhcpv6-client", "services: ssh wireguard dhcpv6-client http"),
    ("ports: ", "ports: 3079/tcp"),
    ("protocols: icmp ipv6-icmp", "protocols: icmp ipv6-icmp tcp"),
    ("rich rules: ", 'rich rules: \n    rule family="ipv4" accept'),
])
def test_verify_rejects_policy_drift(commands, permanent, old, new):
    original = commands.side_effect

    def run(*args, **kwargs):
        result = original(*args, **kwargs)
        if ("--list-all" in args and "--policy=public-in" in args
                and ("--permanent" in args) == permanent):
            result.stdout = result.stdout.replace(old, new)
        return result

    commands.side_effect = run
    assert not firewall._FirewallConfig().verify(argparse.Namespace())


@pytest.mark.parametrize("failure", ["daemon", "config", "enabled", "forward", "interface", "rpc"])
def test_verify_reports_failures(commands, failure):
    original = commands.side_effect

    def run(*args, **kwargs):
        if ((failure == "daemon" and "--state" in args)
                or (failure == "config" and "--check-config" in args)):
            raise subprocess.CalledProcessError(252, args)
        result = original(*args, **kwargs)
        if failure == "enabled" and args[0] == "nirtcfg":
            result.stdout = "False"
        elif failure == "forward" and "--query-forward" in args:
            result.stdout, result.returncode = "yes", 0
        elif failure == "interface" and "--get-zone-of-interface=wglv0" in args:
            result.stdout = "public"
        elif failure == "rpc" and "--policy=work-in" in args and "--list-all" in args:
            result.stdout = result.stdout.replace("43973/tcp ", "")
        return result

    commands.side_effect = run
    assert not firewall._FirewallConfig().verify(argparse.Namespace())
