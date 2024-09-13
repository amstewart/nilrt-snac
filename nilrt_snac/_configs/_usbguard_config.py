import argparse
import pathlib
import shutil
import subprocess
import tempfile

from nilrt_snac._configs._base_config import _BaseConfig

from nilrt_snac import logger
from nilrt_snac.opkg import opkg_helper

USBGUARD_SRC_URL = (
    "https://github.com/USBGuard/usbguard/releases/download/usbguard-1.1.2/usbguard-1.1.2.tar.gz"
)


class _USBGuardConfig(_BaseConfig):
    def __init__(self):
        self._src_path = pathlib.Path("/usr/local/src")
        self._opkg_helper = opkg_helper

    def configure(self, args: argparse.Namespace) -> None:
        print("Installing USBGuard...")
        dry_run: bool = args.dry_run

        logger.debug(f"Ensure {self._src_path} exists")
        self._src_path.mkdir(parents=True, exist_ok=True)

        logger.debug("Clean up any previous copy of USB Guard")
        installer_path = self._src_path / "usbguard"
        shutil.rmtree(installer_path)

        logger.debug(f"Download and extract {USBGUARD_SRC_URL}")
        # There is not proper typing support for NamedTemporaryFile
        with tempfile.NamedTemporaryFile(delete_on_close=False) as fp:  # type: ignore
            subprocess.run(["wget", USBGUARD_SRC_URL, "-O", fp.name], check=True)
            subprocess.run(["tar", "xz", "-f", fp.name, "-C", self._src_path], check=True)

        logger.debug("Install prereq")
        self._opkg_helper.install("libqb-dev")

        logger.debug("Configure and install USBGuard")
        cmd = [
            "./configure",
            "--with-crypto-library=openssl",
            "--with-bundled-catch",
            "--with-bundled-pegtl",
            "--without-dbus",
            "--without-polkit",
            "--prefix=/",
        ]
        if not dry_run:
            subprocess.run(cmd, check=True, cwd=installer_path)
            subprocess.run(["make", "install"], check=True, cwd=installer_path)
            # TODO: make initscript

    def verify(self, args: argparse.Namespace) -> bool:
        print("Verifying USBGuard configuration...")
        valid = True
        # TODO: figure out what needs to be verified
        return valid
