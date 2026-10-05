#!/bin/sh
set -eu
SOURCE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
VERSION=0.13.1~beta1
PACKAGE=mailflag_${VERSION}_amd64.deb
BUILD=$(mktemp -d "${TMPDIR:-/tmp}/mailflag-deb.XXXXXX")
cleanup() { rm -rf "$BUILD"; }
trap cleanup EXIT HUP INT TERM
mkdir -p "$BUILD/DEBIAN" "$BUILD/opt/mailflag" "$BUILD/usr/bin" \
  "$BUILD/usr/share/applications" "$BUILD/etc/xdg/autostart" \
  "$BUILD/usr/share/doc/mailflag"
cp "$SOURCE/packaging/debian/control" "$BUILD/DEBIAN/control"
cp "$SOURCE/packaging/debian/postinst" "$BUILD/DEBIAN/postinst"
cp "$SOURCE/packaging/debian/postrm" "$BUILD/DEBIAN/postrm"
cp -R "$SOURCE/mailflag" "$BUILD/opt/mailflag/"
cp -R "$SOURCE/vendor" "$BUILD/opt/mailflag/"
find "$BUILD/opt/mailflag" -type d -name __pycache__ -prune -exec rm -rf {} +
find "$BUILD/opt/mailflag" -type f -name '*.pyc' -delete
cat > "$BUILD/opt/mailflag/run" <<'EOF'
#!/bin/sh
set -eu
cd /opt/mailflag
export PYTHONPATH="/opt/mailflag/vendor${PYTHONPATH:+:$PYTHONPATH}"
exec /usr/bin/python3 -m mailflag "$@"
EOF
chmod 755 "$BUILD/opt/mailflag/run"
cat > "$BUILD/usr/bin/mailflag" <<'EOF'
#!/bin/sh
exec /opt/mailflag/run "$@"
EOF
chmod 755 "$BUILD/usr/bin/mailflag"
cp "$SOURCE/packaging/mailflag.desktop" "$BUILD/usr/share/applications/mailflag.desktop"
cp "$SOURCE/packaging/mailflag-autostart.desktop" "$BUILD/etc/xdg/autostart/mailflag.desktop"
cp "$SOURCE/packaging/mailflag-migrate-local" "$BUILD/usr/bin/mailflag-migrate-local"
for size in 48 64 128 256; do
  mkdir -p "$BUILD/usr/share/icons/hicolor/${size}x${size}/apps"
  cp "$SOURCE/packaging/icons/mailflag-${size}.png" \
    "$BUILD/usr/share/icons/hicolor/${size}x${size}/apps/mailflag.png"
done
cp "$SOURCE/README.md" "$SOURCE/ARCHITECTURE.md" "$SOURCE/BETA_CHECKLIST.md" \
  "$BUILD/usr/share/doc/mailflag/"
printf '%s\n' 'imap-tools 1.15.0 is bundled under /opt/mailflag/vendor.' \
  > "$BUILD/usr/share/doc/mailflag/DEPENDENCIES"
chmod -R u=rwX,go=rX "$BUILD"
chmod 755 "$BUILD/DEBIAN/postinst" "$BUILD/DEBIAN/postrm" \
  "$BUILD/opt/mailflag/run" "$BUILD/usr/bin/mailflag" \
  "$BUILD/usr/bin/mailflag-migrate-local"
dpkg-deb --build --root-owner-group "$BUILD" "$SOURCE/$PACKAGE"
printf '%s\n' "$SOURCE/$PACKAGE"
