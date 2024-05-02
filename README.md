# NILRT SNAC tool

The NI LinuxRT Secured, Network-Attached Configuration (SNAC) tool is a utility for admins to put a NILRT system into the SNAC configuration.

NOTICE: This tool is under-development and is very unsafe to run on a production system.


# Design

This tool...
* is not (yet) officially supported by NI.
* is only designed to work on NILRT versions 10.3 or later.
	* `grep 'ID=' /etc/os-release`
* only works in runmode. It will refuse to run from safemode.
* requires a network connection to the internet.
* requires access to the core NILRT package feeds.
* can only be run as root.
* has no external library dependencies.
* installs some open source projects at runtime which are not officially supported by NI.
	* wireguard-tools (from the debian package feeds)
	* USBGuard (from its canonical upstream GH repo)


# Installation

## Installation Dependencies

* `make`

## Installing the tool

On a deployed NILRT system, in runmode...

```bash
mkdir -p /usr/local/src/nilrt-snac
git clone https://github.com/amstewart/nilrt-snac /usr/local/src/nilrt-snac
cd /usr/local/src/nilrt-snac
make install
```

## Uninstallation

```bash
cd /usr/local/src/nilrt-snac
make uninstall
```


# Usage

## Runtime Dependencies

* `bash`

## CLI

After installation, the tool should be available in your PATH.

```bash
configure-nilrt-snac
```

After the script completes successfully, you will be instructed to reboot your system. Reboot into runmode and login using `root` with no password.
