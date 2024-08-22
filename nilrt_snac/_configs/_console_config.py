import argparse
import subprocess

from nilrt_snac._configs._base_config import _BaseConfig

from nilrt_snac import logger


class _ConsoleConfig(_BaseConfig):
    def __init__(self):
        pass  # Nothing to do for now

    def configure(self, args: argparse.Namespace) -> None:
        print("Configuring console access...")
        dry_run: bool = args.dry_run
        if not dry_run:
            logger.debug("Disabling console access")
            subprocess.run(
                ["nirtcfg", "--set", "section=systemsettings,token=consoleout.enabled,value=False"],
                check=True,
            )

    def verify(self, args: argparse.Namespace) -> bool:
        print("Verifying console access configuration...")
        valid = True
        result = subprocess.run(
            ["nirtcfg", "--get", "section=systemsettings,token=consoleout.enabled"],
            check=True,
            stdout=subprocess.PIPE,
        )
        if result.stdout.decode().strip() != "False":
            valid = False
            logger.error("FOUND: console access not diabled")
        return valid
