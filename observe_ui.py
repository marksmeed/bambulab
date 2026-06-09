"""
observe_ui.py - logs the Farm Manager client's API calls (incl. POST bodies)
to a file while you click through the UI. Read-only observation via DevTools.

Run it, then in the client do the actions you want to learn:
  - send a job to a printer
  - pause / resume / cancel a print
  - reorder the queue
Each action's request (method, URL, headers, body) is written to the log.

Usage:
    python observe_ui.py                 # logs until you press Ctrl+C
    python observe_ui.py --seconds 120   # logs for a fixed time
"""

import json
import sys
import time
import urllib.request
from datetime import datetime

import websocket  # pip install websocket-client

DEBUG_PORT = 9222
LOGFILE = f"api_capture_{datetime.now():%Y%m%d_%H%M%S}.log"

# Only log calls to the real farm API, skip image/liveview noise
SKIP = ("liveview.jpeg", ".png", ".jpg", "/file?asset_path=liveview")
INTEREST = ("192.168.68.78:8888", "/task", "/device", "/printer",
            "/file", "/login", "/users", "/settings", "/captain")


def get_page_ws():
    raw = urllib.request.urlopen(f"http://127.0.0.1:{DEBUG_PORT}/json", timeout=3).read()
    for t in json.loads(raw):
        if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
            return t["webSocketDebuggerUrl"]
    return None


def log(line, fh):
    print(line)
    fh.write(line + "\n")
    fh.flush()


def main():
    seconds = None
    if "--seconds" in sys.argv:
        seconds = int(sys.argv[sys.argv.index("--seconds") + 1])

    ws_url = get_page_ws()
    if not ws_url:
        print("No page target. Is the client running with the debug flags?")
        return

    ws = websocket.create_connection(ws_url, max_size=None)
    mid = [0]

    def send(method, params=None):
        mid[0] += 1
        ws.send(json.dumps({"id": mid[0], "method": method, "params": params or {}}))

    send("Network.enable")

    # Cache request bodies for POST/PUT so we can log them
    req_bodies = {}

    fh = open(LOGFILE, "w", encoding="utf-8")
    log(f"# API capture started {datetime.now():%Y-%m-%d %H:%M:%S}", fh)
    log(f"# Logging to {LOGFILE}", fh)
    log("# Now click through the client UI (send a job, pause, cancel, reorder)...", fh)
    log("# Press Ctrl+C when done.\n", fh)

    end = time.time() + seconds if seconds else None
    ws.settimeout(2)
    try:
        while True:
            if end and time.time() > end:
                break
            try:
                m = json.loads(ws.recv())
            except websocket.WebSocketTimeoutException:
                continue
            except Exception:
                break

            meth = m.get("method", "")

            if meth == "Network.requestWillBeSent":
                req = m["params"]["request"]
                url = req.get("url", "")
                verb = req.get("method", "")
                if any(s in url for s in SKIP):
                    continue
                if verb in ("POST", "PUT", "PATCH", "DELETE") or any(i in url for i in INTEREST):
                    ts = datetime.now().strftime("%H:%M:%S")
                    log(f"[{ts}] {verb} {url}", fh)
                    pd = req.get("postData")
                    if pd:
                        # pretty-print JSON bodies where possible
                        try:
                            log("    BODY: " + json.dumps(json.loads(pd), indent=2)
                                .replace("\n", "\n    "), fh)
                        except Exception:
                            log("    BODY: " + pd[:2000], fh)
                    # log a couple of useful headers (auth shape)
                    hdrs = req.get("headers", {})
                    interesting = {k: v for k, v in hdrs.items()
                                   if k.lower() in ("authorization", "content-type", "x-bbl-sec-ver")}
                    if interesting:
                        log("    HDRS: " + json.dumps(interesting), fh)
                    log("", fh)

    except KeyboardInterrupt:
        pass
    finally:
        ws.close()
        log(f"\n# Capture ended {datetime.now():%H:%M:%S}. Saved to {LOGFILE}", fh)
        fh.close()
        print(f"\nLog written to: {LOGFILE}")


if __name__ == "__main__":
    main()
