#!/usr/bin/env bash
# bookmark_sync installer
# Usage: curl -fsSL https://raw.githubusercontent.com/pbernicchi/bookmark_sync/main/install.sh | bash

set -euo pipefail

REPO="https://raw.githubusercontent.com/pbernicchi/bookmark_sync/main"
INSTALL_DIR="${HOME}/.local/share/bookmark_sync"
BIN_DIR="${HOME}/.local/bin"
WRAPPER="${BIN_DIR}/bsync"

# ── helpers ──────────────────────────────────────────────────────────────────
info()  { printf '\033[1;34m==> \033[0m%s\n' "$*"; }
ok()    { printf '\033[1;32m ok \033[0m%s\n' "$*"; }
die()   { printf '\033[1;31merr \033[0m%s\n' "$*" >&2; exit 1; }

# ── Python check ─────────────────────────────────────────────────────────────
PYTHON=""
for py in python3 python; do
    if command -v "$py" &>/dev/null; then
        ver=$("$py" -c 'import sys; print(sys.version_info >= (3,9))' 2>/dev/null)
        if [[ "$ver" == "True" ]]; then
            PYTHON="$py"
            break
        fi
    fi
done
[[ -n "$PYTHON" ]] || die "Python 3.9+ is required but was not found."
ok "Python: $($PYTHON --version)"

# ── create directories ────────────────────────────────────────────────────────
mkdir -p "$INSTALL_DIR" "$BIN_DIR"

# ── download script ───────────────────────────────────────────────────────────
info "Downloading bookmark_sync.py …"
curl -fsSL "${REPO}/bookmark_sync.py" -o "${INSTALL_DIR}/bookmark_sync.py"
ok "Saved to ${INSTALL_DIR}/bookmark_sync.py"

# ── virtual environment ───────────────────────────────────────────────────────
info "Creating virtual environment …"
"$PYTHON" -m venv "${INSTALL_DIR}/venv"
ok "Venv at ${INSTALL_DIR}/venv"

info "Installing dependencies (beautifulsoup4, lxml) …"
"${INSTALL_DIR}/venv/bin/pip" install --quiet beautifulsoup4 lxml
ok "Dependencies installed"

# ── wrapper script ────────────────────────────────────────────────────────────
info "Writing bsync wrapper to ${WRAPPER} …"
cat > "$WRAPPER" <<'WRAPPER_EOF'
#!/usr/bin/env bash
exec "${HOME}/.local/share/bookmark_sync/venv/bin/python3" \
     "${HOME}/.local/share/bookmark_sync/bookmark_sync.py" "$@"
WRAPPER_EOF
chmod +x "$WRAPPER"
ok "Wrapper written"

# ── PATH reminder ─────────────────────────────────────────────────────────────
if [[ ":${PATH}:" != *":${BIN_DIR}:"* ]]; then
    echo ""
    echo "  Add ${BIN_DIR} to your PATH by adding this line to ~/.zshrc or ~/.bashrc:"
    echo ""
    echo "    export PATH=\"\$HOME/.local/bin:\$PATH\""
    echo ""
fi

# ── done ──────────────────────────────────────────────────────────────────────
echo ""
echo "  bookmark_sync installed. Next steps:"
echo ""
echo "  1. Edit MASTER_FILE in ${INSTALL_DIR}/bookmark_sync.py"
echo "     to point at your shared location (iCloud Drive, Dropbox, etc.):"
echo ""
echo "     nano ${INSTALL_DIR}/bookmark_sync.py"
echo ""
echo "  2. Pull bookmarks from all browsers on this machine:"
echo ""
echo "     bsync pull"
echo ""
echo "  3. For Safari: File → Export Bookmarks in Safari, then:"
echo ""
echo "     bsync safari-in ~/Downloads/bookmarks.html"
echo ""
echo "  Run  bsync help  for all commands."
echo ""
