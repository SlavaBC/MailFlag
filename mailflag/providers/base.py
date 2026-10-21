from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderProfile:
    provider_id: str
    display_name: str
    imap_host: str
    inbox: str
    webmail_url: str
    spam_folder: str | None = None
    imap_port: int = 993
    imap_ssl: bool = True

