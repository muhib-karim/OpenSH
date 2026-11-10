#!/bin/bash
# OpenSH - Unix Installer (macOS/Linux)
# Based on nlsh (https://github.com/junaid-mahmood/nlsh) by Junaid Mahmood
# Support: https://ko-fi.com/ai_dev_2024

set -euo pipefail

INSTALL_DIR="$HOME/.opsh"
REPO_URL="https://github.com/muhib-karim/OpenSH.git"

echo "Installing OpenSH..."

# Python 3.9+ is the only requirement: OpenSH uses the standard library only.
if ! command -v python3 > /dev/null 2>&1; then
    echo "Python 3.9 or newer is required. Please install it first."
    exit 1
fi
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)'; then
    echo "Python 3.9 or newer is required (found $(python3 --version 2>&1))."
    exit 1
fi

need_git() {
    if ! command -v git > /dev/null 2>&1; then
        echo "git is required to download OpenSH. Please install it first."
        exit 1
    fi
}

# Where this script lives. Empty when it is piped (curl ... | bash): then there is
# no source folder and OpenSH is downloaded. The current directory is never used
# as a source, so a stray opsh.py or .env in it cannot end up installed.
SOURCE_DIR=""
SCRIPT_PATH="${BASH_SOURCE[0]:-}"
if [ -n "$SCRIPT_PATH" ] && [ -f "$SCRIPT_PATH" ]; then
    SOURCE_DIR="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)"
fi

if [ -n "$SOURCE_DIR" ] && [ -f "$SOURCE_DIR/opsh.py" ] && [ "$SOURCE_DIR" != "$INSTALL_DIR" ]; then
    # Local installation (development mode). Also refreshes an earlier local install.
    echo "Installing from $SOURCE_DIR..."
    mkdir -p "$INSTALL_DIR"
    cp "$SOURCE_DIR/opsh.py" "$INSTALL_DIR/"
    for extra in requirements.txt uninstall.sh; do
        if [ -f "$SOURCE_DIR/$extra" ]; then
            cp "$SOURCE_DIR/$extra" "$INSTALL_DIR/"
        fi
    done
    # Bring an API key along, but never overwrite one that is already installed.
    if [ -f "$SOURCE_DIR/.env" ] && [ ! -f "$INSTALL_DIR/.env" ]; then
        cp "$SOURCE_DIR/.env" "$INSTALL_DIR/"
    fi
elif [ -d "$INSTALL_DIR/.git" ]; then
    echo "Updating existing installation..."
    need_git
    git -C "$INSTALL_DIR" pull --quiet --ff-only || echo "Warning: could not update from git; keeping the current files."
elif [ -f "$INSTALL_DIR/opsh.py" ]; then
    # Installed earlier by copying files: fetch the current program into place.
    echo "Updating existing installation..."
    need_git
    TMP_DIR="$(mktemp -d)"
    if git clone --quiet --depth 1 "$REPO_URL" "$TMP_DIR/OpenSH"; then
        cp "$TMP_DIR/OpenSH/opsh.py" "$TMP_DIR/OpenSH/requirements.txt" "$TMP_DIR/OpenSH/uninstall.sh" "$INSTALL_DIR/"
    else
        echo "Warning: could not download the update; keeping the current files."
    fi
    rm -rf "$TMP_DIR"
else
    echo "Downloading OpenSH..."
    need_git
    git clone --quiet --depth 1 "$REPO_URL" "$INSTALL_DIR"
fi

# The API key file, if there is one, should be readable by its owner only.
if [ -f "$INSTALL_DIR/.env" ]; then
    chmod 600 "$INSTALL_DIR/.env"
fi

# Create opsh command
echo "Creating opsh command..."
mkdir -p "$HOME/.local/bin"
cat > "$HOME/.local/bin/opsh" << 'EOF'
#!/bin/bash
exec python3 "$HOME/.opsh/opsh.py" "$@"
EOF
chmod +x "$HOME/.local/bin/opsh"

# Put ~/.local/bin on PATH
add_to_path() {
    local rc_file="$1"
    if grep -q '.local/bin' "$rc_file" 2> /dev/null; then
        return 0
    fi
    printf '\n# OpenSH - PATH\nexport PATH="$HOME/.local/bin:$PATH"\n' >> "$rc_file"
}

# Shell startup files that already exist get the PATH line. Files that do not
# exist are left alone: creating ~/.bash_profile, for one, would stop bash from
# reading ~/.profile.
for rc_file in "$HOME/.zshrc" "$HOME/.zprofile" "$HOME/.bashrc" "$HOME/.bash_profile" "$HOME/.profile"; do
    if [ -f "$rc_file" ]; then
        add_to_path "$rc_file"
    fi
done

# Make sure the shell in use is covered even if it has no startup file yet.
case "$(basename "${SHELL:-}")" in
    zsh)
        add_to_path "$HOME/.zshrc"
        ;;
    bash)
        add_to_path "$HOME/.bashrc"
        if [ ! -f "$HOME/.bash_profile" ] && [ ! -f "$HOME/.bash_login" ] && [ ! -f "$HOME/.profile" ]; then
            add_to_path "$HOME/.profile"
        fi
        ;;
    *)
        echo "Note: add $HOME/.local/bin to your PATH if 'opsh' is not found."
        ;;
esac

echo ""
echo "================================================"
echo "  OpenSH installed successfully!"
echo "================================================"
echo ""
echo "To start using OpenSH:"
echo "  1. Open a new terminal window"
echo "  2. Type: opsh"
echo ""
echo "Based on nlsh by Junaid Mahmood"
echo "Support: https://ko-fi.com/ai_dev_2024"
echo ""
