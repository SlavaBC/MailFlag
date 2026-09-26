from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppPaths:
    config_dir: Path
    state_dir: Path
    cache_dir: Path
    assets_dir: Path

    @property
    def config_file(self): return self.config_dir / "config.ini"
    @property
    def state_file(self): return self.state_dir / "state.json"


class CredentialStore(ABC):
    @abstractmethod
    def get(self, account: str) -> str: ...
    @abstractmethod
    def set(self, account: str, secret: str) -> None: ...
    @abstractmethod
    def delete(self, account: str) -> None: ...


class AutostartService(ABC):
    @abstractmethod
    def enable(self) -> None: ...
    @abstractmethod
    def disable(self) -> None: ...
    @abstractmethod
    def is_enabled(self) -> bool: ...


class PlatformServices(ABC):
    paths: AppPaths
    credentials: CredentialStore
    autostart: AutostartService

    @abstractmethod
    def power_clock_snapshot(self): ...
    @abstractmethod
    def suspend_gap_since(self, snapshot) -> float: ...
    @abstractmethod
    def copy_text(self, text: str, primary=False) -> None: ...
    @abstractmethod
    def play_audio(self, path: Path) -> bool: ...
    @abstractmethod
    def open_url(self, url: str) -> bool: ...
    @abstractmethod
    def open_default_mail_client(self) -> bool: ...
    @abstractmethod
    def notify(self, title: str, body: str) -> bool: ...

