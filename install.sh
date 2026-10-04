#!/bin/bash
# OpenSH - Unix Installer (macOS/Linux)
# Based on nlsh (https://github.com/junaid-mahmood/nlsh) by Junaid Mahmood
# Support: https://ko-fi.com/ai_dev_2024

set -e

INSTALL_DIR="$HOME/.opsh"
REPO_URL="https://github.com/muhib-karim/OpenSH.git"

echo "Installing OpenSH..."

# Check for Python 3
if ! command -v python3 &> /dev/null; then
    echo "Python 3 is required. Please install it first."
    exit 1
fi

# Clone or update repository
if [ -d "$INSTALL_DIR" ]; then
    echo "Updating existing installation..."
    cd "$INSTALL_DIR"
    git pull --quiet 2>/dev/null || echo "Warning: Could not update from git."
else
    echo "Downloading OpenSH..."
    
    # Check if we're running from the source directory
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    if [ -f "$SCRIPT_DIR/opsh.py" ]; then
        # Local installation (development mode)
        echo "Installing from local directory..."
        mkdir -p "$INSTALL_DIR"
        cp "$SCRIPT_DIR/opsh.py" "$INSTALL_DIR/"
        cp "$SCRIPT_DIR/requirements.txt" "$INSTALL_DIR/"
        [ -f "$SCRIPT_DIR/.env" ] && cp "$SCRIPT_DIR/.env" "$INSTALL_DIR/"
    else
        # Remote installation
        git clone --quiet "$REPO_URL" "$INSTALL_DIR"
    fi
fi

cd "$INSTALL_DIR"

# Set up Python virtual environment
echo "Setting up Python environment..."
python3 -m venv venv
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
    touch "$rc_file"
    
    # Add to PATH if not already there
    if ! grep -q '.local/bin' "$rc_file" 2>/dev/null; then
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

# Configure common shell rc files
setup_shell "$HOME/.zprofile"
setup_shell "$HOME/.zshrc"
setup_shell "$HOME/.bashrc"
setup_shell "$HOME/.bash_profile"

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
