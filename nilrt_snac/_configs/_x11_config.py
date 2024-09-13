import argparse

from nilrt_snac._configs._base_config import _BaseConfig

from nilrt_snac import logger
from nilrt_snac.opkg import opkg_helper


class _X11Config(_BaseConfig):
    def __init__(self):
        self._opkg_helper = opkg_helper

    def configure(self, args: argparse.Namespace) -> None:
        print("Removing X11 stack...")
        self._opkg_helper.remove("packagegroup-core-x11")
        self._opkg_helper.remove("packagegroup-ni-xfce")
        self._opkg_helper.remove("*xfce4*-locale-ja*", ignore_installed=True)  # where do these come from !?!

    def verify(self, args: argparse.Namespace) -> bool:
        print("Verifying X11 stack removal...")
        valid = True
        if self._opkg_helper.is_installed("packagegroup-core-x11"):
            valid = False
            logger.error("FOUND: packagegroup-core-x11 installed")
        if self._opkg_helper.is_installed("packagegroup-ni-xfce"):
            valid = False
            logger.error("FOUND: packagegroup-ni-xfce installed")
        return valid
