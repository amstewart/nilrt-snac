import argparse
import textwrap

from nilrt_snac._configs._base_config import _BaseConfig
from nilrt_snac._configs._config_file import _ConfigFile

from nilrt_snac import logger
from nilrt_snac.opkg import opkg_helper


class _TmuxConfig(_BaseConfig):
    def __init__(self):
        self._opkg_helper = opkg_helper

    def configure(self, args: argparse.Namespace) -> None:
        print("Configuring tmux...")
        snac_config_file = _ConfigFile("/usr/share/tmux/conf.d/snac.conf")
        profile_file = _ConfigFile("/etc/profile.d/tmux.sh")
        dry_run: bool = args.dry_run
        self._opkg_helper.install("tmux")

        if not snac_config_file.exists():
            snac_config_file.add(
                textwrap.dedent(
                    """
                    # NILRT SNAC configuration tmux-snac.conf. Do not hand-edit.
                    set -g lock-after-time 900
                    """
                )
            )

        if not profile_file.exists():
            profile_file.add(
                textwrap.dedent(
                    """
                    # NILRT SNAC configuration tmux.sh. Do not hand-edit.
                    if [ "$PS1" ]; then
                        parent=$(ps -o ppid= -p $$)
                        name=$(ps -o comm= -p $parent)
                        case "$name" in (sshd|login) exec tmux ;; esac
                    fi
                    """
                )
            )

        snac_config_file.save(dry_run)
        profile_file.save(dry_run)

    def verify(self, args: argparse.Namespace) -> bool:
        print("Verifying tmux configuration...")
        snac_config_file = _ConfigFile("/usr/share/tmux/conf.d/snac.conf")
        profile_file = _ConfigFile("/etc/profile.d/tmux.sh")
        valid = True
        if not self._opkg_helper.is_installed("tmux"):
            valid = False
            logger.error("MISSING: tmux not installed")
        if not snac_config_file.exists():
            valid = False
            logger.error(f"MISSING: {snac_config_file.path} not found")
        if not snac_config_file.contains("set -g lock-after-time"):
            valid = False
            logger.error("MISSING: commands to inactivity lock")
        if not profile_file.exists():
            valid = False
            logger.error(f"MISSING: {profile_file.path} not found")
        if not profile_file.contains("exec tmux"):
            valid = False
            logger.error("MISSING: command to replace shell with tmux")
        return valid
