"""
sync.py - background sync loop for the Smokeforge print farm.

Makes direct HTTP requests to the Farm Manager API (same approach as
bambu_api.py) to keep the SQLite DB in sync.  JWT is sniffed once from
the running client via DevTools and then reused.

Syncs:
  - /devices2                          -> printers / ams_units / slots  (every 15 s)
  - /file/f3mffolder + /file/f3mf      -> models table                  (every 10 min)

Usage:
    python sync.py           # continuous loop
    python sync.py --once    # single pass then exit
"""

import argparse
import importlib
import sqlite3
import subprocess
import sys
import time
from pathlib import Path


def _ensure_deps():
    # package name -> import name (where they differ)
    deps = {"requests": "requests", "urllib3": "urllib3"}
    for pkg, imp in deps.items():
        try:
            importlib.import_module(imp)
        except ImportError:
            print(f"Installing {pkg} ...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])


_ensure_deps()

import requests
import urllib3

from bambu_api import _get_jwt, BASE_URL, HEADERS_FIXED
from bambu_client import ensure_client
from db import init_db, connect, parse_and_sync

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

DB_PATH = "farm.db"
DEVICES_INTERVAL = 15    # seconds
MODELS_INTERVAL = 600    # seconds (10 min)


def _session() -> tuple[requests.Session, dict]:
    jwt = _get_jwt()
    sess = requests.Session()
    headers = {**HEADERS_FIXED, "Authorization": f"Bearer {jwt}"}
    return sess, headers


def _ts() -> str:
    return time.strftime("%H:%M:%S")


def _ensure_db() -> None:
    if not Path(DB_PATH).exists():
        print(f"[{_ts()}] Initialising {DB_PATH} ...")
        init_db(DB_PATH)


# ---------------------------------------------------------------------------
# Device / filament sync
# ---------------------------------------------------------------------------

def sync_devices_once() -> bool:
    sess, headers = _session()
    resp = sess.get(
        f"{BASE_URL}/devices2",
        params={"use_lite": "true"},
        headers=headers,
        verify=False,
    )
    resp.raise_for_status()
    data = resp.json()
    parse_and_sync(data, path=DB_PATH)
    device_count = len(data.get("devices", []))
    print(f"[{_ts()}] sync_devices: synced {device_count} printer(s)")
    return True


# ---------------------------------------------------------------------------
# 3MF library sync
# ---------------------------------------------------------------------------

def upsert_model(con: sqlite3.Connection, f3mf_id: str, name: str, folder_id: str) -> None:
    con.execute(
        """
        INSERT INTO models (f3mf_id, name, folder_id, updated_at)
        VALUES (?, ?, ?, datetime('now'))
        ON CONFLICT(f3mf_id) DO UPDATE SET
            name       = excluded.name,
            folder_id  = excluded.folder_id,
            updated_at = datetime('now')
        """,
        (f3mf_id, name, folder_id),
    )


def sync_models_once() -> bool:
    sess, headers = _session()

    resp = sess.get(f"{BASE_URL}/file/f3mffolder", headers=headers, verify=False)
    resp.raise_for_status()
    folders_data = resp.json()
    folders = folders_data if isinstance(folders_data, list) else folders_data.get("folders", [])

    total = 0
    con = connect(DB_PATH)
    try:
        with con:
            for folder in folders:
                folder_id = folder.get("folder_id") or folder.get("id") or str(folder)
                r = sess.get(
                    f"{BASE_URL}/file/f3mf",
                    params={"folder_id": folder_id},
                    headers=headers,
                    verify=False,
                )
                r.raise_for_status()
                files_data = r.json()
                files = files_data if isinstance(files_data, list) else files_data.get("files", [])
                for f in files:
                    f3mf_id = f.get("f3mf_id") or f.get("id")
                    name = f.get("name") or f.get("title") or f3mf_id
                    if f3mf_id:
                        upsert_model(con, f3mf_id, name, folder_id)
                        total += 1
    finally:
        con.close()

    print(f"[{_ts()}] sync_models: upserted {total} model(s) across {len(folders)} folder(s)")
    return True


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run_loop() -> None:
    _ensure_db()
    ensure_client(verbose=True)

    last_devices = 0.0
    last_models = 0.0

    print(f"[{_ts()}] Sync loop started (devices every {DEVICES_INTERVAL}s, "
          f"models every {MODELS_INTERVAL}s).  Ctrl+C to stop.")
    try:
        while True:
            now = time.time()
            if now - last_devices >= DEVICES_INTERVAL:
                try:
                    sync_devices_once()
                except Exception as e:
                    print(f"[{_ts()}] sync_devices error: {e}")
                last_devices = time.time()
            if now - last_models >= MODELS_INTERVAL:
                try:
                    sync_models_once()
                except Exception as e:
                    print(f"[{_ts()}] sync_models error: {e}")
                last_models = time.time()
            time.sleep(1)
    except KeyboardInterrupt:
        print(f"\n[{_ts()}] Sync loop stopped.")


def run_once() -> None:
    _ensure_db()
    ensure_client(verbose=True)
    sync_devices_once()
    sync_models_once()
    print(f"[{_ts()}] Single-pass complete.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Smokeforge farm sync daemon")
    parser.add_argument("--once", action="store_true",
                        help="Run a single sync pass and exit")
    args = parser.parse_args()

    if args.once:
        run_once()
    else:
        run_loop()
