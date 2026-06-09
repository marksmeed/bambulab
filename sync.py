"""
sync.py - background sync loop for the Smokeforge print farm.

Keeps the SQLite DB in sync with the live Farm Manager server by passively
observing the client's API traffic via Chrome DevTools Protocol.

Syncs:
  - /devices2      -> printers / ams_units / slots  (every 15 s)
  - /file/f3mffolder + /file/f3mf?folder_id=<id>
                   -> models table                   (every 10 min)

Usage:
    python sync.py           # continuous loop
    python sync.py --once    # single pass then exit
"""

import argparse
import json
import sqlite3
import time
from pathlib import Path

import websocket

from bambu_client import ensure_client, get_page_ws
from db import init_db, connect, parse_and_sync

DB_PATH = "farm.db"
DEVICES_INTERVAL = 15       # seconds
MODELS_INTERVAL = 600       # seconds (10 min)

# The Farm Manager client polls /devices2 on its own cycle (~30 s).  We need
# to wait long enough to catch at least one cycle after connecting.
DEVICES_CAPTURE_TIMEOUT = 35   # seconds

# /file/f3mffolder is only requested when the user navigates to the Files
# section of the UI.  We wait up to this long and prompt the user to click
# there if it isn't captured quickly.
MODELS_CAPTURE_TIMEOUT = 60    # seconds


# ---------------------------------------------------------------------------
# Generic DevTools capture helper
# ---------------------------------------------------------------------------

def _capture_url(url_fragment: str, timeout: int = 20) -> dict | None:
    """
    Wait for a response whose URL contains url_fragment, return its parsed
    JSON body.  Opens a fresh DevTools websocket connection each call.
    """
    ws_url = get_page_ws()
    if not ws_url:
        return None

    ws = websocket.create_connection(ws_url, max_size=None)
    mid = [0]

    def send(method, params=None):
        mid[0] += 1
        ws.send(json.dumps({"id": mid[0], "method": method, "params": params or {}}))

    send("Network.enable")
    ws.settimeout(timeout + 2)
    deadline = time.time() + timeout
    body = None
    pending = {}

    try:
        while time.time() < deadline and body is None:
            try:
                msg = json.loads(ws.recv())
            except Exception:
                break
            method = msg.get("method", "")
            if method == "Network.responseReceived":
                url = msg["params"]["response"]["url"]
                if url_fragment in url:
                    pending[msg["params"]["requestId"]] = url
            elif method == "Network.loadingFinished":
                req_id = msg["params"]["requestId"]
                if req_id in pending:
                    send("Network.getResponseBody", {"requestId": req_id})
                    while True:
                        rep = json.loads(ws.recv())
                        if "result" in rep and "body" in rep.get("result", {}):
                            body = rep["result"]["body"]
                            break
    finally:
        ws.close()

    return json.loads(body) if body else None


# ---------------------------------------------------------------------------
# Device / filament sync
# ---------------------------------------------------------------------------

def sync_devices_once() -> bool:
    data = _capture_url("/devices2", timeout=DEVICES_CAPTURE_TIMEOUT)
    if not data:
        print(f"[{_ts()}] sync_devices: no data captured "
              f"(waited {DEVICES_CAPTURE_TIMEOUT}s — is the client on the Printers page?)")
        return False
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
    print(f"[{_ts()}] sync_models: waiting up to {MODELS_CAPTURE_TIMEOUT}s for "
          f"/file/f3mffolder — navigate to the Files section in the Farm Manager UI now ...")
    folders_data = _capture_url("/file/f3mffolder", timeout=MODELS_CAPTURE_TIMEOUT)
    if not folders_data:
        print(f"[{_ts()}] sync_models: timed out — no /file/f3mffolder request observed. "
              f"Open the Files tab in the Farm Manager client and re-run.")
        return False

    folders = folders_data if isinstance(folders_data, list) else folders_data.get("folders", [])
    total = 0
    con = connect(DB_PATH)
    try:
        with con:
            for folder in folders:
                folder_id = folder.get("folder_id") or folder.get("id") or str(folder)
                files_data = _capture_url(f"/file/f3mf?folder_id={folder_id}")
                if not files_data:
                    continue
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
# Helpers
# ---------------------------------------------------------------------------

def _ts() -> str:
    return time.strftime("%H:%M:%S")


def _ensure_db() -> None:
    if not Path(DB_PATH).exists():
        print(f"[{_ts()}] Initialising {DB_PATH} ...")
        init_db(DB_PATH)


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
                sync_devices_once()
                last_devices = time.time()
            if now - last_models >= MODELS_INTERVAL:
                sync_models_once()
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
