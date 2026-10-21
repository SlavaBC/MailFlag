"""Generic user-configured IMAP provider profile."""

from .base import ProviderProfile


def custom_imap_profile(host, port=993, use_ssl=True, display_name="Custom IMAP"):
    return ProviderProfile(
        provider_id="custom_imap",
        display_name=display_name or "Custom IMAP",
        imap_host=str(host).strip(),
        imap_port=int(port),
        imap_ssl=bool(use_ssl),
        inbox="INBOX",
        webmail_url="",
        spam_folder=None,
    )


__all__ = ["custom_imap_profile"]
