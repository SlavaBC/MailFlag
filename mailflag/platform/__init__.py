"""Selected operating-system services."""

import sys

from .base import PlatformServices

_platform = None


def get_platform() -> PlatformServices:
    global _platform
    if _platform is None:
        if sys.platform.startswith("linux"):
            from .linux import LinuxPlatform
            _platform = LinuxPlatform()
        elif sys.platform == "win32":
            from .windows import WindowsPlatform
            _platform = WindowsPlatform()
        else:
            raise RuntimeError(f"Unsupported MailFlag platform: {sys.platform}")
    return _platform


def set_platform_for_tests(platform):
    global _platform
    _platform = platform

