# MailFlag architecture

- `mailflag/core`: provider- and desktop-independent account parsing, message
  identities, OTP classification, JSON state codec, UID/delivery policy,
  reconnect/status models, and exact IMAP actions.
- `mailflag/providers`: provider profiles. Yahoo owns its host, Inbox, webmail
  URL and Spam folder here.
- `mailflag/platform`: OS service contracts and the current Linux backend.
- `mailflag/app.py`: Linux GTK presentation and composition root. It converts
  Core events into popup, pending-indicator and tray behavior.
- `mailflag/opening.py`, `sound.py`, `setup_account.py`: user preferences and
  setup using the selected platform backend rather than Linux commands.

Core modules import neither GTK nor Linux platform modules. `test_core.py` can
run without a desktop session and is the portable regression suite.
