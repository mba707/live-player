#!/bin/sh
# Live Player VLC opener for macOS and Linux. Do not use sudo.
#   curl -fsSL http://192.168.50.49:8112/static/install-vlc-handler.sh | bash
set -eu

OS="$(uname -s)"
BIN="${HOME}/.local/bin"
OPENER="${BIN}/live-player-open"
mkdir -p "${BIN}"

echo "Installing Live Player VLC opener for ${OS}..."

cat > "${OPENER}" << 'PY'
#!/usr/bin/env python3
import os
import sys
import urllib.parse
from shutil import which

def stream_url(raw):
    parsed = urllib.parse.urlparse(raw)
    query = urllib.parse.parse_qs(parsed.query)
    url = (query.get("url") or [""])[0]
    if not url:
        path = urllib.parse.unquote(parsed.path.lstrip("/"))
        url = path.replace("http:/", "http://", 1) if path.startswith("http:/") else path
    if not url.startswith(("http://", "https://")):
        raise SystemExit("live-player-open: refused %r" % (raw,))
    return url

def vlc_command():
    if sys.platform == "darwin":
        return ["open", "-a", "VLC"]
    if which("vlc"):
        return ["vlc"]
    if which("flatpak"):
        return ["flatpak", "run", "org.videolan.VLC"]
    raise SystemExit("live-player-open: VLC is not installed")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("usage: live-player-open liveplayer:?url=http://...")
    url = stream_url(sys.argv[1])
    command = vlc_command()
    os.execvp(command[0], [*command, url])
PY
chmod +x "${OPENER}"
echo "Wrote ${OPENER}"

install_linux() {
    APP="${HOME}/.local/share/applications"
    mkdir -p "${APP}"
    cat > "${APP}/live-player-vlc.desktop" << EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=Live Player VLC
Comment=Open Live Player streams in VLC
Exec=${OPENER} %u
TryExec=${OPENER}
StartupNotify=false
Terminal=false
NoDisplay=true
MimeType=x-scheme-handler/liveplayer;
EOF
    if command -v xdg-mime >/dev/null 2>&1; then
        xdg-mime default live-player-vlc.desktop x-scheme-handler/liveplayer
    fi
    if command -v gio >/dev/null 2>&1; then
        gio mime x-scheme-handler/liveplayer live-player-vlc.desktop >/dev/null 2>&1 || true
    fi
    if command -v update-desktop-database >/dev/null 2>&1; then
        update-desktop-database "${APP}" >/dev/null 2>&1 || true
    fi
    echo "Linux opener installed."
}

install_macos() {
    if [ ! -d "/Applications/VLC.app" ] && [ ! -d "${HOME}/Applications/VLC.app" ]; then
        echo "VLC.app was not found in /Applications." >&2
        echo "Install VLC first: https://www.videolan.org/vlc/" >&2
        exit 1
    fi
    if [ ! -x /usr/bin/osacompile ]; then
        echo "osacompile is missing. Install Xcode command-line tools:" >&2
        echo "  xcode-select --install" >&2
        exit 1
    fi
    APPS="${HOME}/Applications"
    BUNDLE="${APPS}/Live Player VLC.app"
    mkdir -p "${APPS}"
    TMP="$(mktemp -t live-player-vlc.XXXXXX)"
    cat > "${TMP}" << 'EOF'
on open location theURL
  set streamURL to do shell script "/usr/bin/ruby -ruri -e 'print URI.decode_www_form_component(ARGV[0].split(\"url=\", 2)[1].to_s.split(\"&\").first)' -- " & quoted form of theURL
  do shell script "/usr/bin/open -a VLC " & quoted form of streamURL
end open location
EOF
    echo "Building ${BUNDLE}"
    /usr/bin/osacompile -o "${BUNDLE}" "${TMP}"
    rm -f "${TMP}"

    PLIST="${BUNDLE}/Contents/Info.plist"
    /usr/libexec/PlistBuddy -c "Delete :CFBundleURLTypes" "${PLIST}" >/dev/null 2>&1 || true
    /usr/libexec/PlistBuddy -c "Delete :CFBundleIdentifier" "${PLIST}" >/dev/null 2>&1 || true
    /usr/libexec/PlistBuddy -c "Add :CFBundleIdentifier string com.liveplayer.vlc" "${PLIST}"
    /usr/libexec/PlistBuddy -c "Add :CFBundleURLTypes array" "${PLIST}"
    /usr/libexec/PlistBuddy -c "Add :CFBundleURLTypes:0 dict" "${PLIST}"
    /usr/libexec/PlistBuddy -c "Add :CFBundleURLTypes:0:CFBundleURLName string Live Player" "${PLIST}"
    /usr/libexec/PlistBuddy -c "Add :CFBundleURLTypes:0:CFBundleURLSchemes array" "${PLIST}"
    /usr/libexec/PlistBuddy -c "Add :CFBundleURLTypes:0:CFBundleURLSchemes:0 string liveplayer" "${PLIST}"

    xattr -dr com.apple.quarantine "${BUNDLE}" >/dev/null 2>&1 || true
    LSREGISTER="/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"
    if [ -x "${LSREGISTER}" ]; then
        "${LSREGISTER}" -f "${BUNDLE}"
    fi
    echo "macOS opener installed at ${BUNDLE}"
}

case "${OS}" in
    Linux) install_linux ;;
    Darwin) install_macos ;;
    *)
        echo "Unsupported OS: ${OS}. Use Linux or macOS." >&2
        exit 1
        ;;
esac

echo
echo "Done. Next steps:"
echo "  1. Fully quit Chrome (Cmd+Q on a Mac, not just close the window)."
echo "  2. Open Live Player again and click Play."
echo "  3. If Chrome asks to open Live Player VLC, click Open."
echo "Handler: ${OPENER}"
