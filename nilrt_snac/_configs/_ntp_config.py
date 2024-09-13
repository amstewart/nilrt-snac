import argparse
import subprocess

from nilrt_snac._configs._base_config import _BaseConfig
from nilrt_snac._configs._config_file import _ConfigFile

from nilrt_snac import logger
from nilrt_snac.opkg import opkg_helper


class _NTPConfig(_BaseConfig):
    def __init__(self):
        self._opkg_helper = opkg_helper

    def configure(self, args: argparse.Namespace) -> None:
        print("Configuring NTP...")
        config_file = _ConfigFile("/etc/ntp.conf")
        dry_run: bool = args.dry_run
        self._opkg_helper.install("ntp")

        logger.debug("Switching ntp servers to US mil.")
        if config_file.contains("natinst.pool.ntp.org"):
            config_file.update("^.*natinst.pool.ntp.org.*$", "")

        if not config_file.contains("server 0.us.pool.ntp.mil iburst maxpoll 16"):
            config_file.add("server 0.us.pool.ntp.mil iburst maxpoll 16")

        config_file.save(dry_run)
        if not dry_run:
            logger.debug("Restarting ntp service")
            subprocess.run(["/etc/init.d/ntpd", "restart"])

    def verify(self, args: argparse.Namespace) -> bool:
        print("Verifying NTP configuration...")
        config_file = _ConfigFile("/etc/ntp.conf")
        valid = True
        if not self._opkg_helper.is_installed("ntp"):
            valid = False
            logger.error("MISSING: ntp not installed")
        if not config_file.contains("0.us.pool.ntp.mil iburst maxpoll 16"):
            valid = False
            logger.error("MISSING: designated ntp server and settings not found in config file")
        if config_file.contains("natinst.pool.ntp.org"):
            valid = False
            logger.error("FOUND: NI ntp server in config file")
        return valid
