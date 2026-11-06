-- NASA Near-Earth Asteroid Data Pipeline
-- M3: cleaned layer and mapping tables
-- Built by src/clean.py from the M2 tables (sql/schema.sql), which it never changes.
--
-- Pattern for every value that cleaning can change:
--   <col>_raw   exactly what M2 holds
--   <col>       the cleaned value: NULL when not trusted, standardised when the text was inconsistent,
--               converted when the type was wrong, otherwise unchanged. Never imputed.
--   <col>_flag  why <col> differs from <col>_raw (or a note on a kept value); one flag per value,
--               the first rule that applies wins (order in docs/cleaning_report.md, section 5).
-- Each cleaned table has the grain, primary key and row count of the M2 table it cleans.

PRAGMA foreign_keys = ON;

-- Mapping tables: loaded from the committed CSVs in data/mappings/ on every run.
-- They hold NASA source ids and names, never surrogate keys (those belong to one database build).

CREATE TABLE IF NOT EXISTS body_alias_map (
    alias TEXT PRIMARY KEY,               -- orbiting_body exactly as NASA sends it
    name TEXT NOT NULL,                   -- standard English name
    decided_by TEXT NOT NULL,
    decided_at TEXT NOT NULL,             -- YYYY-MM-DD
    note TEXT NOT NULL
) STRICT;

CREATE TABLE IF NOT EXISTS asteroid_identity_map (
    source_id TEXT PRIMARY KEY,           -- NASA id that duplicates another record
    resolved_source_id TEXT NOT NULL,     -- NASA id the analysis should use instead
    decided_by TEXT NOT NULL,
    decided_at TEXT NOT NULL,
    note TEXT NOT NULL,
    CHECK (source_id <> resolved_source_id)
) STRICT;

-- 1. Cleaned asteroids: one row per row of asteroids
CREATE TABLE IF NOT EXISTS asteroid_clean (
    asteroid_key INTEGER PRIMARY KEY REFERENCES asteroids (asteroid_key),

    designation_raw TEXT,
    designation TEXT,
    designation_flag TEXT NOT NULL CHECK (designation_flag IN (
        'ok', 'missing_not_in_source', 'invalid_inconsistent_with_name')),

    absolute_magnitude_h_raw REAL,
    absolute_magnitude_h REAL,
    absolute_magnitude_h_flag TEXT NOT NULL CHECK (absolute_magnitude_h_flag IN (
        'ok', 'missing_not_reported', 'invalid_out_of_range')),

    is_potentially_hazardous_raw INTEGER,
    is_potentially_hazardous INTEGER CHECK (is_potentially_hazardous IN (0, 1)),
    is_potentially_hazardous_flag TEXT NOT NULL CHECK (is_potentially_hazardous_flag IN (
        'ok', 'missing_not_reported', 'unchecked_no_orbit', 'label_rule_mismatch')),

    -- row-level: what approach data exists for this asteroid
    approach_coverage TEXT NOT NULL CHECK (approach_coverage IN (
        'earth_approaches', 'no_earth_approach', 'no_approach_in_source')),

    -- identity: the asteroid analyses should count this row as (itself unless a mapping says otherwise)
    resolved_asteroid_key INTEGER NOT NULL REFERENCES asteroids (asteroid_key),
    identity_flag TEXT NOT NULL CHECK (identity_flag IN ('ok', 'duplicate_id_resolved'))
) STRICT;

-- 2. Cleaned orbits: one row per row of orbits
CREATE TABLE IF NOT EXISTS orbit_clean (
    orbit_key INTEGER PRIMARY KEY REFERENCES orbits (orbit_key),
    asteroid_key INTEGER NOT NULL UNIQUE REFERENCES asteroids (asteroid_key),

    eccentricity_raw REAL,
    eccentricity REAL,
    eccentricity_flag TEXT NOT NULL CHECK (eccentricity_flag IN (
        'ok', 'missing_not_reported', 'invalid_out_of_range', 'unusual_high', 'unusual_low')),

    inclination_raw REAL,
    inclination REAL,
    inclination_flag TEXT NOT NULL CHECK (inclination_flag IN (
        'ok', 'missing_not_reported', 'invalid_out_of_range', 'unusual_high', 'unusual_low')),

    semi_major_axis_raw REAL,
    semi_major_axis REAL,
    semi_major_axis_flag TEXT NOT NULL CHECK (semi_major_axis_flag IN (
        'ok', 'missing_not_reported', 'invalid_out_of_range', 'invalid_inconsistent',
        'unusual_high', 'unusual_low')),

    minimum_orbit_intersection_raw REAL,
    minimum_orbit_intersection REAL,
    minimum_orbit_intersection_flag TEXT NOT NULL CHECK (minimum_orbit_intersection_flag IN (
        'ok', 'missing_not_reported', 'invalid_negative')),

    orbit_uncertainty_raw TEXT,
    orbit_uncertainty INTEGER CHECK (orbit_uncertainty BETWEEN 0 AND 9),
    orbit_uncertainty_flag TEXT NOT NULL CHECK (orbit_uncertainty_flag IN (
        'ok', 'missing_not_reported', 'invalid_not_a_code'))
) STRICT;

-- 3. Cleaned approaches: one row per row of approaches
CREATE TABLE IF NOT EXISTS approach_clean (
    asteroid_key INTEGER NOT NULL REFERENCES asteroids (asteroid_key),
    epoch_date_close_approach INTEGER NOT NULL,
    orbiting_body_raw TEXT NOT NULL,      -- part of the key, so it is exactly the M2 value

    orbiting_body TEXT,
    orbiting_body_flag TEXT NOT NULL CHECK (orbiting_body_flag IN ('ok', 'standardised', 'unmapped')),

    miss_distance_km_raw REAL,
    miss_distance_km REAL,
    miss_distance_km_flag TEXT NOT NULL CHECK (miss_distance_km_flag IN (
        'ok', 'missing_not_reported', 'invalid_nonpositive', 'unusual_high', 'unusual_low')),

    relative_velocity_km_s_raw REAL,
    relative_velocity_km_s REAL,
    relative_velocity_km_s_flag TEXT NOT NULL CHECK (relative_velocity_km_s_flag IN (
        'ok', 'missing_not_reported', 'invalid_out_of_range', 'unusual_high', 'unusual_low')),

    -- row-level: observed (on or before the retrieval date) or a NASA prediction
    timing_flag TEXT NOT NULL CHECK (timing_flag IN ('past', 'predicted')),

    PRIMARY KEY (asteroid_key, epoch_date_close_approach, orbiting_body_raw),
    FOREIGN KEY (asteroid_key, epoch_date_close_approach, orbiting_body_raw)
        REFERENCES approaches (asteroid_key, epoch_date_close_approach, orbiting_body)
) STRICT;

CREATE INDEX IF NOT EXISTS idx_approach_clean_body ON approach_clean (orbiting_body);

-- Views for analysis (M4): names joined in, identity resolved.
CREATE VIEW IF NOT EXISTS v_asteroid_clean AS
SELECT a.source_id, a.name, r.source_id AS resolved_source_id, c.*
FROM asteroid_clean AS c
JOIN asteroids AS a ON a.asteroid_key = c.asteroid_key
JOIN asteroids AS r ON r.asteroid_key = c.resolved_asteroid_key;

CREATE VIEW IF NOT EXISTS v_approach_clean AS
SELECT c.resolved_asteroid_key, a.name, p.*
FROM approach_clean AS p
JOIN asteroid_clean AS c ON c.asteroid_key = p.asteroid_key
JOIN asteroids AS a ON a.asteroid_key = p.asteroid_key;
