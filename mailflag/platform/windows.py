"""Windows contract placeholder. This release is not a Windows build."""

from pathlib import Path

from .base import AppPaths, PlatformServices


class WindowsPlatform(PlatformServices):
    def __init__(self):
        raise NotImplementedError(
            "Windows platform services are specified in WINDOWS_PORT.md but "
            "are intentionally not implemented in MailFlag 0.12.3"
        )
