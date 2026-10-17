"""Compact GTK settings UI; it never owns the mail-monitor lifetime."""

import subprocess
import sys
import threading
import time
from pathlib import Path

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk

from .ipc import send_command
from .platform import get_platform
from .settings_service import POPUP_DURATIONS, SettingsService
from .sound import play_notification
from .version import __version__


PLATFORM = get_platform()
SETTINGS_WINDOW = None

ABOUT_LINKS = (
    ("Website", "https://slavabc.github.io/MailFlag/"),
    ("GitHub", "https://github.com/SlavaBC/MailFlag"),
    ("Privacy Policy", "https://github.com/SlavaBC/MailFlag/blob/master/PRIVACY.md"),
    ("GPLv3 License", "https://github.com/SlavaBC/MailFlag/blob/master/LICENSE"),
)


def install_window_icon():
    """Give the settings window and every transient dialog the app icon."""
    GLib.set_prgname("mailflag")
    GLib.set_application_name("MailFlag")
    Gtk.Window.set_default_icon_name("mailflag")
    icon = PLATFORM.paths.assets_dir / "mailflag-app-icon.png"
    if icon.exists():
        Gtk.Window.set_default_icon_from_file(str(icon))


def _background_command():
    installed = Path("/usr/bin/mailflag")
    return [str(installed), "--background"] if installed.exists() else [
        sys.executable, "-m", "mailflag", "--background"
    ]


def start_background():
    subprocess.Popen(_background_command(), stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)


def restart_background():
    socket_path = PLATFORM.paths.config_dir / "control.sock"
    send_command(socket_path, "stop")
    def delayed():
        for _ in range(30):
            if not socket_path.exists():
                break
            time.sleep(0.1)
        start_background()
    threading.Thread(target=delayed, daemon=True).start()


class AddAccountDialog(Gtk.Dialog):
    def __init__(self, parent, service, account=None):
        super().__init__(title="Add Yahoo account", transient_for=parent,
                         modal=True, destroy_with_parent=True)
        self.service = service
        self.set_default_size(470, 260)
        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        self.add_button("Add account", Gtk.ResponseType.OK)
        box = self.get_content_area()
        box.set_spacing(12)
        box.set_margin_start(20); box.set_margin_end(20)
        box.set_margin_top(18); box.set_margin_bottom(18)
        provider = Gtk.ComboBoxText()
        provider.append("yahoo", "Yahoo")
        provider.append("custom", "Custom IMAP — coming in a later adapter")
        provider.set_active_id("yahoo")
        provider.connect("changed", lambda combo: self._provider_changed(combo))
        box.pack_start(Gtk.Label(label="Provider", xalign=0), False, False, 0)
        box.pack_start(provider, False, False, 0)
        self.email = Gtk.Entry()
        self.email.set_placeholder_text("name@yahoo.com")
        self.email.set_text(account or "")
        self.email.set_sensitive(account is None)
        box.pack_start(Gtk.Label(label="Email", xalign=0), False, False, 0)
        box.pack_start(self.email, False, False, 0)
        self.password = Gtk.Entry()
        self.password.set_visibility(False)
        self.password.set_input_purpose(Gtk.InputPurpose.PASSWORD)
        self.password.set_placeholder_text("Yahoo App Password")
        box.pack_start(Gtk.Label(label="App Password", xalign=0), False, False, 0)
        box.pack_start(self.password, False, False, 0)
        row = Gtk.Box(spacing=10)
        test = Gtk.Button(label="Test connection")
        test.connect("clicked", self._test)
        self.status = Gtk.Label(xalign=0)
        row.pack_start(test, False, False, 0)
        row.pack_start(self.status, True, True, 0)
        box.pack_start(row, False, False, 0)
        self.show_all()

    def _provider_changed(self, combo):
        if combo.get_active_id() == "custom":
            self.status.set_text("Custom IMAP is reserved for the next provider adapter.")
            self.get_widget_for_response(Gtk.ResponseType.OK).set_sensitive(False)
        else:
            self.status.set_text("")
            self.get_widget_for_response(Gtk.ResponseType.OK).set_sensitive(True)

    def _test(self, _button):
        self.status.set_text("Testing…")
        while Gtk.events_pending(): Gtk.main_iteration_do(False)
        try:
            self.service.test_connection(self.email.get_text().strip(),
                                         self.password.get_text())
            self.status.set_markup("<span foreground='#208a45'>Connected</span>")
        except Exception as exc:
            self.status.set_markup("<span foreground='#bb2929'>Connection failed</span>")


class FolderSelectionDialog(Gtk.Dialog):
    def __init__(self, parent, folders, selected=("INBOX",)):
        super().__init__(title="Choose monitored folders", transient_for=parent,
                         modal=True, destroy_with_parent=True)
        screen_height = parent.get_screen().get_height() if parent else 700
        self.set_default_size(460, min(560, max(380, screen_height - 120)))
        self.set_resizable(True)
        self.add_button("Back", Gtk.ResponseType.CANCEL)
        self.add_button("Continue", Gtk.ResponseType.OK)
        box = self.get_content_area(); box.set_spacing(8)
        box.set_margin_start(20); box.set_margin_end(20)
        box.set_margin_top(16); box.set_margin_bottom(16)
        label = Gtk.Label(label="Folders to monitor", xalign=0)
        label.set_markup("<b>Folders to monitor</b>")
        box.pack_start(label, False, False, 0)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_min_content_height(280)
        folder_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.checks = []
        for folder in folders:
            check = Gtk.CheckButton(label=folder)
            check.set_active(folder in selected or folder == "INBOX")
            check.set_sensitive(folder != "INBOX")
            self.checks.append(check)
            folder_box.pack_start(check, False, False, 0)
        scroll.add(folder_box)
        box.pack_start(scroll, True, True, 0)
        self.show_all()

    def selected(self):
        return [check.get_label() for check in self.checks if check.get_active()]


class SettingsWindow(Gtk.Window):
    def __init__(self, service=None, initial_page=None):
        super().__init__(title="MailFlag Settings")
        self.set_wmclass("mailflag", "MailFlag")
        self.service = service or SettingsService()
        self.set_default_size(680, 500)
        self.set_border_width(16)
        icon = PLATFORM.paths.assets_dir / "mailflag-app-icon.png"
        if icon.exists(): self.set_icon_from_file(str(icon))
        self.connect("delete-event", self._hide_on_close)
        self.notebook = Gtk.Notebook()
        self.add(self.notebook)
        self.accounts_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.accounts_list = Gtk.ListBox()
        self.accounts_page.pack_start(self.accounts_list, True, True, 0)
        add = Gtk.Button(label="+ Add account")
        add.connect("clicked", self._add_account)
        self.accounts_page.pack_start(add, False, False, 0)
        self.notebook.append_page(self.accounts_page, Gtk.Label(label="Accounts"))
        self._build_folders_page()
        self._build_notifications_page()
        self._build_startup_page()
        self._build_about_page()
        self.refresh_accounts()
        self.show_all()
        if initial_page:
            self.show_page(initial_page)
        if not self.service.accounts() and initial_page != 'about':
            GLib.idle_add(self._first_run)

    def show_page(self, page):
        indexes = {'about': getattr(self, 'about_page_index', None)}
        index = indexes.get(page)
        if index is None:
            return False
        self.notebook.set_current_page(index)
        self.present()
        return True

    def _hide_on_close(self, *_args):
        Gtk.main_quit()
        return False

    def _first_run(self):
        dialog = Gtk.MessageDialog(
            transient_for=self, modal=True, message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK, text="Welcome to MailFlag",
        )
        dialog.format_secondary_text(
            "MailFlag monitors email in the background and processes mail locally. "
            "Add your Yahoo account to get started."
        )
        dialog.run(); dialog.destroy()
        self._add_account(None)
        return False

    def _clear_list(self, widget):
        for child in widget.get_children(): widget.remove(child)

    def refresh_accounts(self):
        self._clear_list(self.accounts_list)
        accounts = self.service.accounts()
        for account in accounts:
            row = Gtk.Box(spacing=10)
            text = Gtk.Label(xalign=0)
            text.set_markup(
                f"<b>Yahoo — {GLib.markup_escape_text(account)}</b>\n"
                f"Monitored folders: {GLib.markup_escape_text(', '.join(self.service.folders(account)))}"
            )
            row.pack_start(text, True, True, 0)
            edit = Gtk.Button(label="Edit")
            edit.connect("clicked", self._edit_account, account)
            row.pack_start(edit, False, False, 0)
            remove = Gtk.Button(label="Remove")
            remove.connect("clicked", self._remove_account, account)
            row.pack_start(remove, False, False, 0)
            self.accounts_list.add(row)
        self.folder_account.remove_all()
        for account in accounts: self.folder_account.append_text(account)
        if accounts: self.folder_account.set_active(0)
        self.show_all()

    def _add_account(self, _button):
        dialog = AddAccountDialog(self, self.service)
        if dialog.run() == Gtk.ResponseType.OK:
            try:
                account = dialog.email.get_text().strip()
                password = dialog.password.get_text()
                folders = self.service.discover_folders(account, password)
                chooser = FolderSelectionDialog(self, folders)
                response = chooser.run()
                selected = chooser.selected()
                chooser.destroy()
                if response != Gtk.ResponseType.OK:
                    dialog.destroy()
                    return
                self.service.add_yahoo_account(account, password, folders=selected)
                self.refresh_accounts()
                restart_background()
                done = Gtk.MessageDialog(
                    transient_for=self, modal=True, message_type=Gtk.MessageType.INFO,
                    buttons=Gtk.ButtonsType.OK, text="MailFlag is ready",
                )
                done.format_secondary_text(
                    f"{account} is connected. Monitoring: {', '.join(selected)}"
                )
                done.run(); done.destroy()
            except Exception as exc:
                self._error("Account was not added", str(exc))
        dialog.destroy()

    def _edit_account(self, _button, account):
        dialog = AddAccountDialog(self, self.service, account=account)
        dialog.set_title("Update Yahoo credential")
        dialog.get_widget_for_response(Gtk.ResponseType.OK).set_label("Save")
        if dialog.run() == Gtk.ResponseType.OK:
            try:
                self.service.update_yahoo_credential(account, dialog.password.get_text())
                restart_background()
            except Exception as exc:
                self._error("Account was not updated", str(exc))
        dialog.destroy()

    def _remove_account(self, _button, account):
        dialog = Gtk.MessageDialog(
            transient_for=self, modal=True, message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.NONE,
            text=f"Remove account {account} from MailFlag?",
        )
        dialog.format_secondary_text(
            "Local settings, pending/checkpoint data and the saved App Password "
            "for this account will be removed. Messages, folders and filters on "
            "the mail server will not be changed."
        )
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Remove", Gtk.ResponseType.OK)
        if dialog.run() == Gtk.ResponseType.OK:
            try:
                socket_path = PLATFORM.paths.config_dir / "control.sock"
                if socket_path.exists():
                    response = send_command(
                        socket_path, f"remove-account {account}",
                        timeout=25.0, expect_response=True,
                    )
                    if response != "OK":
                        raise RuntimeError(
                            response or "MailFlag background did not respond"
                        )
                else:
                    self.service.remove_account(account)
                self.refresh_accounts()
            except Exception as exc:
                self._error("Account was not removed", str(exc))
        dialog.destroy()

    def _build_folders_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.folder_account = Gtk.ComboBoxText()
        self.folder_account.connect("changed", lambda *_: self._load_folder_checks())
        page.pack_start(self.folder_account, False, False, 0)
        help_text = Gtk.Label(xalign=0)
        help_text.set_line_wrap(True)
        help_text.set_text("Add a destination folder when a server-side filter delivers mail there. Local Thunderbird sorting usually needs only INBOX.")
        page.pack_start(help_text, False, False, 0)
        self.folder_checks = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        scroll = Gtk.ScrolledWindow(); scroll.add(self.folder_checks)
        page.pack_start(scroll, True, True, 0)
        refresh = Gtk.Button(label="Refresh folders")
        refresh.connect("clicked", lambda *_: self._refresh_folders())
        save = Gtk.Button(label="Save monitored folders")
        save.connect("clicked", lambda *_: self._save_folders())
        buttons = Gtk.Box(spacing=10); buttons.pack_start(refresh, False, False, 0); buttons.pack_start(save, False, False, 0)
        page.pack_start(buttons, False, False, 0)
        self.notebook.append_page(page, Gtk.Label(label="Folders"))

    def _load_folder_checks(self, available=None):
        self._clear_list(self.folder_checks)
        account = self.folder_account.get_active_text()
        if not account: return
        current = self.service.folders(account)
        available = available or current
        for folder in available:
            check = Gtk.CheckButton(label=folder)
            check.set_active(folder in current or folder == "INBOX")
            check.set_sensitive(folder != "INBOX")
            self.folder_checks.pack_start(check, False, False, 0)
        self.folder_checks.show_all()

    def _refresh_folders(self):
        account = self.folder_account.get_active_text()
        if not account: return
        try: self._load_folder_checks(self.service.discover_folders(account))
        except Exception as exc: self._error("Folders could not be refreshed", str(exc))

    def _choose_folders(self, account, available):
        self.folder_account.set_active(self.service.accounts().index(account))
        self._load_folder_checks(available)
        self.notebook.set_current_page(1)

    def _save_folders(self):
        account = self.folder_account.get_active_text()
        if not account: return
        selected = [child.get_label() for child in self.folder_checks.get_children()
                    if isinstance(child, Gtk.CheckButton) and child.get_active()]
        self.service.update_folders(account, selected)
        self.refresh_accounts(); restart_background()

    def _build_notifications_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        prefs = self.service.notification_preferences()
        self.show_popup = Gtk.CheckButton(label="Show popup for new mail")
        self.show_popup.set_active(prefs["show_popup"])
        self.play_sound = Gtk.CheckButton(label="Play sound for new mail")
        self.play_sound.set_active(prefs["play_sound"])
        self.duration = Gtk.ComboBoxText()
        for value in POPUP_DURATIONS: self.duration.append_text(str(value))
        self.duration.set_active(POPUP_DURATIONS.index(prefs["popup_duration"]))
        page.pack_start(self.show_popup, False, False, 0)
        page.pack_start(self.play_sound, False, False, 0)
        row = Gtk.Box(spacing=10); row.pack_start(Gtk.Label(label="Popup duration:"), False, False, 0); row.pack_start(self.duration, False, False, 0); row.pack_start(Gtk.Label(label="seconds"), False, False, 0)
        page.pack_start(row, False, False, 0)
        page.pack_start(Gtk.Label(label="OTP codes are shown for a maximum of 30 seconds.", xalign=0), False, False, 0)
        buttons = Gtk.Box(spacing=10)
        save = Gtk.Button(label="Save"); save.connect("clicked", self._save_notifications)
        test = Gtk.Button(label="Test notification"); test.connect("clicked", self._test_notification)
        buttons.pack_start(save, False, False, 0); buttons.pack_start(test, False, False, 0)
        page.pack_start(buttons, False, False, 0)
        self.notebook.append_page(page, Gtk.Label(label="Notifications"))

    def _save_notifications(self, _button):
        self.service.save_notification_preferences(
            self.show_popup.get_active(), self.play_sound.get_active(),
            int(self.duration.get_active_text()),
        )

    def _test_notification(self, _button):
        PLATFORM.notify("MailFlag test", "Notifications are working.")
        if self.play_sound.get_active(): play_notification(force=True)

    def _build_startup_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.autostart = Gtk.CheckButton(label="Start MailFlag when I sign in")
        self.autostart.set_active(PLATFORM.autostart.is_enabled())
        self.autostart.connect("toggled", self._toggle_autostart)
        page.pack_start(self.autostart, False, False, 0)
        stop = Gtk.Button(label="Stop MailFlag")
        stop.connect("clicked", self._stop_background)
        page.pack_start(stop, False, False, 0)
        self.notebook.append_page(page, Gtk.Label(label="Startup"))

    def _toggle_autostart(self, button):
        try:
            (PLATFORM.autostart.enable if button.get_active() else PLATFORM.autostart.disable)()
        except Exception as exc: self._error("Autostart could not be changed", str(exc))

    def _stop_background(self, _button):
        dialog = Gtk.MessageDialog(transient_for=self, modal=True,
            message_type=Gtk.MessageType.WARNING, buttons=Gtk.ButtonsType.NONE,
            text="Stop MailFlag?")
        dialog.format_secondary_text("Mail monitoring will stop until MailFlag is started again.")
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL); dialog.add_button("Stop MailFlag", Gtk.ResponseType.OK)
        if dialog.run() == Gtk.ResponseType.OK:
            send_command(PLATFORM.paths.config_dir / "control.sock", "stop")
        dialog.destroy()

    def _build_about_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        title = Gtk.Label(); title.set_markup(f"<span size='xx-large' weight='bold'>MailFlag</span>\nVersion {__version__}")
        page.pack_start(title, False, False, 20)
        page.pack_start(Gtk.Label(label="Lightweight mail notifier with instant verification-code handling."), False, False, 0)
        links = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        links.set_halign(Gtk.Align.CENTER)
        for label, url in ABOUT_LINKS:
            link = Gtk.LinkButton.new_with_label(url, label)
            links.pack_start(link, False, False, 0)
        page.pack_start(links, False, False, 8)
        self.about_page_index = self.notebook.append_page(
            page, Gtk.Label(label="About")
        )

    def _error(self, title, detail):
        dialog = Gtk.MessageDialog(transient_for=self, modal=True,
            message_type=Gtk.MessageType.ERROR, buttons=Gtk.ButtonsType.OK,
            text=title)
        dialog.format_secondary_text(detail); dialog.run(); dialog.destroy()


def show_settings_page(page):
    return bool(SETTINGS_WINDOW and SETTINGS_WINDOW.show_page(page))


def run_settings(initial_page=None):
    global SETTINGS_WINDOW
    install_window_icon()
    window = SettingsWindow(initial_page=initial_page)
    SETTINGS_WINDOW = window
    if window.service.accounts() and not (
        PLATFORM.paths.config_dir / "control.sock"
    ).exists():
        start_background()
    window.connect("destroy", Gtk.main_quit)
    try:
        Gtk.main()
    finally:
        SETTINGS_WINDOW = None


__all__ = ["SettingsWindow", "run_settings", "show_settings_page", "restart_background",
           "start_background", "install_window_icon"]
