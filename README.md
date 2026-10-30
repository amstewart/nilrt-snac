# NILRT SNAC Configuration Tool

The NILRT SNAC configuration tool is a utility that helps system administrators place their NI LinuxRT (NILRT) devices into a Secured, Network-Attached Configuration (SNAC).


# Design

This tool...
* only works in runmode. It will refuse to run from safemode.
* requires a network connection to the NI IPK feeds server, or access to an offline feeds server.
* can only be run as root.


# Installation


## Installation from the NILRT IPK Feeds

As of NILRT Base System Images 11.0 (2025Q1) and later, this project can be installed directly from the vendor's packaging.

This is the preferred method of installation for users.

```bash
opkg update && \
	opkg install nilrt-snac
```


### Uninstallation

```bash
opkg remove nilrt-snac
```


## Installation From Source

Install this project's build dependencies.

* `make`

Then build the project.

```bash
mkdir -p /usr/local/src
wget 'https://github.com/ni/nilrt-snac/archive/refs/heads/master.tar.gz' -O - | tar xzf - -C /usr/local/src
cd /usr/local/src/nilrt-snac*
make install  # prefix defaults to /usr/local
```

### Uninstallation

```bash
cd /usr/local/src/nilrt-snac
make uninstall sysconfdir=/etc
```


# Usage

## Runtime Dependencies

* `bash`
* `python3`


## CLI

After installation, the tool should be available in your PATH.

The tool has two primary modes of operation: `configure` and `verify`.


### Configure

In 'configure' mode, the tool will **apply** the SNAC configuration to the NILRT system.
This is a destructive operation that should only be run by a system maintainer during deployment.

```bash
nilrt-snac configure
```

After the script completes successfully, you will be instructed to reboot your system. Reboot into runmode and login using `root` with no password.

#### Firewall configuration

SNAC enables firewalld at boot through `SystemSettings firewall.enabled` and
starts it when configuring the device. The default zone remains `public`;
the WireGuard interface `wglv0` is assigned to `work`. Forwarding within both
zones is disabled.

SNAC replaces its four `work-in`, `work-out`, `public-in`, and `public-out`
policies, but preserves distro-owned service definitions, zones, and NI firewall
drop-ins. All four policies reject unmatched traffic at priority `-1000`,
before zone rules are evaluated. Consequently, services opened in the default
zone by NI package installation or boot hooks do not bypass SNAC restrictions.

* Public inbound traffic permits SSH, WireGuard, and DHCPv6 client traffic.
* Work inbound traffic permits SSH, DHCPv6 client traffic, mDNS, LabVIEW Real-Time/VI Server,
  NI Logos XT, MXS, Service Locator, NI RPC (TCP 43973), and niroco (TCP 55184).
  The RPC port is allowed directly because newer distro service-definition
  packages no longer provide `ni-rpc-server`.
* Public outbound traffic permits DHCP/DHCPv6, HTTP/HTTPS, WireGuard, DNS, and NTP.
* Work outbound traffic permits SSH, HTTP/HTTPS, syslog, NI Logos XT, AMQP,
  and Salt master traffic.
* ICMP and IPv6 ICMP are permitted in both directions on both zones.

Firewall verification checks both permanent and runtime policies, including
their allowlists, targets, priorities, zone bindings, and forwarding state.


### Verify

In 'verify' mode, the tool will **check** that the NILRT system is in the SNAC configuration, without modifying the system state.
The operation will fail if any of the checks fail.

```bash
nilrt-snac verify
```
