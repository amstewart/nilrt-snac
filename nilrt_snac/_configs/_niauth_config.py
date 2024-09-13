import argparse
import subprocess

from nilrt_snac._configs._base_config import _BaseConfig
from nilrt_snac._configs._config_file import _ConfigFile

from nilrt_snac import logger, SNAC_DATA_DIR
from nilrt_snac.opkg import opkg_helper


class _NIAuthConfig(_BaseConfig):
    def __init__(self):
        self._opkg_helper = opkg_helper

    def configure(self, args: argparse.Namespace) -> None:
        print("Removing NIAuth...")
        dry_run: bool = args.dry_run
        self._opkg_helper.remove("ni-auth", force_essential=True, force_depends=True)
        if not self._opkg_helper.is_installed("nilrt-snac-conflicts"):
            self._opkg_helper.install(str(SNAC_DATA_DIR / "nilrt-snac-conflicts.ipk"))

        if not dry_run:
            logger.debug("Removing root password")
            subprocess.run(["passwd", "-d", "root"], check=True)

    def verify(self, args: argparse.Namespace) -> bool:
        print("Verifying NIAuth...")
        valid = True
        if self._opkg_helper.is_installed("ni-auth"):
            valid = False
            logger.error("FOUND: ni-auth installed")
        if not self._opkg_helper.is_installed("nilrt-snac-conflicts"):
            valid = False
            logger.error("MISSING: nilrt-snac-conflicts not installed")
        return valid
