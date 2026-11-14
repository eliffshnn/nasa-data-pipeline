-- Question: how do an asteroid's orbit, its listed Earth approaches and its hazard label relate? (cleaned layer)
-- Grain: one row per resolved asteroid that has an orbit row and at least one qualifying Earth approach.
--   approach_clean is collapsed to one row per asteroid in the CTE first, so every asteroid counts once
--   (the unit for sections 6 and 7 is the asteroid, not the approach).
-- Orbit class: NASA's orbit_class_type from the M2 orbits table (orbit_clean does not carry it; joined by orbit_key, one row each).
--   derived_class recomputes it from a and e with NASA's definitions, as a check (q = a(1 - e), Q = a(1 + e), in AU):
--   IEO (Atira) Q < 0.983 · ATE (Aten) a < 1, Q > 0.983 · APO (Apollo) a > 1, q < 1.017 · AMO (Amor) a > 1, 1.017 < q < 1.3
-- Flag filter (same parameters as closest_earth_clean.sql):
--   identity_flag = 'ok'; label present (label_rule_mismatch kept unless :exclude_label_mismatch = 1);
--   miss distance ok (+ unusual_* if :include_unusual = 1); past (+ predicted if :include_predicted = 1).
--   Orbit values: eccentricity, inclination and semi-major axis must be present; their unusual_* flags are returned,
--   not filtered, so the notebook can drop them as a named sensitivity step.
-- H, MOID and diameter define the hazard label and are deliberately not returned.
WITH earth AS (
    SELECT
        p.asteroid_key,
        COUNT(*)                    AS n_earth_approaches,
        MIN(p.miss_distance_km)     AS closest_km,
        AVG(p.relative_velocity_km_s) AS mean_velocity_km_s
    FROM approach_clean AS p
    WHERE p.orbiting_body = 'Earth'
      AND p.miss_distance_km IS NOT NULL
      AND (p.miss_distance_km_flag = 'ok' OR :include_unusual = 1)
      AND (p.timing_flag = 'past' OR :include_predicted = 1)
    GROUP BY p.asteroid_key
)
SELECT
    c.asteroid_key,
    c.is_potentially_hazardous AS hazardous,
    o.eccentricity,
    o.inclination,
    o.semi_major_axis,
    o.semi_major_axis_flag,
    o.inclination_flag,
    o.semi_major_axis * (1 - o.eccentricity) AS perihelion_au,
    m.orbit_class_type AS orbit_class,
    CASE
        WHEN o.semi_major_axis * (1 + o.eccentricity) < 0.983 THEN 'IEO'
        WHEN o.semi_major_axis < 1.0                         THEN 'ATE'
        WHEN o.semi_major_axis * (1 - o.eccentricity) < 1.017 THEN 'APO'
        WHEN o.semi_major_axis * (1 - o.eccentricity) < 1.3   THEN 'AMO'
        ELSE 'other'
    END AS derived_class,
    e.n_earth_approaches,
    e.closest_km,
    e.mean_velocity_km_s
FROM asteroid_clean AS c
JOIN orbit_clean AS o ON o.asteroid_key = c.asteroid_key
JOIN orbits AS m      ON m.orbit_key = o.orbit_key
JOIN earth AS e       ON e.asteroid_key = c.asteroid_key
WHERE c.identity_flag = 'ok'
  AND c.is_potentially_hazardous IS NOT NULL
  AND (c.is_potentially_hazardous_flag <> 'label_rule_mismatch' OR :exclude_label_mismatch = 0)
  AND o.eccentricity IS NOT NULL
  AND o.inclination IS NOT NULL
  AND o.semi_major_axis IS NOT NULL;
