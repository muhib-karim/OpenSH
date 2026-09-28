#!/bin/bash
# OpenSH - Unix Uninstaller
# Based on nlsh (https://github.com/junaid-mahmood/nlsh)

echo "Uninstalling OpenSH..."

rm -rf "$HOME/.opsh"
rm -f "$HOME/.local/bin/opsh"

# Remove the lines the installer added to shell configs (auto-start, and the
# "# OpenSH - PATH" marker with the export line after it). Only touch files that
# contain them, and write back with cat so symlinked dotfiles stay symlinks.
for rc_file in "$HOME/.zprofile" "$HOME/.zshrc" "$HOME/.bashrc" "$HOME/.bash_profile"; do
    if [ -f "$rc_file" ] && grep -qE 'opsh # auto-start|OpenSH - auto-start|# OpenSH - PATH' "$rc_file"; then
        tmp_file="$(mktemp)"
        if sed -e '/opsh # auto-start/d' -e '/OpenSH - auto-start/d' -e '/# OpenSH - PATH/{N;d;}' "$rc_file" > "$tmp_file"; then
            cat "$tmp_file" > "$rc_file"
        fi
        rm -f "$tmp_file"
    fi
done

echo "✓ OpenSH has been removed"
