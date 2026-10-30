"""Run as root on a configured NILRT testbench: python3 test_firewall_policy.py."""

import os
from pathlib import Path
import subprocess
import sys
import unittest


NAMESPACE = "snac-policy-test"
HOST_INTERFACE = "snac-test0"
PEER_INTERFACE = "snac-test1"
HOST_ADDRESSES = ("192.0.2.1", "2001:db8:55::1")
PEER_ADDRESSES = ("192.0.2.2", "2001:db8:55::2")
MARKER = Path("/etc/ni/firewall/open.d/99-snac-policy-test.conf")

SERVER = """
import socket, sys
address, port = sys.argv[1], int(sys.argv[2])
family = socket.AF_INET6 if ":" in address else socket.AF_INET
with socket.socket(family, socket.SOCK_STREAM) as server:
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((address, port))
    server.listen(1)
    server.settimeout(5)
    print("ready", flush=True)
    connection, _ = server.accept()
    with connection:
        connection.settimeout(2)
        connection.sendall(connection.recv(4))
"""

CLIENT = """
import errno, socket, sys
try:
    with socket.create_connection((sys.argv[1], int(sys.argv[2])), timeout=1) as client:
        client.sendall(b"snac")
        assert client.recv(4) == b"snac"
except TimeoutError as error:
    print(error, file=sys.stderr)
    sys.exit(3)
except OSError as error:
    if error.errno not in (errno.ECONNREFUSED, errno.EHOSTUNREACH):
        raise
    print(error, file=sys.stderr)
    sys.exit(3)
"""


def run(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True)


class FirewallPolicyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.geteuid() != 0:
            raise RuntimeError("These packet tests require root on a NILRT testbench.")
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
        for host, peer in zip(HOST_ADDRESSES, PEER_ADDRESSES):
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
        index = 1 if ipv6 else 0
        address = HOST_ADDRESSES[index] if inbound else PEER_ADDRESSES[index]
        namespace = ("ip", "netns", "exec", NAMESPACE)
        server_command = () if inbound else namespace
        client_command = namespace if inbound else ()
        server = subprocess.Popen(
            (*server_command, sys.executable, "-c", SERVER, address, str(port)),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        try:
            ready = server.stdout.readline().strip()
            if ready != "ready":
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
    unittest.main()
