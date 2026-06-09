"""
investigate_cuckoo.py - figure out HOW the Farm Manager client reaches the
server, so we can route our own write requests the same way.

Background: direct Python requests to https://192.168.68.78:8888 fail mutual
TLS (the server demands a client cert we don't have).  The client succeeds
because its requests carry the cert via the internal "cuckoo" proxy.  To
write, we must send our requests through whatever path the client uses.

This script does NOT originate any HTTP.  It passively inspects a real API
request the client already makes (via DevTools) and reports the connection
facts, then enumerates local listeners and processes that might be cuckoo.

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

API_HOST_HINT = "192.168.68.78"   # the server we ultimately want to reach


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
            # any call to the real API host/port (8888) tells us the path
            if ":8888" in url or API_HOST_HINT in url:
                found = {
                    "url": url,
                    "remoteIPAddress": resp.get("remoteIPAddress"),
                    "remotePort": resp.get("remotePort"),
                    "protocol": resp.get("protocol"),
                    "requestHeaders": resp.get("requestHeaders", {}),
                    "fromProxy": resp.get("fromProxy"),
                }
    finally:
        ws.close()

    return found


# ---------------------------------------------------------------------------
# 2. Enumerate local listeners + processes (Windows)
# ---------------------------------------------------------------------------

def local_listeners() -> str:
    try:
        out = subprocess.check_output(
            ["netstat", "-ano", "-p", "TCP"], text=True, stderr=subprocess.DEVNULL)
    except Exception as e:
        return f"(netstat failed: {e})"
    lines = [ln for ln in out.splitlines() if "LISTENING" in ln and "127.0.0.1" in ln]
    return "\n".join(lines) if lines else "(no 127.0.0.1 TCP listeners found)"


def find_cuckoo_processes() -> str:
    try:
        out = subprocess.check_output(["tasklist"], text=True, stderr=subprocess.DEVNULL)
    except Exception as e:
        return f"(tasklist failed: {e})"
    hits = [ln for ln in out.splitlines()
            if re.search(r"cuckoo|bambu", ln, re.IGNORECASE)]
    return "\n".join(hits) if hits else "(no cuckoo/bambu processes matched)"


# ---------------------------------------------------------------------------
# Report + interpretation
# ---------------------------------------------------------------------------

def main():
    print("=" * 70)
    print("CUCKOO INVESTIGATION")
    print("=" * 70)

    print("\n[1] Inspecting a real API request the client makes ...")
    info = inspect_api_request()
    if not info:
        print("    No :8888 API request observed. Make sure the client is open")
        print("    on the Printers page (it polls /devices2 every ~30s).")
    else:
        print(f"    url            : {info['url']}")
        print(f"    remoteIPAddress: {info['remoteIPAddress']}")
        print(f"    remotePort     : {info['remotePort']}")
        print(f"    protocol       : {info['protocol']}")
        print(f"    fromProxy      : {info['fromProxy']}")
        hdrs = info["requestHeaders"]
        interesting = {k: v for k, v in hdrs.items()
                       if k.lower() in ("host", "authorization", "x-bbl-sec-ver",
                                        "user-agent", "via", "x-forwarded-for")}
        print(f"    key headers    : {json.dumps(interesting, indent=22)[22:]}")

    print("\n[2] Local TCP listeners on 127.0.0.1 (cuckoo proxy candidates):")
    print(local_listeners())

    print("\n[3] Processes matching cuckoo/bambu:")
    print(find_cuckoo_processes())

    print("\n" + "=" * 70)
    print("HOW TO READ THIS")
    print("=" * 70)
    if info and info.get("remoteIPAddress"):
        ip = info["remoteIPAddress"]
        if ip.startswith("127.") or ip == "::1":
            print(f"""
    remoteIPAddress is LOCALHOST ({ip}:{info['remotePort']}).
    => cuckoo is a real local proxy. The client sends to it, and it
       re-originates to the server WITH the client cert.

    NEXT STEP: route our writes through it. In bambu_api.py set:
        CUCKOO_PROXY = {{"https": "http://127.0.0.1:{info['remotePort']}",
                        "http":  "http://127.0.0.1:{info['remotePort']}"}}
    (or, if it speaks plain HTTP, point BASE_URL at
     http://127.0.0.1:{info['remotePort']}). Then post_task / opt_command
     will inherit the cert automatically.""")
        else:
            print(f"""
    remoteIPAddress is the REAL SERVER ({ip}:{info['remotePort']}).
    => there is no local proxy hop. Electron's network stack is presenting
       the client cert directly from the Windows cert store.

    This means a forward-proxy route does NOT exist; the cert is attached
    by the OS/Electron net layer. Options from here:
      * shell out to Windows curl (Schannel) referencing the cert by
        thumbprint (CurrentUser\\MY\\<thumb>) - uses the non-exportable key
        without exporting it; or
      * drive the client via DevTools so the app issues the request.
    Re-run with this output and we'll pick the route.""")
    else:
        print("\n    No API request captured - cannot conclude. Retry with the")
        print("    client focused on the Printers page.")
    print()


if __name__ == "__main__":
    main()
