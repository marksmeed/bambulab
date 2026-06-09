"""
investigate_cuckoo.py - figure out HOW the Farm Manager client reaches the
server, so we can route our own write requests the same way.

Background: a direct Python request to https://192.168.68.78:8888 fails mutual
TLS (the server demands a client cert we don't have).  The client instead
makes PLAIN http://192.168.68.78:8888 requests that Electron intercepts and
routes through a local "cuckoo" proxy, which performs the real mTLS HTTPS to
the server.  To write, we must send our requests through that same proxy.

What this script does:
  [1] Passively inspects a real :8888 request the client makes (via DevTools).
  [2] Lists local TCP listeners and maps each to its owning process.
  [3] ACTIVELY probes each local port with a read-only GET /captain, routed
      through that port as an HTTP proxy (and also tried directly), to find
      which port is cuckoo.  /captain is the server health endpoint - safe.

Run it on the Windows box with the client open on the Printers page:
    python investigate_cuckoo.py
"""

import json
import re
import subprocess
import sys
import time

from bambu_client import ensure_client, get_page_ws

try:
    import websocket
except ImportError:
    print("Installing websocket-client ...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "websocket-client"])
    import websocket

try:
    import requests
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except ImportError:
    print("Installing requests ...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests"])
    import requests
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

API_HOST_HINT = "192.168.68.78"          # the server we ultimately want to reach
API_HTTP = "http://192.168.68.78:8888"   # how the client addresses it
PROBE_PATH = "/captain"                  # read-only health endpoint


# ---------------------------------------------------------------------------
# 1. Inspect a real API request via DevTools
# ---------------------------------------------------------------------------

def inspect_api_request(timeout: int = 40) -> dict | None:
    """
    Capture the first response to an :8888 API call the client makes and
    return its connection details (remote IP/port, protocol, headers, url).
    """
    ensure_client(verbose=False)
    ws_url = get_page_ws()
    if not ws_url:
        print("Could not get a DevTools page websocket. Is the client open?")
        return None

    ws = websocket.create_connection(ws_url, max_size=None)
    mid = [0]

    def send(method, params=None):
        mid[0] += 1
        ws.send(json.dumps({"id": mid[0], "method": method, "params": params or {}}))

    send("Network.enable")
    ws.settimeout(timeout + 2)
    deadline = time.time() + timeout
    found = None

    try:
        while time.time() < deadline and found is None:
            try:
                msg = json.loads(ws.recv())
            except Exception:
                break
            if msg.get("method") != "Network.responseReceived":
                continue
            resp = msg["params"]["response"]
            url = resp.get("url", "")
            if ":8888" in url or API_HOST_HINT in url:
                found = {
                    "url": url,
                    "scheme": url.split(":", 1)[0],
                    "remoteIPAddress": resp.get("remoteIPAddress"),
                    "remotePort": resp.get("remotePort"),
                    "protocol": resp.get("protocol"),
                    "fromProxy": resp.get("fromProxy"),
                    "requestHeaders": resp.get("requestHeaders", {}),
                }
    finally:
        ws.close()

    return found


# ---------------------------------------------------------------------------
# 2. Enumerate local listeners + map to processes (Windows)
# ---------------------------------------------------------------------------

def name_for_pid(pid: str) -> str:
    try:
        out = subprocess.check_output(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            text=True, stderr=subprocess.DEVNULL)
        parts = out.strip().split('","')
        if parts and parts[0]:
            return parts[0].strip('"')
    except Exception:
        pass
    return "?"


def local_listeners() -> list[tuple[str, str, str]]:
    """Return [(port, pid, process_name), ...] for 127.0.0.1 TCP listeners."""
    try:
        out = subprocess.check_output(
            ["netstat", "-ano", "-p", "TCP"], text=True, stderr=subprocess.DEVNULL)
    except Exception as e:
        print(f"  (netstat failed: {e})")
        return []
    rows = []
    seen = set()
    for ln in out.splitlines():
        if "LISTENING" not in ln or "127.0.0.1" not in ln:
            continue
        m = re.search(r"127\.0\.0\.1:(\d+)\s+\S+\s+LISTENING\s+(\d+)", ln)
        if not m:
            continue
        port, pid = m.group(1), m.group(2)
        if port in seen:
            continue
        seen.add(port)
        rows.append((port, pid, name_for_pid(pid)))
    return rows


# ---------------------------------------------------------------------------
# 3. Actively probe candidate ports for the cuckoo route
# ---------------------------------------------------------------------------

def _auth_headers() -> dict:
    """Best-effort JWT for the probe (/captain may not need it, but be safe)."""
    headers = {"x-bbl-sec-ver": "1"}
    try:
        from bambu_api import _get_jwt
        headers["Authorization"] = f"Bearer {_get_jwt()}"
    except Exception as e:
        print(f"  (could not sniff a JWT for the probe: {e})")
    return headers


def _summarise(resp) -> str:
    body = (resp.text or "")[:160].replace("\n", " ")
    return f"HTTP {resp.status_code}  body[:160]={body!r}"


def probe_ports(ports: list[str]) -> str | None:
    """
    For each candidate port, try reaching GET {API_HTTP}{PROBE_PATH} two ways:
      a) using the port as an HTTP forward proxy
      b) talking to the port directly (reverse-proxy style)
    Return the first port that yields a healthy response, else None.
    """
    headers = _auth_headers()
    winner = None

    print(f"\n    Target: GET {API_HTTP}{PROBE_PATH}")
    print("    (a) = port used as HTTP proxy   (b) = direct to 127.0.0.1:port\n")

    for port in ports:
        proxies = {"http": f"http://127.0.0.1:{port}",
                   "https": f"http://127.0.0.1:{port}"}
        # (a) as a forward proxy
        try:
            r = requests.get(f"{API_HTTP}{PROBE_PATH}", headers=headers,
                             proxies=proxies, timeout=6, verify=False)
            print(f"    port {port} (a) proxy : {_summarise(r)}")
            if r.ok and r.text.strip().startswith(("{", "[")):
                winner = winner or ("proxy", port)
        except Exception as e:
            print(f"    port {port} (a) proxy : {type(e).__name__}: {str(e)[:80]}")
        # (b) direct to the port
        try:
            r = requests.get(f"http://127.0.0.1:{port}{PROBE_PATH}", headers=headers,
                             timeout=6, verify=False)
            print(f"    port {port} (b) direct: {_summarise(r)}")
            if r.ok and r.text.strip().startswith(("{", "[")):
                winner = winner or ("direct", port)
        except Exception as e:
            print(f"    port {port} (b) direct: {type(e).__name__}: {str(e)[:80]}")

    # also a baseline: plain http straight to the server (no proxy)
    try:
        r = requests.get(f"{API_HTTP}{PROBE_PATH}", headers=headers,
                         timeout=6, verify=False)
        print(f"\n    baseline no-proxy http: {_summarise(r)}")
        if r.ok and r.text.strip().startswith(("{", "[")):
            winner = winner or ("noproxy-http", "-")
    except Exception as e:
        print(f"\n    baseline no-proxy http: {type(e).__name__}: {str(e)[:80]}")

    return winner


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def main():
    print("=" * 70)
    print("CUCKOO INVESTIGATION")
    print("=" * 70)

    print("\n[1] Inspecting a real API request the client makes ...")
    info = inspect_api_request()
    if not info:
        print("    No :8888 API request observed. Make sure the client is open")
        print("    on the Printers page (it polls every ~30s). Stopping.")
        return
    print(f"    url            : {info['url']}")
    print(f"    scheme         : {info['scheme']}")
    print(f"    remoteIPAddress: {info['remoteIPAddress']}")
    print(f"    remotePort     : {info['remotePort']}")
    print(f"    protocol       : {info['protocol']}")
    print(f"    fromProxy      : {info['fromProxy']}")

    print("\n[2] Local TCP listeners on 127.0.0.1:")
    listeners = local_listeners()
    for port, pid, name in listeners:
        print(f"    127.0.0.1:{port:<6}  pid {pid:<6}  {name}")

    print("\n[3] Probing candidate ports for the cuckoo route ...")
    ports = [p for p, _, _ in listeners if p != "9222"]  # skip the debug port
    winner = probe_ports(ports)

    print("\n" + "=" * 70)
    print("CONCLUSION")
    print("=" * 70)
    if winner:
        mode, port = winner
        if mode == "proxy":
            print(f"""
    Cuckoo is the HTTP proxy on 127.0.0.1:{port}.
    Set this at the top of bambu_api.py and writes will work:

        CUCKOO_PROXY = {{"http":  "http://127.0.0.1:{port}",
                        "https": "http://127.0.0.1:{port}"}}
        BASE_URL = "http://192.168.68.78:8888"   # note: http, like the client
""")
        elif mode == "direct":
            print(f"""
    The server is reachable directly at 127.0.0.1:{port} (reverse proxy).
    Set this at the top of bambu_api.py:

        BASE_URL = "http://127.0.0.1:{port}"
        CUCKOO_PROXY = None
""")
        else:  # noproxy-http
            print(f"""
    Plain HTTP straight to {API_HTTP} works (no proxy needed)!
    Set at the top of bambu_api.py:

        BASE_URL = "http://192.168.68.78:8888"   # http, not https
        CUCKOO_PROXY = None
""")
    else:
        print("""
    None of the probed ports returned a healthy /captain.  Paste this whole
    output back and we'll pick the next approach (Windows curl via cert
    thumbprint, or driving the client through DevTools).
""")


if __name__ == "__main__":
    main()
