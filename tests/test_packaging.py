"""Static regression checks for the Debian package inputs."""

from pathlib import Path
import unittest

from mailflag.version import __version__, DEBIAN_VERSION


ROOT = Path(__file__).parents[1]


class PackagingTests(unittest.TestCase):
    def test_version_metadata_is_consistent(self):
        control = (ROOT / 'packaging/debian/control').read_text()
        self.assertEqual(__version__, '0.15.1-beta1')
        self.assertEqual(DEBIAN_VERSION, '0.15.1~beta1')
        self.assertIn(f'Version: {DEBIAN_VERSION}', control)
        self.assertIn(f'VERSION={DEBIAN_VERSION}',
                      (ROOT / 'build-deb.sh').read_text())

    def test_desktop_launcher_and_autostart_are_headless(self):
        launcher = (ROOT / 'packaging/mailflag.desktop').read_text()
        autostart = (ROOT / 'packaging/mailflag-autostart.desktop').read_text()
        for text in (launcher, autostart):
            self.assertIn('Terminal=false', text)
        self.assertIn(
            'Icon=/usr/share/icons/hicolor/128x128/apps/mailflag.png',
            launcher,
        )
        self.assertIn('Icon=mailflag', autostart)
        self.assertIn('Exec=/usr/bin/mailflag --settings', launcher)
        self.assertIn('StartupWMClass=mailflag', launcher)
        self.assertIn('Exec=/usr/bin/mailflag --startup', autostart)
        self.assertIn('X-GNOME-Autostart-enabled=true', autostart)

    def test_package_scripts_never_touch_mail_or_user_state(self):
        scripts = '\n'.join(
            (ROOT / f'packaging/debian/{name}').read_text()
            for name in ('postinst', 'prerm', 'postrm')
        ).lower()
        for forbidden in ('imap', 'config.ini', 'state.json', 'secret-tool',
                          'mailbox', 'trash', 'bulk'):
            self.assertNotIn(forbidden, scripts)

    def test_prerm_stops_only_python_module_mailflag_processes(self):
        script = (ROOT / 'packaging/debian/prerm').read_text()
        self.assertIn('/usr/bin/mailflag --shutdown', script)
        self.assertIn("['-m', 'mailflag']", script)
        self.assertIn('kill -TERM $pids', script)
        self.assertIn('kill -KILL $pids', script)
        self.assertNotIn('pkill', script)
        self.assertNotIn('killall', script)
        self.assertIn('# Never block removal', script)

    def test_prerm_is_packaged_as_executable_maintainer_script(self):
        build = (ROOT / 'build-deb.sh').read_text()
        self.assertIn('packaging/debian/prerm', build)
        self.assertIn('$BUILD/DEBIAN/prerm', build)

    def test_finished_debian_package_goes_to_shared_outputs_directory(self):
        build = (ROOT / 'build-deb.sh').read_text()
        self.assertIn('OUTPUT_DIR=$(CDPATH= cd -- "$SOURCE/.."', build)
        self.assertIn('"$OUTPUT_DIR/$PACKAGE"', build)

    def test_fresh_install_schedules_settings_in_desktop_user_session(self):
        preinst = (ROOT / 'packaging/debian/preinst').read_text()
        postinst = (ROOT / 'packaging/debian/postinst').read_text()
        launcher = (ROOT / 'packaging/mailflag-launch-first-run').read_text()
        build = (ROOT / 'build-deb.sh').read_text()
        self.assertIn('[ "${1:-}" = "install" ]', preinst)
        self.assertIn('/run/mailflag-first-install.pending', preinst)
        self.assertIn('[ "${1:-}" = "configure" ]', postinst)
        self.assertIn('[ -f "$marker" ]', postinst)
        self.assertIn('/usr/lib/mailflag/launch-first-run', postinst)
        self.assertIn('loginctl list-sessions', launcher)
        self.assertIn('[ "$active" = "yes" ]', launcher)
        self.assertIn('x11|wayland', launcher)
        self.assertIn('runuser -u "$user"', launcher)
        self.assertIn('DISPLAY="$display"', launcher)
        self.assertIn('WAYLAND_DISPLAY="$wayland"', launcher)
        self.assertIn('nohup /usr/bin/mailflag --settings', launcher)
        self.assertIn('/usr/bin/mailflag --settings', launcher)
        self.assertIn('mailflag-launch-first-run', build)

    def test_upgrade_does_not_launch_settings(self):
        preinst = (ROOT / 'packaging/debian/preinst').read_text()
        self.assertIn('[ "${1:-}" = "install" ]', preinst)
        self.assertNotIn('= "upgrade"', preinst)

    def test_preinst_is_packaged_as_executable_maintainer_script(self):
        build = (ROOT / 'build-deb.sh').read_text()
        self.assertIn('packaging/debian/preinst', build)
        self.assertIn('$BUILD/DEBIAN/preinst', build)

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
        self.assertIn('[str(installed), mode]', source)
        self.assertLess(
            source.index('Gtk.MenuItem(label="Settings…")'),
            source.index('Gtk.MenuItem(label="About MailFlag")'),
        )
        self.assertLess(
            source.index('Gtk.MenuItem(label="About MailFlag")'),
            source.index('Gtk.MenuItem(label="Quit MailFlag")'),
        )

    def test_about_tab_has_public_links_and_direct_opening(self):
        settings = (ROOT / 'mailflag/settings_gui.py').read_text()
        entrypoint = (ROOT / 'mailflag/__main__.py').read_text()
        expected = {
            'Website': 'https://slavabc.github.io/MailFlag/',
            'GitHub': 'https://github.com/SlavaBC/MailFlag',
            'Privacy Policy': 'https://github.com/SlavaBC/MailFlag/blob/master/PRIVACY.md',
            'GPLv3 License': 'https://github.com/SlavaBC/MailFlag/blob/master/LICENSE',
        }
        for label, url in expected.items():
            self.assertIn(f'("{label}", "{url}")', settings)
        self.assertIn('Gtk.LinkButton.new_with_label(url, label)', settings)
        self.assertNotIn('about:blank', settings)
        self.assertIn("run_settings('about' if '--about'", entrypoint)
        self.assertIn(
            "send_command(directory / 'settings-control.sock', 'show-about')",
            entrypoint,
        )

    def test_beta_acceptance_report_is_packaged(self):
        build = (ROOT / 'build-deb.sh').read_text()
        self.assertIn('BETA_CHECKLIST.md', build)
        self.assertIn('mailflag.1.gz', build)

    def test_manual_documents_public_commands(self):
        manual = (ROOT / 'packaging/mailflag.1').read_text()
        for option in ('--settings', '--about', '--background', '--startup', '--remove-account',
                       '--configure-folders', '--help'):
            self.assertIn(option, manual)

    def test_launcher_cannot_import_a_mailflag_file_from_current_directory(self):
        build = (ROOT / 'build-deb.sh').read_text()
        self.assertIn('cd /opt/mailflag', build)
        self.assertLess(build.index('cd /opt/mailflag'),
                        build.index('exec /usr/bin/python3 -m mailflag'))


if __name__ == '__main__':
    unittest.main()
