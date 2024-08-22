import argparse
import subprocess
import textwrap

from nilrt_snac._configs._base_config import _BaseConfig
from nilrt_snac._configs._config_file import _ConfigFile

from nilrt_snac import logger


class _WifiConfig(_BaseConfig):
    def __init__(self):
        pass

    def configure(self, args: argparse.Namespace) -> None:
        print("Configuring WiFi configuration...")
        config_file = _ConfigFile("/etc/modprobe.d/snac_blacklist.conf")
        dry_run: bool = args.dry_run
        if not config_file.contains("install cfg80211 /bin/true"):
            config_file.add(
                textwrap.dedent(
                    """
                    # Do not allow WiFi connections
                    # We cannot use the blacklist keyword because they will still be loaded
                    # when another module depends on them. This will prevent the modules from
                    # being loaded along with any modules that depends on them.
                    install cfg80211 /bin/true
                    install mac80211 /bin/true
                    """
                )
            )

        config_file.save(dry_run)
        if not dry_run:
            logger.debug("Removing any WiFi modules in memory")
            # We do not check for success. If the modules are not loaded, this will return an error
            subprocess.run(["rmmod", "cfg80211", "mac80211"], check=False)

    def verify(self, args: argparse.Namespace) -> bool:
        print("Verifying WiFi configuration...")
        config_file = _ConfigFile("/etc/modprobe.d/snac_blacklist.conf")
        valid = True
        if not config_file.exists():
            valid = False
            logger.error(f"MISSING: {config_file.path} not found")
        if not config_file.contains("install cfg80211 /bin/true"):
            valid = False
            logger.error("MISSING: commands to fail install of WiFi modules")
        return valid
