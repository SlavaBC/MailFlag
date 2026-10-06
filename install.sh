#!/bin/sh
set -eu
SOURCE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
DEST="$HOME/.local/share/mailflag"
# Stage first; an unsuccessful dependency install leaves the current version intact.
mkdir -p "$DEST/releases" "$HOME/.local/bin" "$HOME/.local/share/applications" "$HOME/.config/autostart"
STAGE=$(mktemp -d "$DEST/releases/0.14.1-beta1.XXXXXX")
trap 'rm -rf "$STAGE"' EXIT HUP INT TERM
cp -R "$SOURCE/mailflag" "$STAGE/"
cp -R "$SOURCE/vendor" "$STAGE/"
python3 -m venv --system-site-packages "$STAGE/venv"
PYTHONPATH="$STAGE/vendor" "$STAGE/venv/bin/python" -c 'import gi; gi.require_version("Gtk", "3.0"); gi.require_version("AyatanaAppIndicator3", "0.1"); from gi.repository import AyatanaAppIndicator3, Gtk; import imap_tools; assert imap_tools.__version__ == "1.15.0"'
command -v secret-tool >/dev/null
cat > "$STAGE/run" <<'EOF'
#!/bin/sh
set -eu
APP=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$APP"
export PYTHONPATH="$APP/vendor${PYTHONPATH:+:$PYTHONPATH}"
exec "$APP/venv/bin/python" -m mailflag "$@"
EOF
chmod +x "$STAGE/run"
# Atomic release switch. Old releases remain available for rollback.
ln -s "$STAGE" "$DEST/current.new"
mv -Tf "$DEST/current.new" "$DEST/current"
trap - EXIT HUP INT TERM
cat > "$HOME/.local/bin/mailflag" <<'EOF'
#!/bin/sh
exec "$HOME/.local/share/mailflag/current/run" "$@"
EOF
chmod +x "$HOME/.local/bin/mailflag"
# Desktop Exec quoting is generated with the desktop-entry escaping rules.
python3 - <<'PY'
from pathlib import Path
home = Path.home()
def quoted(value):
    value = str(value).replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$').replace('%', '%%')
    return '"' + value.replace('\\', '\\\\') + '"'
text = '[Desktop Entry]\nType=Application\nName=MailFlag\nComment=Multi-account mail notifications\nExec=' + quoted(home / '.local/bin/mailflag') + '\nIcon=' + str(home / '.local/share/mailflag/current/mailflag/mailflag-app-icon.png') + '\nTerminal=false\nCategories=Network;Email;\n'
(home / '.local/share/applications/mailflag.desktop').write_text(text)
(home / '.config/autostart/mailflag.desktop').write_text(text)
PY
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$HOME/.local/share/applications"
fi
rm -f "$HOME/.config/mailflag/diagnostics.jsonl" "$HOME/.config/mailflag/diagnostics.jsonl.1"
printf '%s\n' 'MailFlag 0.14.1-beta1 installed. Stop the running older version, then launch MailFlag from the menu.'
