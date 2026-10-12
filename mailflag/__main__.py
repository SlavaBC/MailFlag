"""Application entry point and single-instance guard."""
import sys
from .platform import get_platform
from .ipc import send_command
from .single_instance import acquire_instance_lock
from .version import __version__


HELP = """Usage: mailflag [OPTION]

  --settings                    open the graphical settings window
  --background                  run mail monitoring without opening Settings
  --startup                     first-run-aware desktop-session startup
  --shutdown                    stop running MailFlag processes
  --add-account                 add a Yahoo account in the terminal
  --remove-account [ACCOUNT]    remove one local account safely
  --configure-folders [ACCOUNT] choose monitored IMAP folders
  --demo                        show an offline popup demonstration
  --version                     show the installed version
  --help                        show this help
"""


def should_open_settings(arguments, accounts):
    """Return the UI route without importing GTK or starting a worker."""
    if '--startup' in arguments:
        return not accounts
    return '--settings' in arguments or '--background' not in arguments


def _handle_settings_control(command):
    """Schedule a clean GTK exit without touching background monitoring."""
    if command != 'stop':
        raise ValueError(f"Unknown settings control command: {command}")
    from gi.repository import GLib, Gtk
    GLib.idle_add(Gtk.main_quit)
    return "OK"


def main():
    if '--help' in sys.argv:
        print(HELP)
        return
    if '--version' in sys.argv:
        print(f'MailFlag {__version__}')
        return
    if '--shutdown' in sys.argv:
        from .shutdown import graceful_shutdown
        graceful_shutdown()
        return
    if '--configure-folders' in sys.argv:
        from .folders import configure_folders
        index = sys.argv.index('--configure-folders')
        account = sys.argv[index + 1] if len(sys.argv) > index + 1 else None
        configure_folders(account)
        return
    if '--add-account' in sys.argv:
        from . import setup_account
        return
    if '--remove-account' in sys.argv:
        from .remove_account import remove_account
        index = sys.argv.index('--remove-account')
        account = sys.argv[index + 1] if len(sys.argv) > index + 1 else None
        remove_account(account)
        return
    if '--demo' in sys.argv:
        from . import app
        app.install_ui_styles()
        # Offline UI preview: all mail/network actions are replaced.
        app.open_default_mail_app = lambda: True
        app.move_regular_to_trash = lambda *a: True
        app.move_regular_to_spam = lambda *a: True
        app.mark_exact_read = lambda *a: True
        app.add_pending_uid = lambda *a: None
        app.regular_popup.show('Long sender ' + 'a' * 180 + '@example.test',
                               'Long subject ' * 35, 'Preview text ' * 35,
                               1, 1, 'demo@example.test', '')
        app.regular_popup.window.connect("destroy", lambda *_: app.Gtk.main_quit())
        app.Gtk.main()
        return
    allowed_runtime = {'--settings', '--background', '--startup'}
    unknown = [arg for arg in sys.argv[1:] if arg not in allowed_runtime]
    if unknown:
        print(f"Unknown option: {unknown[0]}\n\n{HELP}", file=sys.stderr)
        raise SystemExit(2)
    startup = '--startup' in sys.argv
    accounts = None
    if startup:
        from .settings_service import SettingsService
        accounts = SettingsService().accounts()
    open_settings = should_open_settings(sys.argv[1:], accounts)
    if open_settings:
        from .settings_gui import run_settings
        from .ipc import ControlServer
        directory = get_platform().paths.config_dir
        directory.mkdir(parents=True, exist_ok=True)
        settings_lock = acquire_instance_lock(directory / 'settings.lock')
        if settings_lock is None:
            print('MailFlag Settings is already open.')
            return
        with settings_lock:
            control = ControlServer(
                directory / 'settings-control.sock',
                lambda command: _handle_settings_control(command),
            )
            control.start()
            try:
                run_settings()
            finally:
                control.close()
        return
    directory = get_platform().paths.config_dir
    directory.mkdir(parents=True, exist_ok=True)
    lock = acquire_instance_lock(directory / 'instance.lock')
    if lock is None:
        print('MailFlag background is already running.')
        return
    with lock:
        from .app import main as run
        run()


if __name__ == '__main__':
    main()
