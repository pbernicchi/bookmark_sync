# bookmark_sync

A local Python tool that keeps bookmarks in sync across **Safari, Firefox, Chrome, Brave, and Edge** — including across macOS, Ubuntu, and Windows (e.g. Parallels VM).

No cloud service required. One canonical JSON file on a shared location (iCloud Drive, Dropbox, or a Parallels shared folder) is the source of truth.

---

## Supported browsers

| Browser | Read | Write |
|---|---|---|
| Chrome | ✅ native JSON | ✅ direct |
| Brave | ✅ native JSON | ✅ direct |
| Edge | ✅ native JSON | ✅ direct |
| Firefox | ✅ SQLite | HTML export (manual import) |
| Safari | HTML export (manual) | HTML export (manual import) |

---

## Requirements

- Python 3.9+
- `beautifulsoup4`, `lxml`

```bash
python3 -m venv ~/bookmark_sync_env
source ~/bookmark_sync_env/bin/activate
pip install beautifulsoup4 lxml
```

---

## Quick start

```bash
# 1. Import Safari bookmarks as source of truth
python3 bookmark_sync.py safari-in ~/Downloads/safari_export.html

# 2. Push to all Chromium browsers + generate HTML for Safari/Firefox
#    (close Chrome, Brave, Edge first)
python3 bookmark_sync.py push

# 3. Check status
python3 bookmark_sync.py status
```

---

## Commands

| Command | Description |
|---|---|
| `pull` | Read all browsers on this machine → merge into master JSON |
| `push` | Write master → Chromium browsers + generate HTML export |
| `safari-in <file>` | Import a Safari/Netscape HTML export into master |
| `safari-out [file]` | Export master as HTML for Safari or Firefox import |
| `dedupe` | Remove duplicate URLs from master |
| `status` | Show counts by folder and source browser |
| `help` | Print command summary |

---

## Configuration

Edit the `MASTER_FILE` variable near the top of `bookmark_sync.py` to point at a location accessible from all your machines:

```python
# iCloud Drive (macOS default)
MASTER_FILE = HOME / "Library/Mobile Documents/com~apple~CloudDocs/bookmark_sync/bookmarks_master.json"

# Dropbox (works on macOS, Linux, Windows)
MASTER_FILE = HOME / "Dropbox/bookmark_sync/bookmarks_master.json"

# Parallels shared folder (Windows side)
MASTER_FILE = Path(r"\\Mac\Home\bookmark_sync\bookmarks_master.json")
```

---

## Shell alias (optional)

Add to `~/.zshrc` for quick access from anywhere:

```bash
alias bsync='source ~/bookmark_sync_env/bin/activate && python3 ~/Git/bookmark_sync/bookmark_sync.py'
```

Then: `bsync pull`, `bsync push`, `bsync status`

---

## Backups

Before every write, the script backs up the original file to `~/.bookmark_sync_backups/` with a timestamp. Nothing is ever lost.

---

## Platform notes

- **Safari**: Apple locks the bookmark database. Export via *File → Export Bookmarks*, then run `safari-in`.
- **Firefox**: Write-back via HTML import only (writing to a live SQLite DB is unsafe).
- **Linux/Ubuntu**: Chrome, Brave, and Firefox paths are auto-detected under `~/.config` and `~/.mozilla`.
- **Windows**: Chrome, Brave, Edge, and Firefox paths are auto-detected from `%LOCALAPPDATA%` and `%APPDATA%`.
- **Parallels VM**: Point `MASTER_FILE` at a Parallels shared folder path accessible from both macOS and Windows.
