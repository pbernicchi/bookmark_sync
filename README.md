# bookmark_sync

[![version](https://img.shields.io/badge/version-1.0.0-blue)](https://github.com/pbernicchi/bookmark_sync/releases)
[![python](https://img.shields.io/badge/python-3.9%2B-blue)](https://www.python.org/)
[![platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux%20%7C%20Windows-lightgrey)](#platform-notes)

A local Python CLI that keeps bookmarks synchronized across **Safari, Firefox, Chrome, Brave, and Edge** on macOS, Ubuntu/Linux, and Windows.

No cloud service or account required. A single `bookmarks_master.json` on any shared location (iCloud Drive, Dropbox, or a Parallels shared folder) is the source of truth.

---

## Supported browsers

| Browser | Read | Write |
|---|---|---|
| Chrome | native JSON | direct |
| Brave | native JSON | direct |
| Edge | native JSON | direct |
| Firefox | SQLite | HTML import |
| Safari | HTML export | HTML import |

Chrome, Brave, and Edge are read/written directly. Firefox and Safari use Netscape HTML as the interchange format since their databases are unsafe or inaccessible to write directly.

---

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/pbernicchi/bookmark_sync/main/install.sh | bash
```

The installer:
- Downloads `bookmark_sync.py` to `~/.local/share/bookmark_sync/`
- Creates a Python virtual environment there
- Installs `beautifulsoup4` and `lxml`
- Writes a `bsync` wrapper to `~/.local/bin/`

After install, make sure `~/.local/bin` is in your `PATH`:

```bash
# add to ~/.zshrc or ~/.bashrc if not already there
export PATH="$HOME/.local/bin:$PATH"
```

### Manual install (developers)

```bash
git clone git@github.com:pbernicchi/bookmark_sync.git
cd bookmark_sync
python3 -m venv bookmark_sync_env
source bookmark_sync_env/bin/activate
pip install -r requirements.txt
```

---

## Setup

After installing, open `~/.local/share/bookmark_sync/bookmark_sync.py` and set `MASTER_FILE` near the top to point at a location accessible from all your machines:

```python
# iCloud Drive (macOS — syncs automatically to all Apple devices)
MASTER_FILE = HOME / "Library/Mobile Documents/com~apple~CloudDocs/bookmark_sync/bookmarks_master.json"

# Dropbox (works on macOS, Linux, Windows)
MASTER_FILE = HOME / "Dropbox/bookmark_sync/bookmarks_master.json"

# Parallels shared folder (Windows side)
MASTER_FILE = Path(r"\\Mac\Home\bookmark_sync\bookmarks_master.json")
```

---

## Quick start

```bash
# Pull all browsers on this machine into the master file
bsync pull

# Import Safari bookmarks (File → Export Bookmarks in Safari first)
bsync safari-in ~/Downloads/bookmarks.html

# Push master to all Chromium browsers + generate HTML for Safari/Firefox
# (close Chrome, Brave, and Edge before running)
bsync push

# Check what's in the master file
bsync status
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
| `version` | Print the installed version |
| `help` | Print command summary |

---

## Backups

Before every write the script saves a timestamped copy of the original file to `~/.bookmark_sync_backups/`. Nothing is ever overwritten without a backup.

---

## Platform notes

- **Safari** — Apple locks the bookmark database with `EPERM`. Workflow: *File → Export Bookmarks* → `bsync safari-in` → `bsync safari-out` → re-import into Safari.
- **Firefox** — Writing to a live `places.sqlite` risks corruption (active WAL journal). HTML import is the safe path.
- **Linux/Ubuntu** — Chrome, Brave, and Firefox paths are auto-detected under `~/.config` and `~/.mozilla`. iCloud Drive has no native Linux client; use Dropbox or `rclone`.
- **Windows** — Chrome, Brave, Edge, and Firefox paths are auto-detected from `%LOCALAPPDATA%` and `%APPDATA%`.
- **Parallels VM** — Point `MASTER_FILE` at a Parallels shared folder path visible from both macOS and Windows.

---

## Versioning

Releases follow [Semantic Versioning](https://semver.org). See [Releases](https://github.com/pbernicchi/bookmark_sync/releases) for the changelog.

```bash
bsync version
```
