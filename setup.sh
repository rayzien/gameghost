#!/bin/sh
# ==============================================================================
# GameGhost One-Line Installer & Setup (Linux & Android Termux)
# ==============================================================================
set -e

SCRIPT_DIR="$( cd "$( dirname "$0" )" && pwd )"
BIN_DIR="${HOME}/.local/bin"
TERMUX_BIN="${HOME}/bin"

echo "==> Setting up GameGhost..."

# 1. Ensure uinput permissions on Linux PC host
if [ -c /dev/uinput ]; then
    if ! [ -w /dev/uinput ]; then
        echo "[INFO] Configuring /dev/uinput permissions for virtual gamepad..."
        sudo usermod -aG input "$USER" 2>/dev/null || true
        sudo setfacl -m "u:${USER}:rw" /dev/uinput 2>/dev/null || true
    fi
fi

# 2. Make launcher executable and install global symlinks
chmod +x "${SCRIPT_DIR}/bin/gameghost"

mkdir -p "${BIN_DIR}"
ln -sf "${SCRIPT_DIR}/bin/gameghost" "${BIN_DIR}/gameghost"
ln -sf "${SCRIPT_DIR}/bin/gameghost" "${BIN_DIR}/gg"

mkdir -p "${TERMUX_BIN}"
ln -sf "${SCRIPT_DIR}/bin/gameghost" "${TERMUX_BIN}/gameghost"
ln -sf "${SCRIPT_DIR}/bin/gameghost" "${TERMUX_BIN}/gg"

# 3. Create Desktop Launcher if Desktop directory exists
DESKTOP_DIR="${HOME}/Desktop"
if [ -d "${DESKTOP_DIR}" ]; then
    cat << EOF > "${DESKTOP_DIR}/GameGhost.desktop"
[Desktop Entry]
Type=Application
Name=GameGhost Portal
Comment=Cast PC games to phone with on-screen controls
Exec=${BIN_DIR}/gameghost host
Icon=input-gaming
Terminal=true
Categories=Game;Network;
EOF
    chmod +x "${DESKTOP_DIR}/GameGhost.desktop"
fi

echo "==> GameGhost installation complete!"
echo "You can now run 'gameghost' or quick alias 'gg' from anywhere:"
echo "  gg             - Interactive Touch Menu on your phone"
echo "  gg open        - Launch portal in phone browser"
echo "  gg client      - Launch native SDL2 touch client"
echo "  gg scan        - Scan network for PC host"
echo "  gg dmc5        - Launch Devil May Cry 5 & stream"
echo "  gg host        - Start PC streaming host"
echo "  gg status      - Show connection status"
