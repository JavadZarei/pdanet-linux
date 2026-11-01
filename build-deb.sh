#!/usr/bin/env bash
# Build pdanet-linux_<version>_amd64.deb from this source tree.
# Needs only: bash, dpkg-deb, python3. Output: dist/
set -Eeuo pipefail

cd "$(dirname "$(readlink -f "$0")")"
VERSION="$(python3 -c 'import re,sys; print(re.search(r"__version__ = \"([^\"]+)\"", open("gui/pdanet_gui/__init__.py").read()).group(1))')"
PKG="pdanet-linux"
ARCH="amd64"
STAGE="build/${PKG}_${VERSION}_${ARCH}"
OUT="dist/${PKG}_${VERSION}_${ARCH}.deb"
MAINTAINER="${MAINTAINER:-PdaNet Linux <root@localhost>}"   # e.g. MAINTAINER="Your Name <you@example.com>" ./build-deb.sh
EPOCH="${SOURCE_DATE_EPOCH:-1767225600}"   # fixed mtime for reproducible output

command -v dpkg-deb >/dev/null || { echo "dpkg-deb is required" >&2; exit 1; }

echo "==> Running unit tests"
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests/unit
bash tests/usb-selection.sh
python3 libexec/pdanet-usb-helper --self-test

rm -rf build "dist"
mkdir -p "$STAGE/DEBIAN" dist

inst() { install -D -m "$1" "$2" "$STAGE/$3"; }

# --- CLI + helpers (unmodified from the working project)
inst 0755 bin/pdanet                      usr/lib/pdanet-linux/bin/pdanet
inst 0755 libexec/pdanet-usb-helper       usr/lib/pdanet-linux/libexec/pdanet-usb-helper
inst 0755 libexec/pdanet-gui-helper       usr/lib/pdanet-linux/libexec/pdanet-gui-helper
mkdir -p "$STAGE/usr/bin"
ln -s ../lib/pdanet-linux/bin/pdanet "$STAGE/usr/bin/pdanet"
inst 0755 packaging/pdanet-gui            usr/bin/pdanet-gui

# --- Python application
while IFS= read -r -d '' f; do
  inst 0644 "$f" "usr/lib/python3/dist-packages/${f#gui/}"
done < <(find gui/pdanet_gui -name '*.py' -not -path '*/__pycache__/*' -print0)

# --- systemd units (the CLI refers to them by name only)
for f in system/etc/systemd/system/*.service; do
  inst 0644 "$f" "usr/lib/systemd/system/$(basename "$f")"
done

# --- default configs, copied to /etc by postinst only when absent
for f in system/etc/*.toml system/etc/*.nft system/etc/*.conf; do
  inst 0644 "$f" "usr/share/pdanet-linux/etc/$(basename "$f")"
done

# --- desktop integration
inst 0644 packaging/org.pdanet.Desktop.desktop usr/share/applications/org.pdanet.Desktop.desktop
inst 0644 packaging/org.pdanet.Desktop.svg     usr/share/icons/hicolor/scalable/apps/org.pdanet.Desktop.svg
inst 0644 packaging/org.pdanet.Desktop.policy  usr/share/polkit-1/actions/org.pdanet.Desktop.policy

# --- docs
inst 0644 README.md usr/share/doc/$PKG/README.md
cat > "$STAGE/usr/share/doc/$PKG/copyright" <<'COPY'
No license was specified for the original PdaNetClientCLI-Linux project this
package is built from. Redistribution terms are therefore undefined; contact the
project owner before distributing this package outside your own machines.
COPY
chmod 0644 "$STAGE/usr/share/doc/$PKG/copyright"
cat > "$STAGE/usr/share/doc/$PKG/changelog" <<CHL
$PKG ($VERSION) unstable; urgency=medium

  * Native GTK4/libadwaita desktop application for the existing PdaNet USB CLI.

 -- $MAINTAINER  $(date -u -d "@$EPOCH" -R)
CHL
gzip -9n "$STAGE/usr/share/doc/$PKG/changelog"

# --- maintainer scripts and metadata
install -m 0755 packaging/debian/postinst "$STAGE/DEBIAN/postinst"
install -m 0755 packaging/debian/postrm   "$STAGE/DEBIAN/postrm"
SIZE="$(du -sk --exclude=DEBIAN "$STAGE" | cut -f1)"
sed -e "s/@VERSION@/$VERSION/" -e "s/@SIZE@/$SIZE/" -e "s|@MAINTAINER@|$MAINTAINER|" packaging/debian/control > "$STAGE/DEBIAN/control"

# --- md5sums (regular files only)
( cd "$STAGE" && find . -type f -not -path './DEBIAN/*' -printf '%P\0' | sort -z | xargs -0 md5sum ) > "$STAGE/DEBIAN/md5sums"

find "$STAGE" -exec touch -h -d "@$EPOCH" {} +
find "$STAGE" -type d -exec chmod 0755 {} +

dpkg-deb --root-owner-group -Zxz --build "$STAGE" "$OUT"
echo "==> Built $OUT"
dpkg-deb --info "$OUT" | sed -n '1,25p'
