from typing import List

from nilrt_snac._configs._base_config import _BaseConfig
from nilrt_snac._configs._console_config import _ConsoleConfig
from nilrt_snac._configs._cryptsetup_config import _CryptsetupConfig
from nilrt_snac._configs._faillock_config import _FaillockConfig
from nilrt_snac._configs._niauth_config import _NiauthConfig
from nilrt_snac._configs._ntp_config import _NtpConfig
from nilrt_snac._configs._opkg_config import _OpkgConfig
from nilrt_snac._configs._pwquality_config import _PWQualityConfig
from nilrt_snac._configs._wifi_config import _WifiConfig
from nilrt_snac._configs._wireguard_config import _WireguardConfig
from nilrt_snac._configs._x11_config import _X11Config

# USBGuard is not supported for 1.0, but may be added in the future
# from ._UsbGuardConfig import _UsbGuardConfig

CONFIGS: List[_BaseConfig] = [
    _NtpConfig(),
    _OpkgConfig(),
    _WireguardConfig(),
    _CryptsetupConfig(),
    _NiauthConfig(),
    _WifiConfig(),
    _FaillockConfig(),
    _X11Config(),
    _ConsoleConfig(),
    _PWQualityConfig(),
]
