"""Exercise the NILRT firewall policy with real IPv4 and IPv6 TCP connections.

Run this disruptive system test as root on a disposable, configured NILRT
testbench with firewalld and ``ni-firewall-apply`` available. It creates a
network namespace and veth pair, binds the host end to the public/work zones,
and temporarily writes a drop-in under ``/etc/ni/firewall/open.d``. Do not run
it concurrently with another copy or while relying on the testbench's firewall
configuration.

Supply four unused addresses for the test link: the IPv4 pair must share a
``/30`` subnet and the IPv6 pair must share a ``/64`` subnet. Neither subnet
may overlap an existing interface or route. ``*-host`` addresses go on the
testbench; ``*-peer`` addresses go in the test namespace. The temporary
namespace/interface names and marker file must be unused, and the marker
directory must exist. For example:

    python3 tests/system/test_firewall_policy.py \\
        --ipv4-host HOST_IPV4 --ipv4-peer PEER_IPV4 \\
        --ipv6-host HOST_IPV6 --ipv6-peer PEER_IPV6

The test also requires ``ip``, ``firewall-cmd``, and the NI service definitions
``ni-labview-realtime``, ``ni-mxs``, ``http``, and ``https``. Existing listeners
on tested ports are used rather than stopped or replaced.
"""

import argparse
import ipaddress
import os
from pathlib import Path
import subprocess
import sys
import unittest


NAMESPACE = "snac-policy-test"
HOST_INTERFACE = "snac-test0"
PEER_INTERFACE = "snac-test1"
MARKER = Path("/etc/ni/firewall/open.d/99-snac-policy-test.conf")

SERVER = """
import errno, socket, sys
address, port = sys.argv[1], int(sys.argv[2])
family = socket.AF_INET6 if ":" in address else socket.AF_INET
with socket.socket(family, socket.SOCK_STREAM) as server:
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind((address, port))
    except OSError as error:
        if error.errno != errno.EADDRINUSE:
            raise
        try:
            with socket.create_connection((address, port), timeout=1):
                pass
        except OSError as probe_error:
            raise RuntimeError(
                f"{address}:{port} is already bound but no listener accepted a connection"
            ) from probe_error
        print("occupied", flush=True)
        sys.exit(0)
    server.listen(1)
    server.settimeout(5)
    print("ready", flush=True)
    server.accept()
"""

CLIENT = """
import errno, socket, sys
try:
    socket.create_connection((sys.argv[1], int(sys.argv[2])), timeout=1).close()
except TimeoutError as error:
    print(error, file=sys.stderr)
    sys.exit(3)
except OSError as error:
    if error.errno not in (
        errno.ECONNREFUSED, errno.EHOSTUNREACH, errno.EACCES, errno.EPERM
    ):
        raise
    print(error, file=sys.stderr)
    sys.exit(3)
"""


def run(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True)


class FirewallPolicyTest(unittest.TestCase):
    host_addresses: tuple[str, str] | None = None
    peer_addresses: tuple[str, str] | None = None

    @classmethod
    def setUpClass(cls):
        if os.geteuid() != 0:
            raise RuntimeError("These packet tests require root on a NILRT testbench.")
        if cls.host_addresses is None or cls.peer_addresses is None:
            raise RuntimeError("Run this test with all four test-link address options.")
        run("firewall-cmd", "--state")
        if any(line.split()[0] == NAMESPACE for line in run("ip", "netns", "list").stdout.splitlines()):
            raise RuntimeError(f"Test namespace {NAMESPACE} already exists; refusing to alter it.")
        if MARKER.exists():
            raise RuntimeError(f"Test marker {MARKER} already exists; refusing to alter it.")

        run("ip", "netns", "add", NAMESPACE)
        cls.addClassCleanup(run, "ip", "netns", "delete", NAMESPACE)
        run("ip", "link", "add", HOST_INTERFACE, "type", "veth", "peer", "name", PEER_INTERFACE)
        cls.addClassCleanup(run, "ip", "link", "delete", HOST_INTERFACE)
        run("ip", "link", "set", PEER_INTERFACE, "netns", NAMESPACE)
        run("ip", "link", "set", HOST_INTERFACE, "up")
        run("ip", "netns", "exec", NAMESPACE, "ip", "link", "set", PEER_INTERFACE, "up")
        run("firewall-cmd", "--zone=public", f"--change-interface={HOST_INTERFACE}")
        cls.addClassCleanup(cls.remove_zone_binding)

        # Exercise the actual package/boot hook, not just firewall-cmd zone additions.
        original_runtime = set(run("firewall-cmd", "--zone=public", "--list-services").stdout.split())
        MARKER.write_text("ni-labview-realtime\nni-mxs\nhttp\nhttps\n")
        cls.addClassCleanup(cls.remove_marker, original_runtime)
        run("ni-firewall-apply")
        for service in ("ni-labview-realtime", "ni-mxs", "http", "https"):
            run("firewall-cmd", "--zone=public", f"--query-service={service}")

        # Assign addresses after hotplug and firewall hooks have configured the link.
        host_addresses = cls.host_addresses
        peer_addresses = cls.peer_addresses
        for host, peer in zip(host_addresses, peer_addresses):
            ipv6 = ":" in host
            prefix = "64" if ipv6 else "30"
            options = ("nodad",) if ipv6 else ()
            run("ip", "addr", "add", f"{host}/{prefix}", "dev", HOST_INTERFACE, *options)
            run("ip", "netns", "exec", NAMESPACE, "ip", "addr", "add",
                f"{peer}/{prefix}", "dev", PEER_INTERFACE, *options)

    @staticmethod
    def remove_marker(original_runtime):
        MARKER.unlink()
        run("ni-firewall-apply")
        current = set(run("firewall-cmd", "--zone=public", "--list-services").stdout.split())
        for service in ("ni-labview-realtime", "ni-mxs", "http", "https"):
            if service in current and service not in original_runtime:
                run("firewall-cmd", "--zone=public", f"--remove-service={service}")
            elif service in original_runtime and service not in current:
                run("firewall-cmd", "--zone=public", f"--add-service={service}")

    @staticmethod
    def remove_zone_binding():
        zone = run("firewall-cmd", f"--get-zone-of-interface={HOST_INTERFACE}").stdout.strip()
        run("firewall-cmd", f"--zone={zone}", f"--remove-interface={HOST_INTERFACE}")

    def check_packet(self, zone, inbound, ipv6, port, allowed):
        current_zone = run(
            "firewall-cmd", f"--get-zone-of-interface={HOST_INTERFACE}"
        ).stdout.strip()
        if current_zone != zone:
            run("firewall-cmd", f"--zone={zone}", f"--change-interface={HOST_INTERFACE}")
        assert self.host_addresses is not None
        assert self.peer_addresses is not None
        index = 1 if ipv6 else 0
        address = self.host_addresses[index] if inbound else self.peer_addresses[index]
        namespace = ("ip", "netns", "exec", NAMESPACE)
        server_command = () if inbound else namespace
        client_command = namespace if inbound else ()
        server = subprocess.Popen(
            (*server_command, sys.executable, "-c", SERVER, address, str(port)),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        try:
            ready = server.stdout.readline().strip()
            if ready not in ("ready", "occupied"):
                _, errors = server.communicate(timeout=5)
                self.fail(f"Listener failed to start: {errors}")
            client = subprocess.run(
                (*client_command, sys.executable, "-c", CLIENT, address, str(port)),
                capture_output=True, text=True, timeout=5,
            )
            self.assertEqual(client.returncode, 0 if allowed else 3, client.stderr)
            if allowed:
                _, errors = server.communicate(timeout=5)
                self.assertEqual(server.returncode, 0, errors)
        finally:
            if server.poll() is None:
                server.terminate()
            server.communicate(timeout=5)

    def test_public_inbound_stays_restricted_after_distro_hook(self):
        for ipv6 in (False, True):
            for port in (443, 3079, 43973, 55184, 51700, 12345):
                with self.subTest(ipv6=ipv6, port=port):
                    self.check_packet("public", True, ipv6, port, False)

    def test_work_inbound_preserves_ni_access(self):
        for ipv6 in (False, True):
            for port in (3079, 43973, 55184, 51700):
                with self.subTest(ipv6=ipv6, port=port):
                    self.check_packet("work", True, ipv6, port, True)
            with self.subTest(ipv6=ipv6, port=12345):
                self.check_packet("work", True, ipv6, 12345, False)

    def test_outbound_allowlists(self):
        for ipv6 in (False, True):
            for zone in ("public", "work"):
                for port, allowed in ((80, True), (443, True), (12345, False)):
                    with self.subTest(ipv6=ipv6, zone=zone, port=port):
                        self.check_packet(zone, False, ipv6, port, allowed)
                with self.subTest(ipv6=ipv6, zone=zone, port=5672):
                    self.check_packet(zone, False, ipv6, 5672, zone == "work")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ipv4-host", type=ipaddress.IPv4Address, required=True)
    parser.add_argument("--ipv4-peer", type=ipaddress.IPv4Address, required=True)
    parser.add_argument("--ipv6-host", type=ipaddress.IPv6Address, required=True)
    parser.add_argument("--ipv6-peer", type=ipaddress.IPv6Address, required=True)
    args, unittest_args = parser.parse_known_args()

    ipv4_network = ipaddress.ip_network(f"{args.ipv4_host}/30", strict=False)
    ipv6_network = ipaddress.ip_network(f"{args.ipv6_host}/64", strict=False)
    if (
        args.ipv4_peer not in ipv4_network
        or args.ipv4_peer in (ipv4_network.network_address, ipv4_network.broadcast_address)
        or args.ipv4_host in (ipv4_network.network_address, ipv4_network.broadcast_address)
    ):
        parser.error("--ipv4-host and --ipv4-peer must be usable addresses in the same /30")
    if args.ipv6_peer not in ipv6_network:
        parser.error("--ipv6-host and --ipv6-peer must be in the same /64")
    if args.ipv4_host == args.ipv4_peer or args.ipv6_host == args.ipv6_peer:
        parser.error("host and peer addresses must be different")

    FirewallPolicyTest.host_addresses = (str(args.ipv4_host), str(args.ipv6_host))
    FirewallPolicyTest.peer_addresses = (str(args.ipv4_peer), str(args.ipv6_peer))
    unittest.main(argv=[sys.argv[0], *unittest_args])
