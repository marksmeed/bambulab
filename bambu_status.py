"""
bambu_status.py - Smokeforge Terrain print-farm status reader.

Reads live printer + job status from the Bambu Farm Manager client by
passively observing the traffic it already makes (via the Chrome DevTools
protocol). No certificates, no direct server connection, no activation risk.

Usage:
    python bambu_status.py            # one snapshot, printed as a table
    python bambu_status.py --watch    # refresh every few seconds
"""

import json
import os
import subprocess
import sys
import time
import urllib.request

import websocket  # pip install websocket-client

# ----------------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------------
CLIENT_EXE = r"C:\Program Files\Bambu Farm Manager Client\Bambu Farm Manager Client.exe"
CLIENT_PROC = "Bambu Farm Manager Client"
DEBUG_PORT = 9222
CAPTURE_SECONDS = 16          # how long to listen for a full poll cycle
WATCH_INTERVAL = 5            # seconds between refreshes in --watch mode

WANT = ("/devices2", "/task?", "/captain")

# gcode_state -> friendly label
STATE_LABELS = {
    "RUNNING": "Printing",
    "PAUSE": "Paused",
    "FINISH": "Finished",
    "IDLE": "Idle",
    "PREPARE": "Preparing",
    "SLICING": "Slicing",
    "FAILED": "Failed",
    "UNKNOWN": "Unknown",
}


# ----------------------------------------------------------------------------
# Client launch / DevTools discovery
# ----------------------------------------------------------------------------
def is_debug_port_up():
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{DEBUG_PORT}/json/version", timeout=2)
        return True
    except Exception:
        return False


def client_running():
    # tasklist is the most portable check on Windows
    try:
        out = subprocess.check_output(
            ["tasklist", "/FI", f"IMAGENAME eq {CLIENT_PROC}.exe"],
            stderr=subprocess.DEVNULL, text=True,
        )
        return CLIENT_PROC in out
    except Exception:
        return False


def ensure_client_with_debug():
    """Make sure the client is running with the debug flags we need."""
    if is_debug_port_up():
        return True

    if client_running():
        print("Client is running but without the debug port. Restarting it with debug flags...")
        subprocess.run(["taskkill", "/IM", f"{CLIENT_PROC}.exe", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(2)

    if not os.path.exists(CLIENT_EXE):
        print(f"ERROR: cannot find client exe at:\n  {CLIENT_EXE}")
        print("Edit CLIENT_EXE at the top of this script.")
        sys.exit(1)

    print("Launching Farm Manager client with debug flags...")
    subprocess.Popen([CLIENT_EXE,
                      f"--remote-debugging-port={DEBUG_PORT}",
                      "--remote-allow-origins=*"])

    # wait for the debug port + a page target to appear
    for _ in range(30):
        time.sleep(1)
        if is_debug_port_up() and get_page_ws():
            print("Client is up. Give it a few seconds to load the printers page...\n")
            time.sleep(4)
            return True
    print("ERROR: debug port did not come up. The client may block remote debugging.")
    sys.exit(1)


def get_page_ws():
    """Return the websocket URL of the renderer 'page' target (or None)."""
    try:
        raw = urllib.request.urlopen(f"http://127.0.0.1:{DEBUG_PORT}/json", timeout=3).read()
        targets = json.loads(raw)
        for t in targets:
            if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                return t["webSocketDebuggerUrl"]
    except Exception:
        pass
    return None


# ----------------------------------------------------------------------------
# Passive capture via DevTools
# ----------------------------------------------------------------------------
def capture(ws_url, seconds=CAPTURE_SECONDS):
    """Observe the client's own HTTP traffic and grab the JSON bodies we want."""
    ws = websocket.create_connection(ws_url, max_size=None)
    _mid = [0]

    def send(method, params=None):
        _mid[0] += 1
        ws.send(json.dumps({"id": _mid[0], "method": method, "params": params or {}}))
        return _mid[0]

    send("Network.enable")
    captured = {}
    pending = {}  # requestId -> url

    ws.settimeout(seconds + 1)
    end = time.time() + seconds
    while time.time() < end and len(captured) < 3:
        try:
            m = json.loads(ws.recv())
        except Exception:
            break
        meth = m.get("method", "")
        if meth == "Network.responseReceived":
            url = m["params"]["response"]["url"]
            if any(w in url for w in WANT):
                pending[m["params"]["requestId"]] = url
        elif meth == "Network.loadingFinished":
            rid = m["params"]["requestId"]
            if rid in pending:
                url = pending.pop(rid)
                send("Network.getResponseBody", {"requestId": rid})
                while True:
                    try:
                        rep = json.loads(ws.recv())
                    except Exception:
                        break
                    if "result" in rep and "body" in rep.get("result", {}):
                        body = rep["result"]["body"]
                        key = ("devices2" if "/devices2" in url
                               else "task" if "/task?" in url else "captain")
                        captured.setdefault(key, body)
                        break
    ws.close()
    return captured


# ----------------------------------------------------------------------------
# Parsing
# ----------------------------------------------------------------------------
def parse_devices(raw):
    out = []
    try:
        data = json.loads(raw)
    except Exception:
        return out
    for d in data.get("devices", []):
        rs = d.get("report_status", {}) or {}
        state = rs.get("gcode_state", "UNKNOWN") or "UNKNOWN"
        out.append({
            "dev_id": d.get("dev_id", ""),
            "name": d.get("name") or d.get("dev_name") or d.get("dev_id", ""),
            "model": d.get("dev_model", ""),
            "ip": d.get("dev_ip", ""),
            "state": state,
            "label": STATE_LABELS.get(state, state.title()),
            "file": rs.get("subtask_name") or rs.get("gcode_file") or "",
            "percent": rs.get("mc_percent", ""),
            "remaining": rs.get("mc_remaining_time", ""),
            "layer": rs.get("layer_num", ""),
            "total_layer": rs.get("total_layer_num", ""),
            "nozzle": round(float(rs.get("nozzle_temper", 0)), 1),
            "bed": round(float(rs.get("bed_temper", 0)), 1),
            "hms": rs.get("hms", []) or [],
        })
    out.sort(key=lambda x: x["name"])
    return out


def parse_tasks(raw):
    out = []
    try:
        data = json.loads(raw)
    except Exception:
        return out
    for t in data.get("hits", []):
        out.append({
            "id": t.get("id", ""),
            "name": t.get("task_name", ""),
        })
    return out


def parse_captain(raw):
    try:
        return json.loads(raw)
    except Exception:
        return {}


# ----------------------------------------------------------------------------
# Display
# ----------------------------------------------------------------------------
def fmt_remaining(mins):
    try:
        mins = int(mins)
    except Exception:
        return ""
    if mins <= 0:
        return ""
    h, m = divmod(mins, 60)
    return f"{h}h{m:02d}m" if h else f"{m}m"


def print_table(devices, tasks, captain):
    os.system("")  # enable ANSI on Windows terminals
    now = time.strftime("%H:%M:%S")
    name = captain.get("name", "Farm")
    print(f"\n  {name}   {len(devices)} printers   {now}")
    if captain.get("expire_time"):
        print(f"  activation: {captain.get('activate_state','?')} (expires {captain['expire_time'][:10]})")
    print("  " + "-" * 86)
    print(f"  {'Printer':<14}{'Model':<6}{'Status':<10}{'Job':<26}{'Prog':<7}{'Left':<8}{'Noz':<6}{'Bed':<5}")
    print("  " + "-" * 86)

    for d in devices:
        prog = f"{d['percent']}%" if d["percent"] != "" else ""
        if d["layer"] and d["total_layer"]:
            prog = f"{d['percent']}% L{d['layer']}/{d['total_layer']}"
        job = (d["file"][:24] + "..") if len(d["file"]) > 24 else d["file"]
        flag = "  !" if d["hms"] else ""
        print(f"  {d['name'][:13]:<14}{d['model']:<6}{d['label']:<10}{job:<26}"
              f"{prog:<7}{fmt_remaining(d['remaining']):<8}{d['nozzle']:<6}{d['bed']:<5}{flag}")

    print("  " + "-" * 86)

    # summary line
    printing = sum(1 for d in devices if d["state"] == "RUNNING")
    paused = sum(1 for d in devices if d["state"] == "PAUSE")
    idle = sum(1 for d in devices if d["state"] in ("IDLE", "FINISH"))
    errs = sum(1 for d in devices if d["hms"])
    print(f"  Printing: {printing}   Paused: {paused}   Idle/Done: {idle}   "
          f"With alerts: {errs}   Queued tasks: {len(tasks)}")
    if errs:
        print("  (! = HMS alert on printer; run with --watch to monitor)")
    print()


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def snapshot():
    ws_url = get_page_ws()
    if not ws_url:
        print("No page target found; is the printers screen open?")
        return
    caps = capture(ws_url)
    if "devices2" not in caps:
        print("Did not capture device data this cycle. Make sure the printers page "
              "is open and active, then try again.")
        return
    devices = parse_devices(caps.get("devices2", ""))
    tasks = parse_tasks(caps.get("task", ""))
    captain = parse_captain(caps.get("captain", ""))
    print_table(devices, tasks, captain)


def main():
    watch = "--watch" in sys.argv
    ensure_client_with_debug()
    if watch:
        print("Watch mode - Ctrl+C to stop.")
        try:
            while True:
                snapshot()
                time.sleep(WATCH_INTERVAL)
        except KeyboardInterrupt:
            print("\nStopped.")
    else:
        snapshot()


if __name__ == "__main__":
    main()