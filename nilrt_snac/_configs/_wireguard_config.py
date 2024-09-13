import argparse
import pathlib
import subprocess
import textwrap

from nilrt_snac._configs._base_config import _BaseConfig
from nilrt_snac._configs._config_file import _ConfigFile

from nilrt_snac import logger
from nilrt_snac.opkg import OPKG_SNAC_CONF, opkg_helper

WIREGUARD_TOOLS_DEB = "http://ftp.us.debian.org/debian/pool/main/w/wireguard/wireguard-tools_1.0.20210914-1+b1_amd64.deb"


class _WireguardConfig(_BaseConfig):
    def __init__(self):
        self._sysconnf_path = pathlib.Path("/etc/wireguard")
        self._opkg_helper = opkg_helper

    def configure(self, args: argparse.Namespace) -> None:
        print("Installing wireguard-tools...")
        config_file = _ConfigFile(self._sysconnf_path / "wglv0.conf")
        private_key = _ConfigFile(self._sysconnf_path / "wglv0.privatekey")
        public_key = _ConfigFile(self._sysconnf_path / "wglv0.publickey")
        opkg_conf = _ConfigFile(OPKG_SNAC_CONF)
        ifplug_conf = _ConfigFile("/etc/ifplugd/ifplugd.conf")
        dry_run: bool = args.dry_run
        subprocess.run(["wget", WIREGUARD_TOOLS_DEB, "-O", "./wireguard-tools.deb"], check=True)
        if not opkg_conf.contains("arch amd64 15"):
            opkg_conf.add("arch amd64 15\n")
            # We need to save the file before installing the package so that amd64 is
            # a valid architecture
            opkg_conf.save(dry_run)
        self._opkg_helper.install("./wireguard-tools.deb", force_reinstall=True)

        if not ifplug_conf.contains("^ARGS_wglv0.*"):
            ifplug_conf.add(
                textwrap.dedent(
                    """

                    # This assignment block is managed by the nilrt-snac package.
                    ARGS_wglv0="$ARGS --no-auto"
                    # endblock
                    """
                )
            )

        if not config_file.contains("^PrivateKey = .+") and not private_key.exists():
            logger.debug("Generating wireguard keypair....")
            result = subprocess.run(["wg", "genkey"], stdout=subprocess.PIPE, check=True)
            priv_key = result.stdout.decode().strip()
            private_key.add(priv_key)
            private_key.chmod(0o600)
            result = subprocess.run(
                ["wg", "pubkey"], input=priv_key, text=True, stdout=subprocess.PIPE, check=True
            )
            pub_key = result.stdout.strip()
            public_key.add(pub_key)
            public_key.chmod(0o600)

        config_file.save(dry_run)
        private_key.save(dry_run)
        public_key.save(dry_run)
        opkg_conf.save(dry_run)
        ifplug_conf.save(dry_run)
        if not dry_run:
            logger.debug("Restating wireguard service")
            subprocess.run(
                [
                    "update-rc.d",
                    "ni-wireguard-labview",
                    "start",
                    "03",
                    "3",
                    "4",
                    "5",
                    ".",
                    "stop",
                    "05",
                    "0",
                    "6",
                    ".",
                ],
                check=True,
            )
            subprocess.run(["/etc/init.d/ni-wireguard-labview", "restart"], check=True)

    def verify(self, args: argparse.Namespace) -> bool:
        print("Verifying wireguard configuration...")
        config_file = _ConfigFile(self._sysconnf_path / "wglv0.conf")
        private_key = _ConfigFile(self._sysconnf_path / "wglv0.privatekey")
        public_key = _ConfigFile(self._sysconnf_path / "wglv0.publickey")
        opkg_conf = _ConfigFile(OPKG_SNAC_CONF)
        ifplug_conf = _ConfigFile("/etc/ifplugd/ifplugd.conf")
        valid = True
        if not self._opkg_helper.is_installed("wireguard-tools"):
            valid = False
            logger.error("MISSING: wireguard-tools not installed")
        if not config_file.exists():
            valid = False
            logger.error(f"MISSING: {config_file.path}")
        if not private_key.exists():
            valid = False
            logger.error(f"MISSING: {private_key.path}")
        if not public_key.exists():
            valid = False
            logger.error(f"MISSING: {public_key.path}")
        if not opkg_conf.contains("arch amd64 15"):
            valid = False
            logger.error(f"MISSING: 'arch amd64 15' in {opkg_conf.path}")
        if not ifplug_conf.contains("ARGS_wglv0=.*"):
            valid = False
            logger.error(f"MISSING: 'ARGS_wglv0=.*' in {ifplug_conf.path}")
        return valid
