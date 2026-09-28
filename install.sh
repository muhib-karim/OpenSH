#!/bin/bash
# OpenSH - Unix Installer (macOS/Linux)
# Based on nlsh (https://github.com/junaid-mahmood/nlsh) by Junaid Mahmood
# Support: https://ko-fi.com/ai_dev_2024

set -e

INSTALL_DIR="$HOME/.opsh"
REPO_URL="https://github.com/ai-dev-2024/OpenSH.git"

echo "Installing OpenSH..."

# Check for Python 3
if ! command -v python3 &> /dev/null; then
    echo "Python 3 is required. Please install it first."
    exit 1
fi

# Check if we're running from a source checkout (./install.sh) rather than via curl | bash
SCRIPT_DIR=""
if [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "$(dirname "${BASH_SOURCE[0]}")/opsh.py" ]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi

if [ -n "$SCRIPT_DIR" ] && ! [ "$SCRIPT_DIR/opsh.py" -ef "$INSTALL_DIR/opsh.py" ]; then
    # Local installation (development mode) - always copy the current source files
    echo "Installing from local directory..."
    mkdir -p "$INSTALL_DIR"
    cp "$SCRIPT_DIR/opsh.py" "$INSTALL_DIR/"
    cp "$SCRIPT_DIR/requirements.txt" "$INSTALL_DIR/"
    cp "$SCRIPT_DIR/uninstall.sh" "$INSTALL_DIR/"
    # Don't replace API keys that an existing install already has
    if [ -f "$SCRIPT_DIR/.env" ] && [ ! -f "$INSTALL_DIR/.env" ]; then
        cp "$SCRIPT_DIR/.env" "$INSTALL_DIR/"
        chmod 600 "$INSTALL_DIR/.env"
    fi
elif [ -d "$INSTALL_DIR/.git" ]; then
    echo "Updating existing installation..."
    git -C "$INSTALL_DIR" pull --quiet 2>/dev/null || echo "Warning: Could not update from git."
elif [ -f "$INSTALL_DIR/opsh.py" ]; then
    echo "Warning: $INSTALL_DIR was installed from a local checkout and can't be updated here."
    echo "Run ./install.sh from that checkout, or delete $INSTALL_DIR and run this installer again."
else
    # Remote installation
    echo "Downloading OpenSH..."
    if ! command -v git &> /dev/null; then
        echo "git is required to download OpenSH. Please install it first."
        exit 1
    fi
    git clone --quiet "$REPO_URL" "$INSTALL_DIR"
fi

cd "$INSTALL_DIR"

# Set up Python virtual environment
echo "Setting up Python environment..."
if ! python3 -m venv venv; then
    echo "Could not create a Python virtual environment."
    echo "On Debian/Ubuntu, install venv support first: sudo apt install python3-venv"
    exit 1
fi
source venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

# Create opsh command
echo "Creating opsh command..."
mkdir -p "$HOME/.local/bin"
cat > "$HOME/.local/bin/opsh" << 'EOF'
#!/bin/bash
source "$HOME/.opsh/venv/bin/activate"
python "$HOME/.opsh/opsh.py" "$@"
EOF
chmod +x "$HOME/.local/bin/opsh"

# Setup shell configuration
setup_shell() {
    local rc_file="$1"
    
    # Add to PATH if not already there
    if ! grep -Eq '^[^#]*\.local/bin' "$rc_file" 2>/dev/null; then
        echo '' >> "$rc_file"
        echo '# OpenSH - PATH' >> "$rc_file"
        echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$rc_file"
    fi
    
    # Optional: Add auto-start (commented out by default)
    # Uncomment the following lines if you want OpenSH to start automatically
    # if ! grep -q 'opsh # auto-start' "$rc_file" 2>/dev/null; then
    #     echo '' >> "$rc_file"
    #     echo '# OpenSH - auto-start (remove this line to disable)' >> "$rc_file"
    #     echo '[ -t 0 ] && [ -x "$HOME/.local/bin/opsh" ] && opsh # auto-start' >> "$rc_file"
    # fi
}

# Configure the shell rc files that already exist. Creating a missing ~/.bash_profile
# would stop bash login shells from reading ~/.profile, so only fall back to the
# rc file of the user's shell when none exist.
configured=0
for rc_file in "$HOME/.zprofile" "$HOME/.zshrc" "$HOME/.bashrc" "$HOME/.bash_profile"; do
    if [ -f "$rc_file" ]; then
        setup_shell "$rc_file"
        configured=1
    fi
done
if [ "$configured" -eq 0 ]; then
    case "$(basename "${SHELL:-bash}")" in
        zsh) setup_shell "$HOME/.zshrc" ;;
        *) setup_shell "$HOME/.bashrc" ;;
    esac
fi

export PATH="$HOME/.local/bin:$PATH"

echo ""
echo "================================================"
echo "  OpenSH installed successfully!"
echo "================================================"
echo ""
echo "To start using OpenSH:"
echo "  1. Open a new terminal window"
echo "  2. Type: opsh"
echo ""
echo "Or run it now: opsh"
echo ""
echo "Based on nlsh by Junaid Mahmood"
echo "Support: https://ko-fi.com/ai_dev_2024"
echo ""
