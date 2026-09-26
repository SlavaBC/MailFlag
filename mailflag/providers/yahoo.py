from .base import ProviderProfile


YAHOO = ProviderProfile(
    provider_id="yahoo",
    display_name="Yahoo Mail",
    imap_host="imap.mail.yahoo.com",
    inbox="INBOX",
    webmail_url="https://mail.yahoo.com/",
    spam_folder="Bulk",
)

