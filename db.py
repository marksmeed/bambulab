"""
SQLite backbone for the Smokeforge print farm.
Mirrors /devices2 live state into printers / ams_units / slots.
"""

import sqlite3
from pathlib import Path

_SCHEMA = Path(__file__).with_name("schema.sql")


def connect(path: str = "farm.db") -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def init_db(path: str = "farm.db") -> None:
    con = connect(path)
    con.executescript(_SCHEMA.read_text())
    con.close()


def upsert_printer(con: sqlite3.Connection, dev_id: str, name: str,
                   model: str | None, last_state: str | None) -> None:
    con.execute(
        """
        INSERT INTO printers (dev_id, name, model, last_state, last_seen)
        VALUES (?, ?, ?, ?, datetime('now'))
        ON CONFLICT(dev_id) DO UPDATE SET
            name       = excluded.name,
            model      = excluded.model,
            last_state = excluded.last_state,
            last_seen  = datetime('now')
        """,
        (dev_id, name, model, last_state),
    )


def sync_printer_ams(con: sqlite3.Connection, dev_id: str, units: list) -> None:
    con.execute("DELETE FROM ams_units WHERE printer_id = ?", (dev_id,))
    for u in units:
        cur = con.execute(
            """
            INSERT INTO ams_units (printer_id, ams_id, is_external, humidity, temp, updated_at)
            VALUES (?, ?, ?, ?, ?, datetime('now'))
            """,
            (dev_id, u["ams_id"], 1 if u["external"] else 0,
             u.get("humidity"), u.get("temp")),
        )
        ams_row_id = cur.lastrowid
        for s in u.get("slots", []):
            con.execute(
                """
                INSERT INTO slots
                    (ams_unit_id, slot_id, status, material, code,
                     colour_hex, colour_name, remain, tag_uid, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                (ams_row_id, s["slot_id"], s["status"], s.get("material"),
                 s.get("code"), s.get("hex"), s.get("colour"),
                 s.get("remain"), s.get("tag_uid")),
            )


def sync_devices(con: sqlite3.Connection, printers: list) -> None:
    """Mirror a full /devices2 parse into the state tables (single transaction)."""
    with con:
        for p in printers:
            upsert_printer(
                con,
                dev_id=p["dev_id"],
                name=p["name"],
                model=p.get("model"),
                last_state=p.get("state"),
            )
            sync_printer_ams(con, p["dev_id"], p.get("units", []))


def parse_and_sync(raw: dict, path: str = "farm.db") -> None:
    """
    Convenience: parse a raw /devices2 response, merge state + filament data,
    and sync into the DB.  Joins parse_devices (gcode_state) + parse_loadout
    (AMS units) on dev_id so sync_devices gets everything in one pass.
    """
    from bambu_status import parse_devices
    from bambu_filament import parse_loadout

    states = {d["dev_id"]: d["state"] for d in parse_devices(raw)}
    printers = parse_loadout(raw)
    for p in printers:
        p["state"] = states.get(p["dev_id"])

    con = connect(path)
    try:
        sync_devices(con, printers)
    finally:
        con.close()
