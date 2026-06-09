"""
bambu_filament.py - filament / AMS tracking for the Smokeforge print farm.

Reads the live /devices2 data (via the running client) and produces:
  - a per-printer filament loadout (material, colour name + hex, % remaining)
  - a low-stock report (only for AMS 2 Pro slots that actually report weight)

AMS hardware notes baked in:
  remain == -1   -> AMS v1 (Lite): no weight sensing -> "untracked", never warned
  remain == None -> slot is empty (no filament)  [if no type] OR
                    loaded but untracked          [if type present, e.g. X1C]
  remain 0..100  -> AMS 2 Pro: real % -> used for low-stock warnings

Usage:
    python bambu_filament.py                 # full loadout + low-stock
    python bambu_filament.py --low           # low-stock only
    python bambu_filament.py --low 15        # low-stock with custom threshold %
"""

import json
import sys
import time

import websocket  # pip install websocket-client
from bambu_client import ensure_client, get_page_ws

LOW_STOCK_THRESHOLD = 20  # percent; AMS 2 Pro slots at/below this get flagged

# Bambu PLA Basic colour codes seen across the farm (hex RGB -> friendly name).
COLOUR_NAMES = {
    "000000": "Black",
    "161616": "Black",
    "C12E1F": "Red",
    "00AE42": "Bambu Green",
    "0086D6": "Blue",
    "0A2989": "Royal Blue",
    "FF9016": "Orange",
    "FF6A13": "Dark Orange",
    "FEC600": "Yellow",
    "EC008C": "Magenta",
    "F5547C": "Pink",
    "D1D3D5": "Grey",
    "FFFFFF": "White",
}

# AMS ids >= 128 are external spool / single feeders, not 4-slot AMS units
EXTERNAL_AMS_MIN = 128


def colour_name(hex_rgba):
    if not hex_rgba:
        return ""
    rgb = hex_rgba[:6].upper()
    return COLOUR_NAMES.get(rgb, f"#{rgb}")


def fetch_devices2():
    """Capture one /devices2 body from the client's own polling."""
    ensure_client(verbose=False)
    ws_url = get_page_ws()
    if not ws_url:
        return None
    ws = websocket.create_connection(ws_url, max_size=None)
    mid = [0]

    def send(m, p=None):
        mid[0] += 1
        ws.send(json.dumps({"id": mid[0], "method": m, "params": p or {}}))

    send("Network.enable")
    ws.settimeout(16)
    end = time.time() + 15
    body = None
    pend = {}
    while time.time() < end and body is None:
        try:
            m = json.loads(ws.recv())
        except Exception:
            break
        meth = m.get("method", "")
        if meth == "Network.responseReceived" and "/devices2" in m["params"]["response"]["url"]:
            pend[m["params"]["requestId"]] = 1
        elif meth == "Network.loadingFinished" and m["params"]["requestId"] in pend:
            send("Network.getResponseBody", {"requestId": m["params"]["requestId"]})
            while True:
                rep = json.loads(ws.recv())
                if "result" in rep and "body" in rep.get("result", {}):
                    body = rep["result"]["body"]
                    break
    ws.close()
    return json.loads(body) if body else None


def slot_state(tray):
    """Classify a slot: returns (status, remain_value_or_None)."""
    has_type = bool(tray.get("tray_type"))
    remain = tray.get("remain")
    if not has_type:
        return "empty", None
    if remain == -1:
        return "untracked_v1", None      # AMS v1, no sensing
    if remain is None:
        return "untracked", None         # loaded but no telemetry (e.g. X1C)
    return "tracked", remain             # AMS 2 Pro real value


def parse_loadout(data):
    """Return a list of printers, each with its AMS slots parsed."""
    printers = []
    for d in data.get("devices", []):
        ams_block = d.get("report_status", {}).get("ams", {})
        units = ams_block.get("ams", []) if isinstance(ams_block, dict) else []
        p = {
            "name": d.get("name") or d.get("dev_id"),
            "model": d.get("dev_model", ""),
            "dev_id": d.get("dev_id", ""),
            "units": [],
        }
        for u in units:
            try:
                ams_id = int(u.get("id", 0))
            except Exception:
                ams_id = 0
            # humidity level (0-5) and AMS internal temperature (°C) if present
            try:
                hum = int(u.get("humidity")) if u.get("humidity") not in (None, "") else None
            except Exception:
                hum = None
            try:
                temp = float(u.get("temp")) if u.get("temp") not in (None, "") else None
            except Exception:
                temp = None
            unit = {
                "ams_id": ams_id,
                "external": ams_id >= EXTERNAL_AMS_MIN,
                "humidity": hum,
                "temp": temp,
                "slots": [],
            }
            for tray in u.get("tray", []):
                status, remain = slot_state(tray)
                unit["slots"].append({
                    "slot_id": tray.get("id"),
                    "status": status,
                    "remain": remain,
                    "material": tray.get("tray_type", ""),
                    "code": tray.get("tray_info_idx", ""),
                    "hex": (tray.get("tray_color", "")[:6]).upper(),
                    "colour": colour_name(tray.get("tray_color", "")),
                    "sub": tray.get("tray_sub_brands", ""),
                    "tag_uid": tray.get("tag_uid", ""),
                })
            p["units"].append(unit)
        printers.append(p)
    printers.sort(key=lambda x: x["name"])
    return printers


def print_loadout(printers):
    for p in printers:
        label = f"{p['name']} ({p['model']})"
        print(f"\n  {label}")
        print("  " + "-" * 60)
        if not p["units"]:
            print("    no AMS detected")
            continue
        for u in p["units"]:
            tag = "External spool" if u["external"] else f"AMS {u['ams_id']}"
            hum = u["humidity"]
            hum_str = f"humidity {hum}/5" if hum is not None else "humidity -"
            if hum is not None and hum >= 4:
                hum_str += " DAMP!"
            temp_str = f", {u['temp']:.1f}\u00b0C" if u["temp"] is not None else ""
            print(f"    {tag}  ({hum_str}{temp_str})")
            for s in u["slots"]:
                if s["status"] == "empty":
                    print(f"      slot {s['slot_id']}: -- empty --")
                    continue
                if s["status"] == "tracked":
                    rem = f"{s['remain']}%"
                elif s["status"] == "untracked_v1":
                    rem = "v1 (no tracking)"
                else:
                    rem = "loaded (untracked)"
                swatch = f"#{s['hex']}"
                print(f"      slot {s['slot_id']}: {s['material']:<4} "
                      f"{s['colour']:<12} {swatch:<8} {rem}")


def low_stock(printers, threshold):
    """Only AMS 2 Pro tracked slots can be low; v1/untracked are excluded."""
    rows = []
    for p in printers:
        for u in p["units"]:
            for s in u["slots"]:
                if s["status"] == "tracked" and s["remain"] is not None and s["remain"] <= threshold:
                    rows.append((s["remain"], p["name"], u["ams_id"], s))
    rows.sort()  # lowest first
    return rows


def print_low_stock(rows, threshold):
    print(f"\n  LOW STOCK  (AMS 2 Pro slots at or below {threshold}%)")
    print("  " + "-" * 60)
    if not rows:
        print("    Nothing low. (Note: AMS v1 units can't report and are not checked.)")
        return
    for remain, pname, ams_id, s in rows:
        print(f"    {remain:>3}%  {pname:<14} AMS{ams_id} slot {s['slot_id']}  "
              f"{s['material']} {s['colour']} (#{s['hex']})")


def humidity_report(printers):
    """All AMS units with their humidity level + temp, driest first."""
    rows = []
    for p in printers:
        for u in p["units"]:
            if u["external"] and not any(s["status"] != "empty" for s in u["slots"]):
                continue  # skip empty external feeders
            rows.append((u["humidity"] if u["humidity"] is not None else -1,
                         p["name"], u["ams_id"], u["external"], u["humidity"], u["temp"]))
    rows.sort(key=lambda r: (-(r[0]), r[1]))  # dampest (highest) first
    return rows


def print_humidity(rows):
    print("\n  HUMIDITY  (0 = dry, 5 = damp; 4+ flagged)")
    print("  " + "-" * 60)
    if not rows:
        print("    no AMS humidity data")
        return
    for level, pname, ams_id, external, hum, temp in rows:
        unit = "Ext" if external else f"AMS{ams_id}"
        lvl = f"{hum}/5" if hum is not None else "  - "
        flag = "  <-- DAMP, check desiccant" if (hum is not None and hum >= 4) else ""
        t = f"{temp:.1f}\u00b0C" if temp is not None else "   -  "
        print(f"    {lvl:<5} {t:<8} {pname:<14} {unit}{flag}")


def main():
    args = sys.argv[1:]
    low_only = "--low" in args
    humidity_only = "--humidity" in args
    threshold = LOW_STOCK_THRESHOLD
    # optional numeric threshold after --low
    if low_only:
        i = args.index("--low")
        if i + 1 < len(args) and args[i + 1].isdigit():
            threshold = int(args[i + 1])

    data = fetch_devices2()
    if not data:
        print("Could not capture device data. Is the client open on the printers page?")
        return
    printers = parse_loadout(data)

    if humidity_only:
        print_humidity(humidity_report(printers))
        print()
        return

    if not low_only:
        print(f"\n  Filament loadout - {time.strftime('%H:%M:%S')}")
        print_loadout(printers)
    print_low_stock(low_stock(printers, threshold), threshold)
    if not low_only:
        print_humidity(humidity_report(printers))
    print()


if __name__ == "__main__":
    main()
