#!/usr/bin/env python3
"""
bookmark_sync.py  —  Cross-browser bookmark synchronizer
=========================================================
Browsers supported
  • Chrome, Brave, Edge  (native Chromium JSON — read/write directly)
  • Firefox              (places.sqlite — read; HTML import for write)
  • Safari               (Netscape HTML export/import — semi-manual)

Commands
  python bookmark_sync.py pull                    # all browsers → master JSON
  python bookmark_sync.py push                    # master JSON → all Chromium browsers + HTML export
  python bookmark_sync.py safari-in  <file.html>  # Safari HTML export → master
  python bookmark_sync.py safari-out [file.html]  # master → HTML (for Safari / Firefox import)
  python bookmark_sync.py status                  # stats on the master file
  python bookmark_sync.py dedupe                  # remove duplicate URLs from master
  python bookmark_sync.py help                    # show this message

Requirements
  pip install beautifulsoup4 lxml

Quick-start
  1. Edit MASTER_FILE below to point at a location all your machines can reach
     (iCloud Drive folder, Dropbox, or a Parallels shared folder).
  2. On macOS, run:  python bookmark_sync.py pull
  3. On Ubuntu/Windows, copy bookmark_sync.py there, update MASTER_FILE, then run pull.
  4. After any pull, run push to propagate changes back to Chromium browsers.
  5. For Safari: export from Safari → run safari-in → later run safari-out and re-import.
"""

__version__ = "1.0.0"

import json
import os
import platform
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

try:
    from bs4 import BeautifulSoup
except ImportError:
    print("Missing dependency. Run:  pip install beautifulsoup4 lxml")
    sys.exit(1)


# ═══════════════════════════════════════════════════════════════════════════════
#  CONFIGURATION  —  edit this section
# ═══════════════════════════════════════════════════════════════════════════════

# Location of the canonical master JSON shared across all machines.
# Pick whichever cloud/shared folder works for your setup:
#
#   iCloud Drive (macOS default):
#     HOME / "Library/Mobile Documents/com~apple~CloudDocs/bookmark_sync/bookmarks_master.json"
#
#   Dropbox:
#     HOME / "Dropbox/bookmark_sync/bookmarks_master.json"
#
#   Parallels shared folder (inside the VM, Windows):
#     Path(r"\\Mac\Home\bookmark_sync\bookmarks_master.json")
#     or wherever Parallels mounts the macOS home directory
#
#   Ubuntu (if you mount iCloud via rclone or use Dropbox Linux):
#     HOME / "Dropbox/bookmark_sync/bookmarks_master.json"

HOME = Path.home()

MASTER_FILE = (
    HOME / "Library/Mobile Documents/com~apple~CloudDocs/bookmark_sync/bookmarks_master.json"
)
# Alternatives:
# MASTER_FILE = HOME / "Dropbox/bookmark_sync/bookmarks_master.json"
# MASTER_FILE = HOME / "Downloads/bookmark_sync/bookmarks_master.json"  # local testing

# Directory where backups of browser files and master are stored before any write
BACKUP_DIR = HOME / ".bookmark_sync_backups"

# Set to True to skip writing to a browser even if its file is found
SKIP_BROWSERS: set[str] = set()
# e.g. SKIP_BROWSERS = {"Chrome"}  to skip Chrome


# ═══════════════════════════════════════════════════════════════════════════════
#  BROWSER FILE PATHS  —  auto-detected per OS; override here if needed
# ═══════════════════════════════════════════════════════════════════════════════

SYSTEM = platform.system()  # "Darwin" | "Linux" | "Windows"


def get_browser_paths() -> dict[str, Optional[Path]]:
    """Return the bookmark file path for each browser on the current OS."""
    if SYSTEM == "Darwin":
        sup = HOME / "Library/Application Support"
        return {
            "Chrome": sup / "Google/Chrome/Default/Bookmarks",
            "Brave":  sup / "BraveSoftware/Brave-Browser/Default/Bookmarks",
            "Edge":   sup / "Microsoft Edge/Default/Bookmarks",
            "Firefox": _find_firefox_sqlite(sup / "Firefox/Profiles"),
        }
    elif SYSTEM == "Linux":
        cfg = HOME / ".config"
        return {
            "Chrome":  cfg / "google-chrome/Default/Bookmarks",
            "Brave":   cfg / "BraveSoftware/Brave-Browser/Default/Bookmarks",
            "Edge":    cfg / "microsoft-edge/Default/Bookmarks",
            "Firefox": _find_firefox_sqlite(HOME / ".mozilla/firefox"),
        }
    elif SYSTEM == "Windows":
        local = Path(os.environ.get("LOCALAPPDATA", "C:/Users/Default/AppData/Local"))
        appdata = Path(os.environ.get("APPDATA", "C:/Users/Default/AppData/Roaming"))
        return {
            "Chrome":  local / "Google/Chrome/User Data/Default/Bookmarks",
            "Brave":   local / "BraveSoftware/Brave-Browser/User Data/Default/Bookmarks",
            "Edge":    local / "Microsoft/Edge/User Data/Default/Bookmarks",
            "Firefox": _find_firefox_sqlite(appdata / "Mozilla/Firefox/Profiles"),
        }
    return {}


def _find_firefox_sqlite(profiles_dir: Path) -> Optional[Path]:
    """Locate Firefox's places.sqlite inside the default profile directory."""
    if not profiles_dir or not profiles_dir.exists():
        return None
    for pattern in ("*.default-release", "*.default"):
        matches = sorted(profiles_dir.glob(pattern))
        if matches:
            candidate = matches[0] / "places.sqlite"
            if candidate.exists():
                return candidate
    return None


# ═══════════════════════════════════════════════════════════════════════════════
#  MASTER FILE  —  load / save / merge
# ═══════════════════════════════════════════════════════════════════════════════

# Master bookmark record shape:
# {
#   "url":         str,   # full URL
#   "title":       str,   # page title
#   "folder_path": str,   # slash-separated path, e.g. "Tech & Sysadmin/VPN & Networking"
#   "date_added":  str,   # ISO 8601 or empty string
#   "source":      str,   # browser name that originally contributed this entry
# }


def load_master() -> dict:
    if not MASTER_FILE.exists():
        return {"version": 1, "last_updated": "", "bookmarks": []}
    with open(MASTER_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_master(master: dict) -> None:
    MASTER_FILE.parent.mkdir(parents=True, exist_ok=True)
    master["last_updated"] = datetime.now(timezone.utc).isoformat()
    _backup_file(MASTER_FILE, "master")
    with open(MASTER_FILE, "w", encoding="utf-8") as f:
        json.dump(master, f, indent=2, ensure_ascii=False)
    print(f"   Master saved → {MASTER_FILE}")


def merge_into_master(master: dict, new_bookmarks: list[dict]) -> int:
    """Add new_bookmarks into master, deduplicating by normalized URL. Returns count added."""
    seen = {_normalize_url(b["url"]) for b in master["bookmarks"]}
    added = 0
    for bm in new_bookmarks:
        key = _normalize_url(bm["url"])
        if key not in seen:
            master["bookmarks"].append(bm)
            seen.add(key)
            added += 1
    return added


def _normalize_url(url: str) -> str:
    return url.rstrip("/").lower().strip()


# ═══════════════════════════════════════════════════════════════════════════════
#  CHROME / BRAVE / EDGE  (Chromium JSON format)
# ═══════════════════════════════════════════════════════════════════════════════

def pull_chromium(path: Optional[Path], browser: str) -> list[dict]:
    """Read bookmarks from a Chromium-based browser's JSON file."""
    if not path or not path.exists():
        print(f"  [{browser}] not found at {path} — skipping")
        return []

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    results: list[dict] = []

    def walk(node: dict, folder_path: str) -> None:
        if node.get("type") == "url":
            url = node.get("url", "")
            if url.startswith(("http://", "https://")):
                results.append({
                    "url":         url,
                    "title":       node.get("name", ""),
                    "folder_path": folder_path,
                    "date_added":  _chromium_ts(node.get("date_added", "0")),
                    "source":      browser,
                })
        elif node.get("type") == "folder":
            name = node.get("name", "Untitled")
            sub = f"{folder_path}/{name}" if folder_path else name
            for child in node.get("children", []):
                walk(child, sub)

    root_labels = {
        "bookmark_bar": "Bookmarks Bar",
        "other":        "Other Bookmarks",
        "synced":       "Mobile Bookmarks",
    }
    for key, label in root_labels.items():
        if key in data.get("roots", {}):
            for child in data["roots"][key].get("children", []):
                walk(child, label)

    print(f"  [{browser}] {len(results)} bookmarks read")
    return results


def push_chromium(path: Optional[Path], browser: str, master: dict) -> None:
    """Write master bookmarks back into a Chromium JSON file.
    ⚠  The browser must be fully closed before running this command."""
    if browser in SKIP_BROWSERS:
        print(f"  [{browser}] skipped (in SKIP_BROWSERS)")
        return
    if not path or not path.exists():
        print(f"  [{browser}] not found — skipping push")
        return

    _backup_file(path, browser)

    with open(path, encoding="utf-8") as f:
        existing = json.load(f)

    # Rebuild bookmark_bar from master; clear other/synced to avoid duplication
    existing["roots"]["bookmark_bar"]["children"] = _master_to_chromium_tree(master["bookmarks"])
    existing["roots"].setdefault("other", {})["children"] = []
    existing["roots"].setdefault("synced", {})["children"] = []

    # Chrome will recompute the checksum on next launch; clear it to avoid stale-checksum warning
    existing.pop("checksum", None)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(existing, f, separators=(",", ":"), ensure_ascii=False)

    print(f"  [{browser}] {len(master['bookmarks'])} bookmarks written")


def _master_to_chromium_tree(bookmarks: list[dict]) -> list:
    """Convert the flat master list to a Chromium nested folder tree."""
    root: dict = {}
    for bm in bookmarks:
        parts = [p for p in bm["folder_path"].split("/") if p] if bm.get("folder_path") else ["Other"]
        node = root
        for part in parts:
            node = node.setdefault(part, {"__items__": []})
        node["__items__"].append(bm)

    def build_chromium(node: dict, depth: int = 0) -> list:
        children = []
        for bm in node.get("__items__", []):
            children.append({
                "type":          "url",
                "name":          bm["title"],
                "url":           bm["url"],
                "date_added":    "0",
                "date_modified": "0",
                "guid":          "",
                "id":            "0",
                "meta_info":     {},
            })
        for key, sub in node.items():
            if key == "__items__":
                continue
            children.append({
                "type":          "folder",
                "name":          key,
                "children":      build_chromium(sub, depth + 1),
                "date_added":    "0",
                "date_modified": "0",
                "guid":          "",
                "id":            "0",
            })
        return children

    return build_chromium(root)


def _chromium_ts(micros_str: str) -> str:
    """Convert Chromium timestamp (µs since 1601-01-01) → ISO 8601."""
    try:
        micros = int(micros_str)
        unix_ts = (micros / 1_000_000) - 11_644_473_600
        return datetime.fromtimestamp(unix_ts, tz=timezone.utc).isoformat()
    except Exception:
        return ""


# ═══════════════════════════════════════════════════════════════════════════════
#  FIREFOX  (places.sqlite)
# ═══════════════════════════════════════════════════════════════════════════════

def pull_firefox(sqlite_path: Optional[Path]) -> list[dict]:
    """Read bookmarks from Firefox's places.sqlite via a safe read-only copy."""
    if not sqlite_path or not sqlite_path.exists():
        print("  [Firefox] places.sqlite not found — skipping")
        return []

    tmp = Path(tempfile.mktemp(suffix=".sqlite"))
    shutil.copy2(sqlite_path, tmp)

    try:
        conn = sqlite3.connect(f"file:{tmp}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        cur.execute("""
            WITH RECURSIVE bpath(id, title, parent, fk, path) AS (
                SELECT b.id, b.title, b.parent, b.fk,
                       COALESCE(b.title, '') AS path
                FROM   moz_bookmarks b
                WHERE  b.parent IN (
                    SELECT id FROM moz_bookmarks
                    WHERE  title IN ('menu','toolbar','unfiled','mobile')
                )
                UNION ALL
                SELECT b.id, b.title, b.parent, b.fk,
                       CASE
                           WHEN bp.path = '' THEN COALESCE(b.title,'')
                           ELSE bp.path || '/' || COALESCE(b.title,'')
                       END
                FROM   moz_bookmarks b
                JOIN   bpath bp ON b.parent = bp.id
            )
            SELECT bp.path  AS folder_path,
                   p.url,
                   COALESCE(bp.title, p.title, '') AS title,
                   datetime(b2.dateAdded/1000000,'unixepoch') AS date_added
            FROM   bpath bp
            JOIN   moz_bookmarks b2 ON b2.id = bp.id
            JOIN   moz_places p    ON b2.fk  = p.id
            WHERE  b2.type = 1
              AND  b2.fk   IS NOT NULL
              AND  p.url NOT LIKE 'place:%'
              AND  p.url NOT LIKE 'javascript:%'
            ORDER  BY b2.position
        """)

        results = []
        for row in cur.fetchall():
            url = row["url"]
            if not url or not url.startswith(("http://", "https://")):
                continue
            raw_path = row["folder_path"] or ""
            parts = raw_path.rsplit("/", 1)
            folder = parts[0] if len(parts) > 1 else "Firefox"

            results.append({
                "url":         url,
                "title":       row["title"] or "",
                "folder_path": folder,
                "date_added":  row["date_added"] or "",
                "source":      "Firefox",
            })

        conn.close()
        print(f"  [Firefox] {len(results)} bookmarks read")
        return results

    except Exception as e:
        print(f"  [Firefox] error reading SQLite: {e}")
        return []
    finally:
        tmp.unlink(missing_ok=True)


# ═══════════════════════════════════════════════════════════════════════════════
#  SAFARI / NETSCAPE HTML  (import & export)
# ═══════════════════════════════════════════════════════════════════════════════

def pull_safari_html(html_path: Path) -> list[dict]:
    """Parse a Netscape-format HTML bookmark file (Safari export or any browser export)."""
    if not html_path.exists():
        print(f"  [Safari HTML] file not found: {html_path}")
        return []

    with open(html_path, encoding="utf-8", errors="replace") as f:
        soup = BeautifulSoup(f.read(), "lxml")

    results: list[dict] = []

    def walk_dl(dl_tag, folder_path: str = "") -> None:
        for dt in dl_tag.find_all("dt", recursive=False):
            a = dt.find("a")
            h3 = dt.find("h3")
            if a and a.get("href", "").startswith(("http://", "https://")):
                results.append({
                    "url":         a["href"],
                    "title":       a.get_text(strip=True),
                    "folder_path": folder_path,
                    "date_added":  "",
                    "source":      "Safari",
                })
            elif h3:
                sub_dl = dt.find_next_sibling("dl")
                folder_name = h3.get_text(strip=True)
                new_path = f"{folder_path}/{folder_name}" if folder_path else folder_name
                if sub_dl:
                    walk_dl(sub_dl, new_path)

    top_dl = soup.find("dl")
    if top_dl:
        walk_dl(top_dl)

    print(f"  [Safari HTML] {len(results)} bookmarks parsed from {html_path.name}")
    return results


def export_html(master: dict, output_path: Path) -> None:
    """Write master as Netscape HTML — importable by Safari, Firefox, Chrome, Edge, Brave."""
    tree: dict = {}
    for bm in master["bookmarks"]:
        parts = [p for p in bm["folder_path"].split("/") if p] if bm.get("folder_path") else ["Other"]
        node = tree
        for part in parts:
            node = node.setdefault(part, {"__items__": []})
        node["__items__"].append(bm)

    lines = [
        "<!DOCTYPE NETSCAPE-Bookmark-file-1>",
        '<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">',
        "<TITLE>Bookmarks</TITLE>",
        "<H1>Bookmarks</H1>",
        "<DL><p>",
    ]

    def _esc(s: str) -> str:
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

    def render(node: dict, depth: int = 1) -> None:
        indent = "    " * depth
        for bm in node.get("__items__", []):
            lines.append(f'{indent}<DT><A HREF="{bm["url"]}">{_esc(bm["title"])}</A>')
        for key, sub in node.items():
            if key == "__items__":
                continue
            lines.append(f"{indent}<DT><H3>{_esc(key)}</H3>")
            lines.append(f"{indent}<DL><p>")
            render(sub, depth + 1)
            lines.append(f"{indent}</DL><p>")

    render(tree)
    lines.append("</DL><p>")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"  HTML export → {output_path}")


# ═══════════════════════════════════════════════════════════════════════════════
#  UTILITY
# ═══════════════════════════════════════════════════════════════════════════════

def _backup_file(path: Path, label: str) -> None:
    """Copy a file to BACKUP_DIR before any write operation."""
    if not path or not path.exists():
        return
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = BACKUP_DIR / f"{label}_{ts}{path.suffix}"
    shutil.copy2(path, dest)


# ═══════════════════════════════════════════════════════════════════════════════
#  COMMANDS
# ═══════════════════════════════════════════════════════════════════════════════

def cmd_pull() -> None:
    """Pull from all available browsers on this machine and merge into master."""
    print("\n📥  Pulling bookmarks from all browsers…")
    master = load_master()
    paths = get_browser_paths()
    total_added = 0

    for browser, path in paths.items():
        if browser == "Firefox":
            bms = pull_firefox(path)
        else:
            bms = pull_chromium(path, browser)
        added = merge_into_master(master, bms)
        total_added += added
        if bms:
            print(f"     → {added} new URLs added to master")

    save_master(master)
    print(f"\n✅  Done. {total_added} new bookmarks added.")
    print(f"    Master total: {len(master['bookmarks'])} bookmarks.")


def cmd_push() -> None:
    """Push master to Chromium browsers on this machine + generate HTML export."""
    print("\n📤  Pushing bookmarks to browsers…")
    print("    ⚠  Make sure Chrome, Brave, and Edge are fully closed!\n")
    master = load_master()

    if not master["bookmarks"]:
        print("Master file is empty or missing. Run `pull` first.")
        return

    paths = get_browser_paths()
    for browser in ("Chrome", "Brave", "Edge"):
        push_chromium(paths.get(browser), browser, master)

    html_out = MASTER_FILE.parent / "bookmarks_export.html"
    export_html(master, html_out)

    print(f"\n✅  Done.")
    print(f"    HTML export: {html_out}")
    print("    → Safari:  File → Import From → Bookmarks HTML File")
    print("    → Firefox: Bookmarks ☰ → Manage Bookmarks → Import and Backup → Import Bookmarks from HTML")


def cmd_safari_in(html_file: str) -> None:
    """Import a Safari HTML export into the master file."""
    print(f"\n📥  Importing Safari HTML: {html_file}")
    master = load_master()
    bms = pull_safari_html(Path(html_file))
    added = merge_into_master(master, bms)
    save_master(master)
    print(f"\n✅  Done. {added} new bookmarks added. Master total: {len(master['bookmarks'])}.")


def cmd_safari_out(output_file: Optional[str] = None) -> None:
    """Export master as Netscape HTML ready for Safari / Firefox import."""
    master = load_master()
    if not master["bookmarks"]:
        print("Master file is empty. Nothing to export.")
        return
    out = Path(output_file) if output_file else MASTER_FILE.parent / "bookmarks_export.html"
    export_html(master, out)
    print(f"\n✅  HTML ready: {out}")


def cmd_dedupe() -> None:
    """Remove duplicate URLs from master (keeps first occurrence)."""
    print("\n🧹  Deduplicating master…")
    master = load_master()
    before = len(master["bookmarks"])
    seen: set[str] = set()
    deduped = []
    for bm in master["bookmarks"]:
        key = _normalize_url(bm["url"])
        if key not in seen:
            deduped.append(bm)
            seen.add(key)
    master["bookmarks"] = deduped
    removed = before - len(deduped)
    save_master(master)
    print(f"\n✅  Removed {removed} duplicates. Master total: {len(deduped)}.")


def cmd_status() -> None:
    """Show statistics about the master file."""
    master = load_master()
    bms = master["bookmarks"]
    print(f"\n📊  Master bookmark status")
    print(f"    File:         {MASTER_FILE}")
    print(f"    Last updated: {master.get('last_updated', 'never')}")
    print(f"    Total:        {len(bms)} bookmarks")

    if not bms:
        return

    folders: dict[str, int] = {}
    sources: dict[str, int] = {}
    for bm in bms:
        top = bm["folder_path"].split("/")[0] if bm.get("folder_path") else "(none)"
        folders[top] = folders.get(top, 0) + 1
        src = bm.get("source", "unknown")
        sources[src] = sources.get(src, 0) + 1

    print(f"\n    By source browser:")
    for src, cnt in sorted(sources.items(), key=lambda x: -x[1]):
        print(f"      {src:<20} {cnt}")

    print(f"\n    By top-level folder:")
    for folder, cnt in sorted(folders.items(), key=lambda x: -x[1]):
        print(f"      {folder:<40} {cnt}")


def cmd_help() -> None:
    print(__doc__)


def cmd_version() -> None:
    print(f"bookmark_sync {__version__}")


# ═══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

COMMANDS: dict[str, tuple] = {
    "pull":       (cmd_pull,       "Merge all browsers on this machine → master JSON"),
    "push":       (cmd_push,       "Push master JSON → Chromium browsers + HTML export"),
    "safari-in":  (cmd_safari_in,  "Import Safari HTML export → master  (arg: path to HTML)"),
    "safari-out": (cmd_safari_out, "Export master → HTML file         (arg: output path, optional)"),
    "dedupe":     (cmd_dedupe,     "Remove duplicate URLs from master"),
    "status":     (cmd_status,     "Show master file statistics"),
    "version":    (cmd_version,    "Print version number"),
    "help":       (cmd_help,       "Show this help message"),
}

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"
    arg = sys.argv[2] if len(sys.argv) > 2 else None

    if cmd not in COMMANDS:
        print(f"Unknown command: '{cmd}'")
        print(f"Available: {', '.join(COMMANDS)}")
        sys.exit(1)

    fn, _ = COMMANDS[cmd]
    if arg:
        fn(arg)
    else:
        fn()
