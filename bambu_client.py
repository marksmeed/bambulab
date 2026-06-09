"""
bambu_client.py - ensures the Bambu Farm Manager client is running with the
DevTools debug flags we need, restarting it if it has closed.

Use as a module:
    from bambu_client import ensure_client, get_page_ws
    ensure_client()                 # launches/relaunches if needed
    ws = get_page_ws()              # current renderer websocket URL

Or run directly:
    python bambu_client.py          # ensure it's up, report status
    python bambu_client.py --watch  # keep it up; relaunch if it ever closes
"""

import json
import os
import subprocess
import sys
import time
import urllib.request

CLIENT_EXE = r"C:\Program Files\Bambu Farm Manager Client\Bambu Farm Manager Client.exe"
CLIENT_PROC = "Bambu Farm Manager Client"
DEBUG_PORT = 9222
LAUNCH_FLAGS = [f"--remote-debugging-port={DEBUG_PORT}", "--remote-allow-origins=*"]


def debug_port_up():
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{DEBUG_PORT}/json/version", timeout=2)
        return True
    except Exception:
        return False


def get_page_ws():
    """Websocket URL of the renderer 'page' target, or None."""
    try:
        raw = urllib.request.urlopen(f"http://127.0.0.1:{DEBUG_PORT}/json", timeout=3).read()
        for t in json.loads(raw):
            if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                return t["webSocketDebuggerUrl"]
    except Exception:
        pass
    return None


def process_running():
    try:
        out = subprocess.check_output(
            ["tasklist", "/FI", f"IMAGENAME eq {CLIENT_PROC}.exe"],
            stderr=subprocess.DEVNULL, text=True)
        return CLIENT_PROC in out
    except Exception:
        return False


def kill_client():
    subprocess.run(["taskkill", "/IM", f"{CLIENT_PROC}.exe", "/F"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2)


def launch():
    if not os.path.exists(CLIENT_EXE):
        print(f"ERROR: client exe not found:\n  {CLIENT_EXE}")
        sys.exit(1)
    subprocess.Popen([CLIENT_EXE] + LAUNCH_FLAGS)


def ensure_client(wait_for_page=True, verbose=True):
    """
    Guarantee the client is running WITH debug flags and a page target ready.
    Returns the page websocket URL (or None if it couldn't be brought up).
    """
    # Already healthy?
    if debug_port_up():
        ws = get_page_ws()
        if ws:
            if verbose:
                print("Client already up with debug port.")
            return ws

    # Running but without flags -> must restart to add them
    if process_running() and not debug_port_up():
        if verbose:
            print("Client running without debug flags - restarting it...")
        kill_client()

    if verbose:
        print("Launching client with debug flags...")
    launch()

    # Wait for the port and a page target
    for i in range(40):
        time.sleep(1)
        if debug_port_up():
            ws = get_page_ws()
            if ws:
                if verbose:
                    print(f"Client ready after {i+1}s.")
                    if wait_for_page:
                        print("Letting the printers page settle...")
                if wait_for_page:
                    time.sleep(4)
                return get_page_ws()
    if verbose:
        print("ERROR: client did not expose the debug port in time.")
    return None


def watch(interval=10):
    """Keep the client alive with debug flags; relaunch if it ever drops."""
    print(f"Watchdog running (checking every {interval}s). Ctrl+C to stop.")
    try:
        while True:
            if not debug_port_up() or not get_page_ws():
                print(time.strftime("%H:%M:%S"), "client down or no page - ensuring...")
                ensure_client(verbose=False)
                print(time.strftime("%H:%M:%S"), "client restored.")
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nWatchdog stopped.")


if __name__ == "__main__":
    if "--watch" in sys.argv:
        ensure_client()
        watch()
    else:
        ws = ensure_client()
        if ws:
            print("Page websocket:", ws)
            print("Status: READY")
        else:
            print("Status: FAILED")
