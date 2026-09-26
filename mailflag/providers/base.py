from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderProfile:
    provider_id: str
    display_name: str
    imap_host: str
    inbox: str
    webmail_url: str
    spam_folder: str | None = None

