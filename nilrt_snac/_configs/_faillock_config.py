import argparse

from nilrt_snac._configs._base_config import _BaseConfig

from nilrt_snac import logger
from nilrt_snac.OpkgHelper import opkg_helper


class _FaillockConfig(_BaseConfig):
    def __init__(self):
        self._opkg_helper = opkg_helper

    def configure(self, args: argparse.Namespace) -> None:
        print("Configuring PAM faillock...")
        self._opkg_helper.install("pam-plugin-faillock")

    def verify(self, args: argparse.Namespace) -> bool:
        print("Verifying PAM faillock...")
        valid = True
        if not self._opkg_helper.is_installed("pam-plugin-faillock"):
            valid = False
            logger.error("MISSING: pam-plugin-faillock not installed")
        return valid
