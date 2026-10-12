"""Static regression checks for the Debian package inputs."""

from pathlib import Path
import unittest

from mailflag.version import __version__, DEBIAN_VERSION


ROOT = Path(__file__).parents[1]


class PackagingTests(unittest.TestCase):
    def test_version_metadata_is_consistent(self):
        control = (ROOT / 'packaging/debian/control').read_text()
        self.assertEqual(__version__, '0.14.3-beta1')
        self.assertEqual(DEBIAN_VERSION, '0.14.3~beta1')
        self.assertIn(f'Version: {DEBIAN_VERSION}', control)
        self.assertIn(f'VERSION={DEBIAN_VERSION}',
                      (ROOT / 'build-deb.sh').read_text())

    def test_desktop_launcher_and_autostart_are_headless(self):
        launcher = (ROOT / 'packaging/mailflag.desktop').read_text()
        autostart = (ROOT / 'packaging/mailflag-autostart.desktop').read_text()
        for text in (launcher, autostart):
            self.assertIn('Icon=mailflag', text)
            self.assertIn('Terminal=false', text)
        self.assertIn('Exec=/usr/bin/mailflag --settings', launcher)
        self.assertIn('StartupWMClass=mailflag', launcher)
        self.assertIn('Exec=/usr/bin/mailflag --startup', autostart)
        self.assertIn('X-GNOME-Autostart-enabled=true', autostart)

    def test_package_scripts_never_touch_mail_or_user_state(self):
        scripts = '\n'.join(
            (ROOT / f'packaging/debian/{name}').read_text()
            for name in ('postinst', 'postrm')
        ).lower()
        for forbidden in ('imap', 'config.ini', 'state.json', 'secret-tool',
                          'mailbox', 'trash', 'bulk'):
            self.assertNotIn(forbidden, scripts)

    def test_compatible_imap_tools_is_vendored(self):
        init = (ROOT / 'vendor/imap_tools/__init__.py').read_text()
        self.assertIn("__version__ = '1.15.0'", init)
        control = (ROOT / 'packaging/debian/control').read_text()
        self.assertNotIn('python3-imap-tools', control)

    def test_project_and_vendored_dependency_licenses_are_packaged(self):
        license_text = (ROOT / 'LICENSE').read_text()
        self.assertIn('GNU GENERAL PUBLIC LICENSE', license_text)
        self.assertIn('Version 3, 29 June 2007', license_text)

        imap_license = (ROOT / 'vendor/IMAP_TOOLS_LICENSE').read_text()
        self.assertIn('Apache License', imap_license)
        self.assertIn('Version 2.0, January 2004', imap_license)

        build = (ROOT / 'build-deb.sh').read_text()
        for document in ('LICENSE', 'THIRD_PARTY_NOTICES.md',
                         'IMAP_TOOLS_LICENSE'):
            self.assertIn(document, build)

    def test_selected_icon_sizes_are_packaged(self):
        for size in (48, 64, 128, 256):
            self.assertTrue((ROOT / f'packaging/icons/mailflag-{size}.png').is_file())

    def test_settings_dialogs_have_icon_and_scrollable_folder_list(self):
        source = (ROOT / 'mailflag/settings_gui.py').read_text()
        self.assertIn('Gtk.Window.set_default_icon_from_file', source)
        self.assertIn('self.set_wmclass("mailflag", "MailFlag")', source)
        self.assertIn('scroll.set_policy(Gtk.PolicyType.NEVER,', source)
        self.assertIn('box.pack_start(scroll, True, True, 0)', source)

    def test_tray_settings_item_uses_installed_command_before_quit(self):
        source = (ROOT / 'mailflag/app.py').read_text()
        self.assertIn('Gtk.MenuItem(label="Settings…")', source)
        self.assertIn('Path("/usr/bin/mailflag")', source)
        self.assertIn('[str(installed), "--settings"]', source)
        self.assertLess(
            source.index('Gtk.MenuItem(label="Settings…")'),
            source.index('Gtk.MenuItem(label="Quit MailFlag")'),
        )

    def test_beta_acceptance_report_is_packaged(self):
        build = (ROOT / 'build-deb.sh').read_text()
        self.assertIn('BETA_CHECKLIST.md', build)
        self.assertIn('mailflag.1.gz', build)

    def test_manual_documents_public_commands(self):
        manual = (ROOT / 'packaging/mailflag.1').read_text()
        for option in ('--settings', '--background', '--startup', '--remove-account',
                       '--configure-folders', '--help'):
            self.assertIn(option, manual)

    def test_launcher_cannot_import_a_mailflag_file_from_current_directory(self):
        build = (ROOT / 'build-deb.sh').read_text()
        self.assertIn('cd /opt/mailflag', build)
        self.assertLess(build.index('cd /opt/mailflag'),
                        build.index('exec /usr/bin/python3 -m mailflag'))


if __name__ == '__main__':
    unittest.main()
