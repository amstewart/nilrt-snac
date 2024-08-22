"""Helper class to read/write and update configuration files."""

import pathlib
import re
from typing import Union

from nilrt_snac import logger


class _ConfigFile:
    """Helper class to read/write and update configuration files."""

    def __init__(self, path: Union[pathlib.Path, str]) -> None:
        """Initialize the ConfigFile object.

        Args: path: The path to the configuration file.
        """
        if type(path) is str:
            path = pathlib.Path(path)

        self.path = path
        self._config = path.read_text() if path.exists() else ""
        self._mode = path.stat().st_mode if path.exists() else 0o700

    def save(self, dry_run: bool) -> None:
        """Save the configuration file."""
        if dry_run:
            print("dry-run: Not saved")
        else:
            self.path.write_text(self._config)
            self.path.chmod(self._mode)
        logger.debug(f"Contents of {self.path}:")
        logger.debug(self._config)

    def update(self, key: str, value: str) -> None:
        """Update the configuration file with the given key and value.

        Args:
            key: Search RE pattern to find the key.
            value: The value to replace the key with.

        Uses the re.sub() method to replace the key with the value.
        """
        self._config = re.sub(key, value, self._config, flags=re.MULTILINE)

    def add(self, value: str) -> None:
        """Add the value string to the config file.

        Args:
            value: String to add
        """
        self._config += value

    def exists(self) -> bool:
        return self.path.exists()

    def chmod(self, mode: int) -> None:
        self._mode = mode

    def contains(self, key: str) -> bool:
        """Check if the configuration file contains the given key.

        Args: key: RE pattern to search for in the configuration file.

        Returns: True if the key is found, False otherwise.
        """
        return bool(re.search(key, self._config))
