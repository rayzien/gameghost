#!/usr/bin/env bash
# ==============================================================================
# GameGhost One-Line Installer & Setup
# ==============================================================================
set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
BIN_DIR="${HOME}/.local/bin"

echo "==> Setting up GameGhost..."

# 1. Ensure uinput permissions
if [ -c /dev/uinput ]; then
    if ! [ -w /dev/uinput ]; then
        echo "[INFO] Configuring /dev/uinput permissions for virtual gamepad..."
        sudo usermod -aG input "$USER" 2>/dev/null || true
        sudo setfacl -m "u:${USER}:rw" /dev/uinput 2>/dev/null || true
    fi
fi

# 2. Make launcher executable and create symlink
chmod +x "${SCRIPT_DIR}/bin/gameghost"
mkdir -p "${BIN_DIR}"
ln -sf "${SCRIPT_DIR}/bin/gameghost" "${BIN_DIR}/gameghost"

# 3. Create Desktop Launcher
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
echo "Run 'gameghost host' or 'gameghost dmc5' to start playing."
