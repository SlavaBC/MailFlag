# Third-Party Notices

MailFlag uses operating-system libraries and utilities that remain under their
own licenses. They are installed independently by the Linux distribution and
are not copied into the MailFlag source tree or Debian package.

The MailFlag Debian package bundles one third-party Python library:

## imap-tools 1.15.0

- Project: https://github.com/ikvk/imap_tools
- Copyright: 2019 Kaukin Vladimir
- License: Apache License 2.0
- Bundled location: `/opt/mailflag/vendor/imap_tools`
- License text: `vendor/IMAP_TOOLS_LICENSE` in the source tree and
  `/usr/share/doc/mailflag/IMAP_TOOLS_LICENSE` in the Debian package

The bundled imap-tools files remain licensed under Apache License 2.0. They are
not relicensed as MailFlag code. Apache License 2.0 is compatible with GNU GPL
version 3.

## System dependencies

The current Debian package declares these external dependencies:

- Python 3 — Python Software Foundation License
- PyGObject — GNU Lesser General Public License v2.1 or later
- Pycairo — GNU Lesser General Public License v2.1 or Mozilla Public License 1.1
- GTK 3 — GNU Lesser General Public License v2.1 or later
- GdkPixbuf — GNU Lesser General Public License v2 or later and compatible
  licenses for individual files
- AyatanaAppIndicator3 — GNU Lesser General Public License v2.1 or v3 for the
  runtime library, with compatible licenses for individual files
- libsecret / Secret Service integration — GNU Lesser General Public License
  v2.1 or later
- xdg-utils — MIT/Expat license
- libnotify — GNU Lesser General Public License v2.1 or later
- PulseAudio utilities — GNU Lesser General Public License v2.1 or later, with
  compatible licenses for individual files

These components are provided by the operating system. Their copyright and
license files remain available through the corresponding distribution
packages under `/usr/share/doc`.
