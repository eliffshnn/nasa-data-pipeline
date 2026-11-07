# M3 Cleaning Report

**Project:** NASA Near-Earth Asteroid Hazard Analysis · **Milestone:** M3 (clean and validate)
**Team:** Rana Yalçın · Burak Avşar · Elif Şahin

This report documents every decision the cleaned layer makes. It is the companion of:

| File | Role |
|---|---|
| `notebooks/m3_profile.ipynb` | Profile of the M2 database; the evidence for every issue below (cited as §n) |
| `src/clean.py` | Builds `asteroid_clean`, `orbit_clean`, `approach_clean` from the M2 tables |
| `src/clean_config.py` | Every threshold and constant used by `clean.py` (justified in section 5) |
| `data/mappings/*.csv` | Team decisions on names and identities (section 4) |
| `src/validate.py` | STOP / WARN checks on the cleaned layer (section 6) |
| `sql/clean_schema.sql` | Cleaned tables, the allowed flag values (`CHECK`), and the M4 views |

Reproduce from the repository root:

```bash
python src/load.py
python src/clean.py
python src/validate.py
python src/validate.py --self-test
```

Data: 360 raw files retrieved on 2026-10-17 → 5,033 asteroids, 5,000 orbits, 150,936 approaches, 0 quarantined.

---

## 1. Principles

- **The M2 tables are never changed.** `clean.py` takes a SHA-256 fingerprint of every M2 table before and after the run and fails if they differ.
- **Every cleaned value keeps its raw value next to it** (`<col>_raw`, `<col>`, `<col>_flag`). A reader can always see what we changed and why.
- **One flag per value.** The rules for a value are applied in a fixed order, and the first rule that fires sets the flag (section 3).
- **Invalid → NULL, unusual → kept.** A value that cannot be true is set to `NULL` in the cleaned column. A value that is rare but possible keeps its value and gets a flag.
- **No imputation in M3.** Missing values stay missing and get a flag that says why.
- **Decisions about names and identities are data, not code.** They live in `data/mappings/*.csv`, with who decided, when, and why.

---

## 2. Issues register

Each issue was found in the profile (`notebooks/m3_profile.ipynb`). *Cause* says whether the cause is **confirmed** (checked against the raw files or NASA's documentation) or **inferred** (the most likely explanation, not proven).

| ID | Family | Table.column | What | How many | Evidence | Cause | Decision (as implemented) | Investigated by |
|---|---|---|---|---:|---|---|---|---|
| I-01 | Missing | `asteroids.designation` | NULL: feed records do not have the field. 6 more were lost by the M2 loader, now fixed in `load.py` | 33 (was 39) | §2 | **Confirmed** (raw file contents) | keep NULL; `designation_flag = missing_not_in_source`; loader fixed | Burak Avşar |
| I-02 | Missing | `orbits` (whole row) | no orbit for asteroids seen only in the feed | 33 | §2 | **Confirmed** (feed has no `orbital_data`) | keep the asteroid; its hazard label cannot be checked → `is_potentially_hazardous_flag = unchecked_no_orbit` | Burak Avşar |
| I-03 | Missing | `approaches` (whole asteroid) | asteroid has no approach / no Earth approach | 305 / 571 | §2 | **Inferred**: orbit never comes close (255 of the 305 are Amor), so missing not at random | keep; `approach_coverage` = `no_approach_in_source` / `no_earth_approach` | Burak Avşar |
| I-04 | Coverage | `approaches` | 56% of rows are future predictions; NASA window 1900–2200 | 84,274 | §1 | **Confirmed** (NASA window) | `timing_flag` = `past` / `predicted` (date compared with retrieval date) | Burak Avşar |
| I-05 | Invalid | `approaches.close_approach_date` | one date outside 1900–2200 (1899-12-31) | 1 | §6, §7 | **Inferred**: window edge in UTC | keep, no flag | Burak Avşar |
| I-06 | Text | `approaches.orbiting_body` | abbreviations `Merc`, `Juptr` next to full names | 16,125 rows | §4 | **Confirmed** (NASA codes) | `data/mappings/orbiting_body.csv`; `orbiting_body_flag = standardised` | Rana Yalçın |
| I-07 | Text | `orbits.orbit_uncertainty` | ordered 0–9 code stored as text | 5,000 | §4 | **Confirmed** (NASA uncertainty parameter U) | cleaned `INTEGER` column, range 0–9 | Rana Yalçın |
| I-08 | Identity | `asteroids.source_id` | same asteroid under a provisional id and a numbered id | 3 pairs | §5 | **Inferred** (same designation, H, approach time) | `data/mappings/asteroid_identity.csv`; `identity_flag = duplicate_id_resolved`; resolved in `v_asteroid_clean`, no rows merged or deleted | Rana Yalçın |
| I-09 | Cross-field | `asteroids.is_potentially_hazardous` | label = 1 but H > 22.0 (the rule says not hazardous) | 15 | §8 | **Inferred** (H refined after the label was set); NASA's view unknown | keep the label; `is_potentially_hazardous_flag = label_rule_mismatch` | Elif Şahin |
| I-10 | Cross-field | `approaches.miss_distance_km` vs `orbits.minimum_orbit_intersection` | Earth approach closer than the current MOID | 1,603 of 106,069 | §8 | **Inferred** (the orbit drifts over the centuries; MOID describes today's orbit) | no flag on the value; documented for M4 | Elif Şahin |
| I-11 | Cross-field | `asteroids.diameter_min_km`, `diameter_max_km` | diameter is computed from H, not measured | all 5,033 | §3 | **Inferred** (ratio exactly √5; `D · 10^(H/5)` constant) | keep; not carried into the cleaned layer; excluded from M4 features | Elif Şahin |
| I-12 | Unusual | `orbits`, `approaches` | robust z-score > 3.5 within the group | see section 3 | §9 | real objects (e.g. retrograde orbit, key 1357) | `unusual_high` / `unusual_low`, value kept | Elif Şahin |

**Checked and not found:** sentinel values and negatives (§3) · non-NFC, whitespace or case variants in text (§4) · date vs epoch vs timestamp mismatch (§6) · stuck values in sequence (§6) · violations of 17 physical and definitional rules (§7) · NULL in any key or measurement column except `designation` (§2) · quarantined rows (0, §1).

---

## 3. Flag dictionary

**How to read it.** *Order* is the order in which `clean_value()` in `src/clean.py` tries the rules: the first rule that fires sets the flag, and later rules are not tried. A `NULL` raw value always gets `missing_not_reported` first. *Effect* says what happens to the cleaned value.

Counts are from `clean.py` (`m3_clean_run1.txt`; per-group breakdown in section 6.1). They agree with the profile (§§2–9).

### 3.1 `asteroid_clean` (5,033 rows)

| Column | Order | Flag | Rule | Effect | Count |
|---|---:|---|---|---|---:|
| `designation` | 1 | `missing_not_in_source` | raw value is NULL (feed record without the field) | stays NULL | 33 |
| | 2 | `invalid_inconsistent_with_name` | designation ≠ the one read from the name (`'144900 (2004 VG64)'` → `144900`) | → NULL | 0 |
| | – | `ok` | | kept | 5,000 |
| `absolute_magnitude_h` | 0 | `missing_not_reported` | raw NULL | NULL | 0 |
| | 1 | `invalid_out_of_range` | H outside `H_MIN..H_MAX` (0–35) | → NULL | 0 |
| | – | `ok` | | kept | 5,033 |
| `is_potentially_hazardous` | 0 | `missing_not_reported` | raw NULL | NULL | 0 |
| | 1 | `unchecked_no_orbit` | no MOID (no orbit row) or no valid H, so the rule cannot be evaluated | kept | 33 |
| | 2 | `label_rule_mismatch` | label ≠ (H ≤ `PHA_H_MAX` **and** MOID ≤ `PHA_MOID_MAX_AU`) | kept | 15 |
| | – | `ok` | | kept | 4,985 |
| `approach_coverage` | – | `earth_approaches` | at least one approach with `orbiting_body = 'Earth'` | label | 4,157 |
| | – | `no_earth_approach` | approaches, but none with Earth | label | 571 |
| | – | `no_approach_in_source` | empty `close_approach_data` in every raw record | label | 305 |
| `identity_flag` | – | `duplicate_id_resolved` | `source_id` listed in `asteroid_identity.csv`; `resolved_asteroid_key` points to the numbered id | row kept | 3 |
| | – | `ok` | | `resolved_asteroid_key = asteroid_key` | 5,030 |

### 3.2 `orbit_clean` (5,000 rows)

Unusual values use the modified z-score `MAD_SCALE · (x − median) / MAD`, computed **per orbit class** (APO, AMO, ATE, IEO), on valid values only, leaving out the 3 duplicate asteroids so that they do not count twice.

| Column | Order | Flag | Rule | Effect | Count |
|---|---:|---|---|---|---:|
| `eccentricity` | 1 | `invalid_out_of_range` | not `0 ≤ e < ECCENTRICITY_MAX` | → NULL | 0 |
| | 2 | `unusual_high` / `unusual_low` | \|z\| > `Z_LIMIT` within the orbit class | kept | 0 / 0 |
| `inclination` | 1 | `invalid_out_of_range` | not `0 ≤ i ≤ INCLINATION_MAX_DEG` | → NULL | 0 |
| | 2 | `unusual_high` / `unusual_low` | \|z\| > `Z_LIMIT` | kept | 121 / 0 |
| `semi_major_axis` | 1 | `invalid_out_of_range` | not `a > 0` | → NULL | 0 |
| | 2 | `invalid_inconsistent` | \|a(1 − e) − perihelion\| > `AU_TOLERANCE` | → NULL | 0 |
| | 3 | `unusual_high` / `unusual_low` | \|z\| > `Z_LIMIT` | kept | 3 / 0 |
| `minimum_orbit_intersection` | 1 | `invalid_negative` | MOID < 0 | → NULL | 0 |
| `orbit_uncertainty` | 1 | `invalid_not_a_code` | not an integer in `UNCERTAINTY_CODES` (0–9) | → NULL | 0 |

All other values are `ok`.

### 3.3 `approach_clean` (150,936 rows)

Unusual values are computed **per orbiting body**. Miss distance spans four orders of magnitude, so it is scored on `log10`.

| Column | Order | Flag | Rule | Effect | Count |
|---|---:|---|---|---|---:|
| `orbiting_body` | – | `standardised` | raw alias mapped to a different name (`Merc`, `Juptr`) | full name | 16,125 |
| | – | `unmapped` | raw name not in `orbiting_body.csv` | NULL | 0 |
| `miss_distance_km` | 1 | `invalid_nonpositive` | distance ≤ 0 | → NULL | 0 |
| | 2 | `unusual_high` / `unusual_low` | \|z\| of log10(distance) > `Z_LIMIT` | kept | 0 / 2,502 |
| `relative_velocity_km_s` | 1 | `invalid_out_of_range` | not `0 < v < VELOCITY_MAX_KM_S` | → NULL | 0 |
| | 2 | `unusual_high` / `unusual_low` | \|z\| > `Z_LIMIT` | kept | 642 / 0 |
| `timing_flag` | – | `past` / `predicted` | approach date ≤ / > retrieval date (2026-10-17) | label | 66,662 / 84,274 |

`clean.py` leaves the 3 duplicate asteroids out of the median and MAD; the counts are nevertheless identical to the profile's, which used all rows.

---

## 4. Mapping and identity decisions

Both CSVs are loaded into the database (`body_alias_map`, `asteroid_identity_map`) so that every decision travels with the data. `clean.py` reports any CSV row that matches nothing.

### 4.1 Orbiting body names — `data/mappings/orbiting_body.csv`

| Alias in source | Standard name | Approaches | Why |
|---|---|---:|---|
| `Earth` | Earth | 106,102 | already the standard name |
| `Venus` | Venus | 22,568 | already the standard name |
| `Mars` | Mars | 5,793 | already the standard name |
| `Moon` | Moon | 348 | already the standard name |
| `Merc` | Mercury | 16,125 in total for `Merc` and `Juptr` | NASA NeoWs abbreviation; velocities up to 95 km/s fit Mercury's 47 km/s mean orbital speed |
| `Juptr` | Jupiter | | NASA NeoWs abbreviation; miss distances 7.8–299 million km match Jupiter's distance |

Match result: 6 of 6 aliases matched, 0 approach rows unmapped, 16,125 rows standardised. Decided by Burak Avşar, 2026-11-06.

### 4.2 Asteroid identity — `data/mappings/asteroid_identity.csv`

| Provisional id | Numbered id | Designation | Evidence |
|---|---|---|---|
| 3430309 | 2614134 | 2008 TC4 | same H (21.65), same approach 2026-10-17T04:02Z, same miss distance |
| 3801936 | 2678976 | 2018 EH4 | H 21.67 / 21.68, same approach 2026-10-14T05:49Z, miss distance differs by 80 km (0.001%) |
| 54051300 | 2679786 | 2020 QG3 | same H (21.22), same approach 2026-10-16T03:34Z, miss distance differs by 8 km |

Match result: 3 of 3 pairs matched, so 3 asteroids flagged `duplicate_id_resolved`. Both rows of each pair are kept. `v_asteroid_clean` and `v_approach_clean` resolve to the numbered id, which NASA gives once an object is numbered. All six rows come from one feed file. Decided by Burak Avşar, 2026-11-06; investigated by Rana Yalçın (I-08).

**Why not merge?** The match is inferred, not confirmed by NASA. Keeping both rows and resolving in a view means the decision can be reversed by editing one CSV line.

---

## 5. Constants

Every value is defined once in `src/clean_config.py`. Changing a value and running `python src/clean.py` again changes exactly the flags that value controls.

| Constant | Value | Used for | Justification |
|---|---|---|---|
| `AU_KM` | 149,597,870.7 | km ↔ AU conversion | The IAU 2012 exact definition of the astronomical unit. |
| `MAD_SCALE` | 0.6745 | modified z-score | Makes the median absolute deviation comparable to a standard deviation for normal data. |
| `Z_LIMIT` | 3.5 | `unusual_high` / `unusual_low` | The cut-off recommended for the modified z-score by Iglewicz & Hoaglin (1993). |
| `H_MIN`, `H_MAX` | 0.0, 35.0 | `absolute_magnitude_h` invalid | The brightest near-Earth asteroid has H ≈ 9 (Ganymed) and the faintest ever observed has H ≈ 33, so 0–35 leaves a margin on both sides. |
| `INCLINATION_MAX_DEG` | 180.0 | `inclination` invalid | Inclination is defined on 0–180°; anything outside is not a valid angle. |
| `ECCENTRICITY_MAX` | 1.0 | `eccentricity` invalid | e ≥ 1 is not a closed orbit, so the object would not be an asteroid orbiting the Sun. |
| `AU_TOLERANCE` | 0.001 AU (~150,000 km) | `semi_major_axis` inconsistent | Values carry 6+ decimals, so a gap above 0.001 AU between perihelion and a(1 − e) cannot be rounding. |
| `VELOCITY_MAX_KM_S` | 130.0 | `relative_velocity_km_s` invalid | The fastest possible inner-planet encounter is solar escape speed at Mercury (~67 km/s) plus Mercury's top orbital speed (~59 km/s), rounded up. |
| `UNCERTAINTY_CODES` | 0–9 | `orbit_uncertainty` invalid | NASA's orbit uncertainty parameter U is an integer from 0 to 9. |
| `PHA_H_MAX` | 22.0 | hazard rule | NASA/CNEOS definition of a potentially hazardous asteroid: H ≤ 22.0 … |
| `PHA_MOID_MAX_AU` | 0.05 | hazard rule | … and Earth MOID ≤ 0.05 AU. |

---

## 6. Run outputs and warnings

### 6.1 `python src/clean.py`

`clean.py` was run twice in a row. Both runs ended `STATUS: COMPLETE` with identical counts, `M2 tables unchanged: OK`, `row counts equal raw: OK` and `foreign_key_check: OK`.

| Cleaned table | Raw table | Run 1 | Run 2 |
|---|---|---:|---:|
| `asteroid_clean` | `asteroids` (5,033) | 5,033 | 5,033 |
| `orbit_clean` | `orbits` (5,000) | 5,000 | 5,000 |
| `approach_clean` | `approaches` (150,936) | 150,936 | 150,936 |

Run 1 output (`m3_clean_run1.txt`). Run 2 (`m3_clean_run2.txt`) is identical line for line.
The `·` separator in the `mappings:` line appears as `┬À` in the saved file because of the Windows console code page; it is shown corrected here.

```text
asteroid_clean: 5,033 rows (raw: 5,033)
orbit_clean: 5,000 rows (raw: 5,000)
approach_clean: 150,936 rows (raw: 150,936)

asteroid_clean flags (per asteroid; one column per flag)
  designation                                     ok   missing_not_in_source
    all                                        5,000                      33
  absolute_magnitude_h                            ok
    all                                        5,033
  is_potentially_hazardous                        ok     label_rule_mismatch      unchecked_no_orbit
    all                                        4,985                      15                      33
  approach_coverage                 earth_approaches   no_approach_in_source       no_earth_approach
    all                                        4,157                     305                     571
  identity                                        ok   duplicate_id_resolved
    all                                        5,030                       3

orbit_clean flags (per orbit class)
  eccentricity                                    ok
    AMO                                        1,979
    APO                                        2,620
    ATE                                          394
    IEO                                            7
  inclination                                     ok            unusual_high
    AMO                                        1,950                      29
    APO                                        2,531                      89
    ATE                                          391                       3
    IEO                                            7                       0
  semi_major_axis                                 ok            unusual_high
    AMO                                        1,978                       1
    APO                                        2,618                       2
    ATE                                          394                       0
    IEO                                            7                       0
  minimum_orbit_intersection                      ok
    AMO                                        1,979
    APO                                        2,620
    ATE                                          394
    IEO                                            7
  orbit_uncertainty                               ok
    AMO                                        1,979
    APO                                        2,620
    ATE                                          394
    IEO                                            7

approach_clean flags (per orbiting body, raw name)
  orbiting_body                                   ok            standardised
    Earth                                    106,102                       0
    Juptr                                          0                   7,556
    Mars                                       5,793                       0
    Merc                                           0                   8,569
    Moon                                         348                       0
    Venus                                     22,568                       0
  miss_distance_km                                ok             unusual_low
    Earth                                    105,103                     999
    Juptr                                      7,277                     279
    Mars                                       5,583                     210
    Merc                                       8,339                     230
    Moon                                         337                      11
    Venus                                     21,795                     773
  relative_velocity_km_s                          ok            unusual_high
    Earth                                    105,728                     374
    Juptr                                      7,547                       9
    Mars                                       5,777                      16
    Merc                                       8,455                     114
    Moon                                         345                       3
    Venus                                     22,442                     126
  timing                                        past               predicted
    Earth                                     47,453                  58,649
    Juptr                                      3,284                   4,272
    Mars                                       2,509                   3,284
    Merc                                       3,607                   4,962
    Moon                                         227                     121
    Venus                                      9,582                  12,986

mappings: body_alias_map 6 rows · approach bodies matched 6 of 6 · asteroid_identity_map 3 rows, matched 3 of 3
unmatched mapping entries: none
M2 tables unchanged: OK
row counts equal raw: OK
foreign_key_check: OK
STATUS: COMPLETE
```

### 6.2 `python src/validate.py`

Result: **4 PASS, 2 WARN, 0 STOP** → `STATUS: PASS WITH WARNINGS`.
`python src/validate.py --self-test`: the three STOP conditions (row count, impossible value, foreign key) were each injected into a temporary copy and detected, **3/3**.

| Check | Result |
|---|---|
| Raw/clean row-count equality | PASS |
| Impossible values | PASS |
| Foreign-key integrity | PASS |
| Missingness ratios | **WARN** |
| Approach coverage and temporal range | **WARN** |
| Body-name mapping completeness | PASS (0 unmapped, 16,125 standardised, 3 identities resolved) |

Output of `python src/validate.py` (`m3_validation.txt`):

```text
============================================================
NASA ASTEROID DATA PIPELINE - M3 VALIDATION
============================================================
  asteroids: 5,033 | asteroid_clean: 5,033
  orbits: 5,000 | orbit_clean: 5,000
  approaches: 150,936 | approach_clean: 150,936
[PASS] Row count equality: All raw and clean counts match
  asteroid_clean: 0 impossible values
  orbit_clean: 0 impossible values
  approach_clean: 0 impossible values
[PASS] Impossible values: No impossible values detected
[PASS] Foreign key integrity: foreign_key_check returned no violations
  Missingness ratios:
    asteroid_clean.designation: 33/5,033 (0.66%)
    asteroid_clean.absolute_magnitude_h: 0/5,033 (0.00%)
    asteroid_clean.is_potentially_hazardous: 0/5,033 (0.00%)
    orbit_clean.eccentricity: 0/5,000 (0.00%)
    orbit_clean.inclination: 0/5,000 (0.00%)
    orbit_clean.semi_major_axis: 0/5,000 (0.00%)
    orbit_clean.minimum_orbit_intersection: 0/5,000 (0.00%)
    orbit_clean.orbit_uncertainty: 0/5,000 (0.00%)
    approach_clean.orbiting_body: 0/150,936 (0.00%)
    approach_clean.miss_distance_km: 0/150,936 (0.00%)
    approach_clean.relative_velocity_km_s: 0/150,936 (0.00%)
[WARN] Missingness: Missing values are reported for data-quality review
  Approach coverage:
    earth_approaches: 4,157
    no_approach_in_source: 305
    no_earth_approach: 571
  Approach timing:
    past: 66,662
    predicted: 84,274
  Latest approach date (UTC): 2200-12-31
[WARN] Coverage and freshness: Coverage, timing, and latest approach date reported for review
  Unmapped body names: 0
  Standardised body names: 16,125
  Resolved duplicate identities: 3
[PASS] Mapping completeness: All approach body names are mapped

------------------------------------------------------------
VALIDATION SUMMARY
------------------------------------------------------------
PASS: 4
WARN: 2
STOP: 0

STATUS: PASS WITH WARNINGS
```

Output of `python src/validate.py --self-test` (`m3_validation_selftest.txt`), shortened to the lines that show each injected fault and its detection. Each test runs the full validator on its own temporary copy; the production database is not touched.

```text
Testing: Row count STOP
[STOP] Row count equality: asteroids=5033, asteroid_clean=5032
[PASS] Row count STOP: Validator correctly detected STOP
Testing: Impossible value STOP
[STOP] Impossible values: 1 impossible values detected
[PASS] Impossible value STOP: Validator correctly detected STOP
Testing: Foreign key STOP
[STOP] Foreign key integrity: 1 foreign key violations
  ('asteroid_clean', 1, 'asteroids', 0)
[PASS] Foreign key STOP: Validator correctly detected STOP
SELF-TEST RESULT: 3/3 passed
```

| Self-test | Fault injected into a temporary copy | Validator result |
|---|---|---|
| Row count | one `asteroid_clean` row deleted (5,033 → 5,032) | `[STOP] Row count equality` |
| Impossible value | `orbit_clean.eccentricity` set to 1.5 (CHECK constraints switched off on the copy) | `[STOP] Impossible values: 1` |
| Foreign key | `asteroid_clean.resolved_asteroid_key` set to a non-existent key 999999999 (foreign keys switched off on the copy) | `[STOP] Foreign key integrity: 1` |

### 6.3 Where each warning comes from

For each item a WARN reports, we say whether the cause is in **the world** (it is really so), in **the measurement** (how NASA observes or publishes it), or in **our pipeline** (something we did).

| WARN item | Value | Source | Explanation |
|---|---:|---|---|
| `asteroid_clean.designation` missing | 33 of 5,033 (0.66%) | **Measurement** | The feed endpoint does not send `designation`; these 33 asteroids appear only in feed files (I-01). |
| …earlier count 39 | 6 extra | **Our pipeline** (fixed) | The M2 loader kept the newest record per asteroid, and a newer feed record without the field replaced a browse record that had it. `load.py` now takes `designation` from the newest record that has it. Any earlier report of 39 is from before this fix. |
| All other missingness ratios | 0 | – | No other cleaned column is NULL: no value was invalid. |
| `no_approach_in_source` | 305 asteroids | **World** | Every raw record has an empty approach list; 255 of them are Amor asteroids, whose orbits stay outside Earth's (I-03). |
| `no_earth_approach` | 571 asteroids | **World** | The asteroid passes other bodies but never comes close to Earth in 1900–2200. |
| `predicted` approaches | 84,274 of 150,936 | **Measurement** | NASA lists computed approaches up to 2200. These are orbit predictions, not observations (I-04). |
| Latest approach date 2200-12-31 | – | **Measurement** | The end of NASA's fixed window, not a sign of fresh data. The earliest row (1899-12-31) is the other edge of that window seen in UTC (I-05). |
| Source freshness | not measurable | **Our pipeline** | All 360 raw files were retrieved on one day (2026-10-17), so we cannot tell how often NASA updates values. The validator reports coverage, not freshness. |

---

## 7. What we cannot say

- **Whether an asteroid will hit Earth.** `is_potentially_hazardous` is NASA's screening label (H and MOID thresholds), not an impact probability. Our project asks which features go with the label, nothing more.
- **Whether NASA considers the 15 `label_rule_mismatch` asteroids hazardous.** We know only that the label and today's H disagree. M4 must choose between the label as sent and the rule recomputed from H and MOID, and say which it used.
- **Anything about the size of an asteroid beyond H.** Diameter is computed from H with assumed albedos (I-11). It carries no independent information, and the true size of a dark or bright asteroid can be outside the given range.
- **That MOID and miss distance describe the same moment.** MOID is for today's orbit; approaches far in the past or future come from an orbit that has drifted (I-10). They must not be compared as if they were simultaneous.
- **That predicted approaches will happen as listed.** 56% of approaches are predictions. Their accuracy depends on orbit quality (`orbit_uncertainty`), which we did not model.
- **That approach statistics describe all asteroids.** 876 asteroids have no Earth approach. An average over approaches covers only the asteroids that come close, and those are more often hazardous (I-03).
- **That the 3 identity pairs are certainly the same object.** The evidence is strong but inferred. NASA did not confirm it.
- **How values change over time.** All raw data is from one retrieval day, so "latest version wins" has never been tested against a real update.
- **That our 5,033 asteroids represent all near-Earth asteroids.** The sample is what the browse pages and one feed week returned, not a random sample. Small, faint asteroids are under-represented in any survey.
- **That the 33 missing designations are truly unknown.** The designation can be read from the name, but M3 does not impute, so they stay NULL.

---

## 8. Fixed in M2

The profile found one bug in the M2 loader. It was fixed in `src/load.py`, not worked around in the cleaned layer.

| What | Effect before the fix | Fix | Found by |
|---|---|---|---|
| `load.py` lost `designation` for 6 asteroids | The loader keeps the newest record per asteroid. For 6 asteroids the newest record came from a feed file, which has no `designation` field, so the value from an older browse record was replaced by NULL: 39 missing instead of 33. | `designation` is now taken from the newest record that **has** the field. The profile (§2) checks that no designation present in any raw record is lost: 0. | Burak Avşar |

After the fix, the remaining 33 missing designations are absent in the source itself (I-01).
