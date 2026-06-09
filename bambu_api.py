"""
bambu_api.py - write layer for the Smokeforge print farm.

Sniffs a JWT from the Farm Manager client's own requests (Authorization header
via DevTools) and uses it to POST to the local server.  The cert is held by
the client's cuckoo proxy; we POST through requests with verify=False.

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
    # package name -> import name (where they differ)
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
JWT_MAX_AGE = 6 * 24 * 3600  # treat token as stale after 6 days

_jwt_cache: dict = {}  # keys: "token", "captured_at"


def _sniff_jwt(timeout: int = 20) -> str | None:
    """
    Open a DevTools session and wait for any request that carries an
    Authorization: Bearer header.  Returns the token string or None.
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
    # Also ask for request headers to be captured
    send("Network.setRequestInterception", {"patterns": []})

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
            # responseReceived carries the request headers too
            if method == "Network.responseReceived":
                req_headers = (
                    msg.get("params", {})
                    .get("response", {})
                    .get("requestHeaders", {})
                )
                auth = req_headers.get("Authorization") or req_headers.get("authorization")
                if auth and auth.startswith("Bearer "):
                    token = auth[len("Bearer "):]
                    break
            # requestWillBeSent also contains request headers
            elif method == "Network.requestWillBeSent":
                req_headers = (
                    msg.get("params", {})
                    .get("request", {})
                    .get("headers", {})
                )
                auth = req_headers.get("Authorization") or req_headers.get("authorization")
                if auth and auth.startswith("Bearer "):
                    token = auth[len("Bearer "):]
                    break
    finally:
        ws.close()

    return token


def _get_jwt() -> str:
    """Return a valid JWT, re-sniffing if cache is empty or stale."""
    now = time.time()
    if _jwt_cache.get("token") and (now - _jwt_cache.get("captured_at", 0)) < JWT_MAX_AGE:
        return _jwt_cache["token"]

    ensure_client(verbose=False)
    token = _sniff_jwt()
    if not token:
        raise RuntimeError(
            "Could not capture a JWT from the Farm Manager client. "
            "Ensure the client is open and making requests."
        )
    _jwt_cache["token"] = token
    _jwt_cache["captured_at"] = now
    return token


def _session() -> tuple[requests.Session, dict]:
    """Return a configured requests.Session and auth headers."""
    jwt = _get_jwt()
    sess = requests.Session()
    headers = {**HEADERS_FIXED, "Authorization": f"Bearer {jwt}"}
    return sess, headers


def post_task(
    dev_id: str,
    f3mf_id: str,
    task_name: str,
    ams_mapping: list[dict],
) -> dict:
    """
    Create a print job.

    ams_mapping: ordered list of {ams_id, slot_id} dicts, one per filament
    index in the model.  This becomes ams_mapping2 inside device_pool2.
    """
    sess, headers = _session()
    payload = {
        "task_print_model": 1,
        "queue_model_cnt": 0,
        "device_pool": [dev_id],
        "device_pool2": [
            {"dev_id": dev_id, "ams_mapping2": ams_mapping}
        ],
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
    resp = sess.post(f"{BASE_URL}/task", json=payload, headers=headers, verify=False)
    resp.raise_for_status()
    return resp.json()


def opt_command(dev_id: str, opt_name: str) -> dict:
    """
    Send a device opt command (pause / resume / stop / bed_clean / …).
    Wraps the name in the standard {"opt": "<name>"} envelope.
    """
    sess, headers = _session()
    payload = {"opt": opt_name}
    resp = sess.post(
        f"{BASE_URL}/device/{dev_id}/opt",
        json=payload,
        headers=headers,
        verify=False,
    )
    resp.raise_for_status()
    return resp.json()


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
