"""
bambu_api.py - write layer for the Smokeforge print farm.

Sniffs a JWT from the Farm Manager client's own requests (Authorization header
via DevTools — same passive-capture pattern as bambu_filament.py), caches it,
and uses it to POST write commands to the local server.

Connection method: ensure_client() launches the Electron client with debug
flags if needed; all data access is via the Chrome DevTools Protocol on
port 9222.  No certificates, no direct TLS, no activation risk.

Usage:
    from bambu_api import post_task, opt_command
    post_task(dev_id, f3mf_id, "ORD-1234", [{"ams_id": 0, "slot_id": 2}])
    opt_command(dev_id, "pause")

    python bambu_api.py --opt <dev_id> <opt_name>
"""

import importlib
import json
import subprocess
import sys
import time


def _ensure_deps():
    deps = {"requests": "requests", "urllib3": "urllib3", "websocket-client": "websocket"}
    for pkg, imp in deps.items():
        try:
            importlib.import_module(imp)
        except ImportError:
            print(f"Installing {pkg} ...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])


_ensure_deps()

import requests
import urllib3
import websocket

from bambu_client import ensure_client, get_page_ws

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = "https://192.168.68.78:8888"
HEADERS_FIXED = {"x-bbl-sec-ver": "1"}
JWT_MAX_AGE = 6 * 24 * 3600  # sniffed JWTs expire ~7 days; re-sniff after 6

_jwt_cache: dict = {}  # keys: "token", "captured_at"


# ---------------------------------------------------------------------------
# JWT — sniff from the client's own requests via DevTools
# ---------------------------------------------------------------------------

def _sniff_jwt(timeout: int = 35) -> str | None:
    """
    Open a DevTools session and wait for any request that carries an
    Authorization: Bearer header.  The client polls every ~30 s so 35 s
    is enough to reliably catch at least one cycle.
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
    token = None

    try:
        while time.time() < deadline and token is None:
            try:
                msg = json.loads(ws.recv())
            except Exception:
                break
            method = msg.get("method", "")
            if method == "Network.requestWillBeSent":
                hdrs = msg.get("params", {}).get("request", {}).get("headers", {})
            elif method == "Network.responseReceived":
                hdrs = msg.get("params", {}).get("response", {}).get("requestHeaders", {})
            else:
                continue
            auth = hdrs.get("Authorization") or hdrs.get("authorization", "")
            if auth.startswith("Bearer "):
                token = auth[len("Bearer "):]
    finally:
        ws.close()

    return token


def _get_jwt() -> str:
    """Return a cached JWT, re-sniffing if absent or older than 6 days."""
    now = time.time()
    if _jwt_cache.get("token") and (now - _jwt_cache.get("captured_at", 0)) < JWT_MAX_AGE:
        return _jwt_cache["token"]

    ensure_client(verbose=False)
    token = _sniff_jwt()
    if not token:
        raise RuntimeError(
            "Could not capture a JWT. "
            "Ensure the Farm Manager client is open on the Printers page."
        )
    _jwt_cache["token"] = token
    _jwt_cache["captured_at"] = now
    return token


# ---------------------------------------------------------------------------
# Write commands
# ---------------------------------------------------------------------------

def _post(path: str, payload: dict) -> dict:
    jwt = _get_jwt()
    headers = {**HEADERS_FIXED, "Authorization": f"Bearer {jwt}"}
    sess = requests.Session()
    resp = sess.post(f"{BASE_URL}{path}", json=payload, headers=headers,
                     verify=False, timeout=30)
    resp.raise_for_status()
    return resp.json()


def post_task(dev_id: str, f3mf_id: str, task_name: str,
              ams_mapping: list[dict]) -> dict:
    """
    Create a print job.

    ams_mapping: ordered list of {ams_id, slot_id} dicts, one per filament
    index in the model (becomes ams_mapping2 inside device_pool2).
    """
    payload = {
        "task_print_model": 1,
        "queue_model_cnt": 0,
        "device_pool": [dev_id],
        "device_pool2": [{"dev_id": dev_id, "ams_mapping2": ams_mapping}],
        "task_name": task_name,
        "print_option": {
            "auto_bed_leveling": True,
            "flow_dynamic_calibration": True,
            "timelapse": False,
            "bed_leveling_mode": 2,
            "flow_dynamic_cali_mode": 2,
            "nozzle_offset_cali_mode": 2,
        },
        "f3mf_id": f3mf_id,
        "ams_mapping2": [],
    }
    return _post("/task", payload)


def opt_command(dev_id: str, opt_name: str) -> dict:
    """
    Send a device opt command — pause / resume / stop / bed_clean / …
    """
    return _post(f"/device/{dev_id}/opt", {"opt": opt_name})


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    args = sys.argv[1:]
    if "--opt" in args:
        idx = args.index("--opt")
        if idx + 2 >= len(args):
            print("Usage: python bambu_api.py --opt <dev_id> <opt_name>")
            sys.exit(1)
        _dev_id = args[idx + 1]
        _opt_name = args[idx + 2]
        print(f"Sending opt '{_opt_name}' to {_dev_id} ...")
        result = opt_command(_dev_id, _opt_name)
        print(json.dumps(result, indent=2))
    else:
        print("Usage: python bambu_api.py --opt <dev_id> <opt_name>")
        sys.exit(1)
