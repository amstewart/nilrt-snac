import os
import pathlib
import subprocess

from nilrt_snac._common import get_distro
from nilrt_snac.OpkgHelper import opkg_helper

from nilrt_snac import Errors, SNACError, logger

# Check that the effective UID of this bash script is root (UID 0)
def _check_euid_root():
    print("Checking EUID")
    if os.geteuid() != 0:
        raise SNACError("This script must be run as root.", Errors.EX_BAD_ENVIRONEMNT)


# Check that iptables is available.
# NOTE: The ip_tables kernel module is only loaded once the first call to iptables has
#   been made, (inlcuding rule creation).
def _check_iptables():
    print("Checking iptables")
    if not opkg_helper.is_installed("iptables"):
        logger.debug("  Installing iptables")
        opkg_helper.install("iptables")

    logger.debug("  Ensuring iptables is loaded")
    try:
        subprocess.run(["iptables", "-L"])
    except Exception:
        raise SNACError("Failed to load iptables.", Errors.EX_CHECK_FAILURE)

    logger.debug("  Ensuring iptables is installed")
    result = subprocess.run(["lsmod"], stdout=subprocess.PIPE)
    if "ip_tables" not in result.stdout.decode():
        raise SNACError("Failed to find ip_tables module.", Errors.EX_CHECK_FAILURE)


# Check that the script isn't executing within a safemode context
def _check_runmode():
    safe_mode = pathlib.Path("/etc/natinst/safemode")
    if safe_mode.exists():
        raise SNACError("This script cannot be run in safe mode.", Errors.EX_BAD_ENVIRONEMNT)


# Check that the script is running on NI LinuxRT
def _check_nilrt():
    if get_distro() != "nilrt":
        raise SNACError("This script must be run on a NILRT system.", Errors.EX_BAD_ENVIRONEMNT)


def verify_prereqs():  # noqa: D103 - Missing docstring in public function (auto-generated noqa)
    _check_euid_root()
    _check_iptables()
    _check_runmode()
    _check_nilrt()
