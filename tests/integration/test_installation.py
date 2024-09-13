"""These tests verify that required package files are installed to their correct locations."""


# NOTE: We intentionally do not test for:
# * The wrapper binary (nilrt-snac), because that is the domain of the distro
#   package.
# * The installation location of the python libs, as they are configurable by
#   the user/distro.

from pathlib import Path
import shutil

import nilrt_snac
import nilrt_snac._pre_reqs


def test_conflicts_ipk():
	"""The nilrt-snac-conflicts IPK should be installed to the data path."""
	assert (nilrt_snac.SNAC_DATA_DIR / "nilrt-snac-conflicts.ipk").exists()


def test_iptables():
	"""This package requires the iptables module."""
	nilrt_snac._pre_reqs._check_iptables()  # assert no raise


def test_opkg_binary():
	"""This package requires the opkg package manager."""
	assert shutil.which("opkg")


def test_supported_distro():
	"""This package only works on NI LinuxRT runmode."""
	nilrt_snac._pre_reqs._check_nilrt()    # assert no raise
	nilrt_snac._pre_reqs._check_runmode()  # assert no raise


def test_wireguard_conf():
	"""The wireguard configuration bits included with this project should be installed."""
	assert Path("/etc/wireguard/wglv0.conf").exists()
	assert Path("/etc/init.d/ni-wireguard-labview").exists()
