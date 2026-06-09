-- ============================================================================
-- Smokeforge Terrain - print farm SQLite backbone
-- schema.sql  (v2 - multi-file orders + per-filament colour mapping)
--
-- Core model:
--   * The unit of printing is ONE 3mf on ONE machine = one row in `jobs`.
--   * A 3mf model has an ORDERED list of filaments (model_filaments). That
--     order drives ams_mapping2 ("plumb the colours in the right order").
--   * A product (listing) can require SEVERAL 3mf files (product_parts).
--   * A model is compatible with one or more PRINTER MODELS (model_compat) -
--     this is "the machine that matches the 3mf settings".
--   * The order specifies colours per PART, per filament (order_part_colours)
--     - each 3mf file in the order can carry its own colours. Allocation
--     resolves each filament -> a physical AMS slot of that colour and writes
--     the result into job_filaments (= the ams_mapping2 payload).
--
-- Run once:  sqlite3 farm.db < schema.sql
-- Per connection:  PRAGMA foreign_keys = ON;
-- ============================================================================

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ----------------------------------------------------------------------------
-- LIVE STATE  (mirror of /devices2 - upserted every poll)  [unchanged from v1]
-- ----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS printers (
    dev_id      TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    model       TEXT,                       -- C12 / O1D / O1S / N7 / BL-P001
    last_state  TEXT,                       -- gcode_state
    last_seen   TEXT DEFAULT (datetime('now')),
    notes       TEXT
);

CREATE TABLE IF NOT EXISTS ams_units (
    id          INTEGER PRIMARY KEY,
    printer_id  TEXT NOT NULL REFERENCES printers(dev_id) ON DELETE CASCADE,
    ams_id      INTEGER NOT NULL,           -- >=128 = external feeder
    is_external INTEGER NOT NULL DEFAULT 0,
    humidity    INTEGER,                    -- 0..5, 5 = damp
    temp        REAL,
    updated_at  TEXT DEFAULT (datetime('now')),
    UNIQUE (printer_id, ams_id)
);

CREATE TABLE IF NOT EXISTS slots (
    id           INTEGER PRIMARY KEY,
    ams_unit_id  INTEGER NOT NULL REFERENCES ams_units(id) ON DELETE CASCADE,
    slot_id      INTEGER NOT NULL,
    status       TEXT NOT NULL,             -- empty/untracked_v1/untracked/tracked
    material     TEXT,
    code         TEXT,                       -- tray_info_idx, e.g. 'GFA00'
    colour_hex   TEXT,                       -- 6-char RGB upper
    colour_name  TEXT,
    remain       INTEGER,                    -- 0..100 or NULL
    tag_uid      TEXT,
    updated_at   TEXT DEFAULT (datetime('now')),
    UNIQUE (ams_unit_id, slot_id)
);

CREATE INDEX IF NOT EXISTS ix_slots_colour ON slots(colour_hex);
CREATE INDEX IF NOT EXISTS ix_slots_status ON slots(status);
CREATE INDEX IF NOT EXISTS ix_printers_model ON printers(model);
CREATE INDEX IF NOT EXISTS ix_printers_state ON printers(last_state);

-- ----------------------------------------------------------------------------
-- 3MF LIBRARY  (cache of /file/f3mf)
-- ----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS models (
    f3mf_id     TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    folder_id   TEXT,
    updated_at  TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS ix_models_name ON models(name);

-- The ordered filament list a model expects. filament_index is the slicer's
-- filament order and is what ams_mapping2 must follow. `role` is an optional
-- human label ('main','base','detail') for UI / prefill only; the order's
-- colour spec matches by filament_index per part, not by role.
CREATE TABLE IF NOT EXISTS model_filaments (
    id                  INTEGER PRIMARY KEY,
    f3mf_id             TEXT NOT NULL REFERENCES models(f3mf_id) ON DELETE CASCADE,
    filament_index      INTEGER NOT NULL,   -- 0-based; the order that matters
    role                TEXT,               -- 'main' / 'base' / 'detail' / ...
    default_material    TEXT DEFAULT 'PLA',
    default_colour_hex  TEXT,               -- what it was sliced with (info only)
    default_colour_name TEXT,
    UNIQUE (f3mf_id, filament_index)
);

-- Which PRINTER MODELS a given 3mf can run on (matches the sliced settings).
CREATE TABLE IF NOT EXISTS model_compat (
    f3mf_id       TEXT NOT NULL REFERENCES models(f3mf_id) ON DELETE CASCADE,
    printer_model TEXT NOT NULL,            -- e.g. 'C12'
    PRIMARY KEY (f3mf_id, printer_model)
);

-- ----------------------------------------------------------------------------
-- PRODUCTS  (marketplace listing -> bill of materials of 3mf files)
-- ----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS products (
    id            INTEGER PRIMARY KEY,
    sku           TEXT UNIQUE,
    marketplace   TEXT,                     -- 'etsy' / 'ebay' / 'amazon'
    listing_id    TEXT,
    title         TEXT,
    notes         TEXT,
    UNIQUE (marketplace, listing_id)
);

-- A product is built from one or more 3mf files (each printed separately).
CREATE TABLE IF NOT EXISTS product_parts (
    id          INTEGER PRIMARY KEY,
    product_id  INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    f3mf_id     TEXT NOT NULL REFERENCES models(f3mf_id),
    quantity    INTEGER NOT NULL DEFAULT 1, -- copies of this part per product
    UNIQUE (product_id, f3mf_id)
);

-- ----------------------------------------------------------------------------
-- ORDERS
-- ----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS orders (
    id           INTEGER PRIMARY KEY,
    marketplace  TEXT NOT NULL,
    order_ref    TEXT NOT NULL,             -- reused as task_name
    buyer        TEXT,
    status       TEXT NOT NULL DEFAULT 'new',  -- new/allocated/printing/printed/shipped/cancelled
    received_at  TEXT DEFAULT (datetime('now')),
    fulfilled_at TEXT,
    notes        TEXT,
    UNIQUE (marketplace, order_ref)
);

CREATE INDEX IF NOT EXISTS ix_orders_status ON orders(status);

CREATE TABLE IF NOT EXISTS order_items (
    id           INTEGER PRIMARY KEY,
    order_id     INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    product_id   INTEGER REFERENCES products(id),
    quantity     INTEGER NOT NULL DEFAULT 1,
    status       TEXT NOT NULL DEFAULT 'pending'  -- pending/allocated/printing/done/failed
);

CREATE INDEX IF NOT EXISTS ix_order_items_status ON order_items(status);

-- The buyer's colour choice, expressed per PART (3mf file) and per filament
-- within that part - so each 3mf in a multi-file product can have its own
-- colours. filament_index matches model_filaments.filament_index for that
-- f3mf_id. Colours are shared across copies (product_parts.quantity and
-- order_items.quantity); per-copy colours would be a future extension.
CREATE TABLE IF NOT EXISTS order_part_colours (
    id             INTEGER PRIMARY KEY,
    order_item_id  INTEGER NOT NULL REFERENCES order_items(id) ON DELETE CASCADE,
    f3mf_id        TEXT NOT NULL REFERENCES models(f3mf_id),  -- which part
    filament_index INTEGER NOT NULL,        -- which filament of that model
    colour_hex     TEXT NOT NULL,
    colour_name    TEXT,
    material       TEXT DEFAULT 'PLA',
    UNIQUE (order_item_id, f3mf_id, filament_index)
);

-- ----------------------------------------------------------------------------
-- JOBS  (one printable instance of one model on one printer)
-- ----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS jobs (
    id             INTEGER PRIMARY KEY,
    bambu_task_id  TEXT,                     -- observed from /task (NULL until confirmed)
    order_item_id  INTEGER REFERENCES order_items(id),  -- NULL = ad-hoc print
    f3mf_id        TEXT REFERENCES models(f3mf_id),
    printer_id     TEXT REFERENCES printers(dev_id),
    task_name      TEXT,                     -- = orders.order_ref
    state          TEXT NOT NULL DEFAULT 'queued',  -- queued/printing/finished/failed/cancelled
    created_at     TEXT DEFAULT (datetime('now')),
    started_at     TEXT,
    finished_at    TEXT,
    notes          TEXT
);

CREATE INDEX IF NOT EXISTS ix_jobs_state ON jobs(state);
CREATE INDEX IF NOT EXISTS ix_jobs_task  ON jobs(bambu_task_id);

-- The resolved colour->slot mapping for a job. Ordered by filament_index this
-- IS the ams_mapping2 array: [{ams_id, slot_id}, ...]. Multiple logical
-- filaments wanting the same colour may resolve to the same physical slot.
CREATE TABLE IF NOT EXISTS job_filaments (
    id                   INTEGER PRIMARY KEY,
    job_id               INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    filament_index       INTEGER NOT NULL,   -- logical filament order in the 3mf
    requested_colour_hex TEXT,
    assigned_ams_id      INTEGER,            -- resolved physical AMS unit
    assigned_slot_id     INTEGER,            -- resolved physical slot
    UNIQUE (job_id, filament_index)
);

-- ----------------------------------------------------------------------------
-- VIEWS
-- ----------------------------------------------------------------------------

-- Candidate pool: every loaded slot with its printer + AMS context.
CREATE VIEW IF NOT EXISTS v_loaded_slots AS
SELECT  p.dev_id      AS printer_id,
        p.name        AS printer_name,
        p.model       AS printer_model,
        p.last_state  AS printer_state,
        a.ams_id      AS ams_id,
        a.is_external AS is_external,
        a.humidity    AS humidity,
        s.slot_id     AS slot_id,
        s.status      AS slot_status,
        s.material    AS material,
        s.colour_hex  AS colour_hex,
        s.colour_name AS colour_name,
        s.remain      AS remain
FROM    slots s
JOIN    ams_units a ON a.id = s.ams_unit_id
JOIN    printers  p ON p.dev_id = a.printer_id
WHERE   s.status <> 'empty';

CREATE VIEW IF NOT EXISTS v_idle_printers AS
SELECT  dev_id, name, model, last_state, last_seen
FROM    printers
WHERE   last_state IN ('IDLE', 'FINISH');

CREATE VIEW IF NOT EXISTS v_low_stock AS
SELECT  printer_name, printer_model, ams_id, slot_id,
        material, colour_name, colour_hex, remain
FROM    v_loaded_slots
WHERE   slot_status = 'tracked' AND remain IS NOT NULL
ORDER BY remain ASC;
