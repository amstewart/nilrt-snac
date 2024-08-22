import argparse
import textwrap

from nilrt_snac._configs._base_config import _BaseConfig
from nilrt_snac._configs._config_file import _ConfigFile

from nilrt_snac import logger


class _PWQualityConfig(_BaseConfig):
    def __init__(self):
        pass

    def configure(self, args: argparse.Namespace) -> None:
        print("Configuring Password quality...")
        config_file = _ConfigFile("/etc/pam.d/common-password")
        dry_run: bool = args.dry_run

        if not config_file.contains("remember=5"):
            config_file.update(r"(password.*pam_unix.so.*)", r"\1 remember=5")
        if not config_file.contains("password.*requisite.*pam_pwquality.so.*retry=3"):
            config_file.add(
                textwrap.dedent(
                    """
                    # Additional check for password complexity
                    password	requisite	pam_pwquality.so retry=3
                    """
                )
            )

        config_file.save(dry_run)

    def verify(self, args: argparse.Namespace) -> bool:
        print("Verifying Password quality...")
        config_file = _ConfigFile("/etc/pam.d/common-password")
        valid = True
        if not config_file.contains("remember=5"):
            valid = False
            logger.error("MISSING: 'remember=5' for pam_unix.so configuration")
        if not config_file.contains("password.*requisite.*pam_pwquality.so.*retry=3"):
            valid = False
            logger.error("MISSING: entry to add quality check")
        return valid
