import argparse

from nilrt_snac._configs._base_config import _BaseConfig

from nilrt_snac import logger
from nilrt_snac.opkg import opkg_helper


class _CryptSetupConfig(_BaseConfig):
    def __init__(self):
        self._opkg_helper = opkg_helper

    def configure(self, args: argparse.Namespace) -> None:
        print("Configuring cryptsetup...")

        self._opkg_helper.install("cryptsetup")

    def verify(self, args: argparse.Namespace) -> bool:
        print("Verifying cryptsetup configuration...")
        valid = True
        if not self._opkg_helper.is_installed("cryptsetup"):
            valid = False
            logger.error(f"MISSING: cryptsetup not installed")
        return valid
