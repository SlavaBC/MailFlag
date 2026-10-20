# MailFlag

[![GitHub release downloads](https://img.shields.io/github/downloads/SlavaBC/MailFlag/total?label=downloads&logo=github)](https://github.com/SlavaBC/MailFlag/releases)

MailFlag is a lightweight desktop email notifier for Linux. It connects directly to your mailbox over IMAP and watches for new mail in the background, so you do not need to keep webmail or a full email client open just to catch a verification code or an important message.

## Why MailFlag

MailFlag is especially useful when you are waiting for a verification code, one-time password (OTP), or sign-in code by email.

Instead of opening webmail, refreshing your inbox, finding the message, opening it, selecting the code, and copying it manually, MailFlag detects the code as soon as the message arrives and shows it in a dedicated popup. One click copies the code to the clipboard — then you simply paste it where you need it.

For ordinary email, MailFlag works as a lightweight desktop notification layer, showing the sender, subject, preview, and quick actions without requiring a full mail client to stay open.


## Current Features

- Near-real-time IMAP monitoring with IDLE where supported.
- Multiple email accounts in one MailFlag instance.
- Per-account monitored folders, including folders used by server-side mail filters.
- OTP / verification-code detection with one-click copy to the clipboard.
- Compact popup for ordinary mail with sender, subject, and a short preview.
- Quick actions: Open, Delete, Spam, Ignore, and Mark as Read.
- Persistent pending indicator for messages that were not handled while the popup was visible.
- Recovery after reconnect, temporary network loss, sleep/resume, and application restart without replaying a storm of old popups.
- Graphical settings for accounts and monitored folders.
- Credentials stored in the Linux system keyring rather than in plain-text configuration files.
- Local processing of message content. MailFlag does not send your email content, verification codes, or credentials to MailFlag-operated servers.
- No analytics, advertising, or telemetry.

## Current Limitations

- MailFlag is currently focused on Linux and is being tested primarily on Linux Mint 22.x.
- MailFlag currently supports Yahoo Mail only. Support for additional email providers is planned.

We would be very happy to hear from users about which providers they would like to see next. Feedback and real-world use cases will help us decide what to prioritize, and we are open to adding other IMAP providers as demand grows.

If you would like MailFlag to support Gmail, Outlook, iCloud, Proton Mail, or another provider, please let us know through the project's GitHub repository.

- MailFlag is not a full email client. It is a notifier and quick-action tool; reading and composing mail still happens in your normal mail application or webmail.
- If a server-side filter sends new mail directly to a folder other than Inbox, that folder must be added to MailFlag's monitored folders.
- The Open action may open your default mail client or webmail rather than deep-linking to the exact message, depending on the provider and desktop environment.
- OTP detection is heuristic. The classifier is tested against positive, negative, and real-world regression cases, but unusual message formats may still produce false positives or false negatives.
- Windows and macOS versions are not available yet.

## Status

MailFlag is under active development and is being prepared for public beta testing. The current focus is stability, privacy, clean installation and removal, and a simple user experience without requiring terminal commands for normal use.

## License

MailFlag is licensed under the GNU General Public License v3.0.
