# Smokeforge Terrain — Print Farm Integration: Technical Notes

Reference document for the Bambu Farm Manager integration powering the
Smokeforge Terrain order-fulfilment system. Keep this in the project so any
new chat has full context without re-deriving it.

---

## 1. How we connect (the core method)

The Bambu **Farm Manager Server** runs locally and exposes a REST API on
`https://192.168.68.78:8888`, but it enforces **mutual TLS (mTLS)** — the
server demands a client certificate at the TLS handshake. The client cert
lives in the Windows cert store with a **non-exportable** private key
(confirmed: `Export-PfxCertificate` refused). Generating a new cert is **not
an option** — it consumes one of only five activation slots and previously
expired an activation.

**Solution that works (zero cert handling, zero activation risk):**
We read data by passively observing the official **Farm Manager Client**
(an Electron app) via the **Chrome DevTools Protocol**. The client makes the
authenticated requests through its internal `cuckoo` proxy (which holds the
cert); we just watch the traffic and read response bodies.

### Launch the client with debugging enabled
```
"C:\Program Files\Bambu Farm Manager Client\Bambu Farm Manager Client.exe" --remote-debugging-port=9222 --remote-allow-origins=*
```
Both flags are required — without `--remote-allow-origins=*` the websocket
handshake is rejected (403). `bambu_client.py` handles launching/relaunching.

### Key facts
- DevTools endpoint: `http://127.0.0.1:9222/json` → find the `type:"page"` target
- The page target ID changes every launch — always re-fetch it
- A raw `fetch()` from the page does NOT go through the proxy (fails mTLS);
  only the app's own requests do. So we **observe**, we don't inject fetches.
- Auto-update does not work on this install, so the version is effectively
  pinned (good — protects the debug-port method).

### Fallbacks if debug mode is ever disabled by an update
1. Pin/keep the current installer version (auto-update already broken)
2. UI Automation reading the rendered window (data is on screen regardless)
3. Don't take updates without testing

---

## 2. The API

Base: `https://192.168.68.78:8888`
Auth (after mTLS): `Authorization: Bearer <JWT>` + header `x-bbl-sec-ver: 1`.
The JWT is in the client's Local Storage (`servers[0].token`); it expires
(~7 days seen) and the client refreshes it.

### Read endpoints (confirmed working)
- `GET /captain` — server health + activation (`activate_state`, `expire_time`)
- `GET /devices2?use_lite=true` — full printer status (all printers)
- `GET /task?task_state=ongoing&limit=1000&offset=0&use_lite=true` — live queue
- `GET /task?task_state=finished&limit=10&offset=0&use_lite=true` — finished
- `GET /device/{dev_id}` — single device detailed state
- `GET /file/f3mffolder` — 3mf folder list
- `GET /file/f3mf?folder_id={id}` — 3mf files in a folder

### Write / control endpoints
- `POST /task` — **create a print job** (payload below)
- `POST /device/{dev_id}/opt` — device command; envelope:
  `{"opt": "<name>", "<name>": {...params...}}`
- `/task/terminatetasks`, `/task/sortongoing`, `/task/finished/delete`
- `/file/move`, `/file/f3mffolder/root/order`

### Device `opt` command vocabulary (from source)
Print control: `pause`, `resume`, `stop`
Filament: `ams_filament_setting`, `external_filament_setting`,
`unload_filament`, `calibration`, `auto_cali_for_user`

**Rescan note:** there is NO dedicated AMS RFID-rescan opt in this API.
Sending `ams_filament_setting` refreshes a slot as a side effect. A true full
RFID re-read would need the lower-level MQTT print channel (not yet built).

### POST /task — create-print payload (captured)
```json
{
  "task_print_model": 1,
  "queue_model_cnt": 0,
  "device_pool": ["<dev_id>"],
  "device_pool2": [
    {"dev_id": "<dev_id>", "ams_mapping2": [{"ams_id": 0, "slot_id": 2}]}
  ],
  "task_name": "<order reference>",
  "print_option": {
    "auto_bed_leveling": true,
    "flow_dynamic_calibration": true,
    "timelapse": false,
    "bed_leveling_mode": 2,
    "flow_dynamic_cali_mode": 2,
    "nozzle_offset_cali_mode": 2
  },
  "f3mf_id": "<3mf id>",
  "ams_mapping2": []
}
```
- `f3mf_id` — the model to print (look up by name via `/file/f3mf`)
- `device_pool` / `device_pool2.dev_id` — target printer
- `ams_mapping2.slot_id` — which AMS slot (i.e. which colour) to use
- `task_name` — use the order reference for traceability

### POST /device/{dev_id}/opt — external filament setting (captured)
```json
{
  "opt": "external_filament_setting",
  "external_filament_setting": {
    "tray_info_idx": "GFB01", "tray_type": "ASA", "tray_color": "161616FF",
    "nozzle_temp_min": 240, "nozzle_temp_max": 280,
    "ams_id": 255, "tray_id": 0, "slot_id": 0
  }
}
```

---

## 3. The farm — 10 printers (as of 2026-06-09)

| Name | Model | AMS type | Notes |
|------|-------|----------|-------|
| 3DP-01P-356 | C12 | AMS v1 | remain=-1 (no weight sensing) |
| 3DP-01P-640 | C12 | AMS v1 (x2) | |
| H2D-094-922 | O1D | AMS 2 Pro (x2) + ext | real %; dual extruder |
| H2S-093-094 | O1S | AMS 2 Pro (x2) | real % |
| H2S-093-866 | O1S | AMS 2 Pro (x2) | real % |
| P1S-01P-071 | C12 | external only | effectively empty |
| P1S-01P-804 | C12 | AMS v1 | remain=-1 |
| P2S-22E-267 | N7 | AMS 2 Pro (x2) | real % |
| X1C-00M-175 | BL-P001 | AMS | remain=None (loaded, untracked) |
| X1C-00M-454 | BL-P001 | AMS (x2) | remain=None |

### AMS data interpretation (critical)
From `report_status.ams.ams[]`, each unit has `id`, `humidity`, `temp`,
and `tray[]` (slots). Each slot: `tray_type`, `tray_info_idx` (Bambu code,
e.g. `GFA00`=PLA Basic), `tray_color` (RGBA hex), `tag_uid` (RFID), `remain`.

**`remain` field:**
- `-1` → AMS v1 (Lite) hardware — no weight sensing. NOT a low-stock signal.
- `0–100` → AMS 2 Pro — real %. **Only these are used for low-stock warnings.**
- `None` → empty slot (no `tray_type`) OR loaded-but-untracked (BL-P001/X1C,
  which report colour but no remaining telemetry).

**`humidity`:** level 0–5, where **5 = damp (bad)**, 0 = dry. Flag 4+ for
desiccant attention. `temp` is AMS internal temperature in °C.

**AMS `id` ≥ 128** → external spool / single feeder, not a 4-slot AMS.

### Filament colour codes seen (hex RGB → name)
000000/161616=Black, C12E1F=Red, 00AE42=Bambu Green, 0086D6=Blue,
0A2989=Royal Blue, FF9016=Orange, FF6A13=Dark Orange, FEC600=Yellow,
EC008C=Magenta, F5547C=Pink, D1D3D5=Grey, FFFFFF=White. All PLA Basic (GFA00).

---

## 4. The scripts (in `C:\Users\mntsm\bambu-tool\`)

- **`bambu_client.py`** — ensures client up with debug flags; `ensure_client()`
  and `get_page_ws()` helpers; `--watch` watchdog mode. Imported by the others.
- **`bambu_status.py`** — live printer/job status console table; `--watch` mode.
- **`bambu_filament.py`** — filament loadout (colour names + hex), low-stock
  (AMS 2 Pro only), humidity/temp report. Flags `--low [n]`, `--humidity`.
- **`observe_ui.py`** — logs the client's API calls incl. POST bodies to a
  file; run it then click UI actions to capture write payloads.

Dependencies: `pip install websocket-client plyvel-ci ccl_chromium_reader`
(plyvel/ccl only needed for the earlier storage exploration, not runtime).

---

## 5. The fulfilment loop (target architecture)

1. **Order arrives** (Etsy / eBay / Amazon)
2. Map product → `f3mf_id` (via `/file/f3mf`)
3. Read `/devices2` → find an idle printer of the right model with the
   required colour loaded (match `tray_color` / `tray_info_idx`)
4. `POST /task` with `task_name` = order reference, target printer, slot
5. Poll `/task` + `/devices2` to track to completion
6. Mark order fulfilled

### Still to build
- **SQLite backbone** — persist printers, slots, jobs, 3mf library, orders
- **Allocation engine** — the colour-aware printer-picking logic above
- **Marketplace integrations** — Etsy Open API v3, eBay, Amazon SP-API
- **(Optional) MQTT control** — for true AMS rescan / lower-level commands
- Capture remaining payloads: `ams_filament_setting` (AMS, not external),
  `pause`/`resume`/`stop`, `/task/sortongoing`

---

## 6. Hard rules (safety / lessons learned)

- **Never** generate a new client cert or trigger a new activation — only
  five slots exist and mistakes are costly/irreversible.
- **Never** try to export the existing cert's key (non-exportable; harmless
  to attempt but pointless).
- All data access is **passive observation** of the client's own traffic.
- Keep the working client version; auto-update is broken (which suits us).
