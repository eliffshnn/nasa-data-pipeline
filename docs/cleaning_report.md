# Cleaning Report — NASA Near-Earth Asteroid Hazard Analysis

**Milestone:** M3 (CLEAN) · **Team:** Rana Yalçın · Burak Avşar · Elif Şahin
**Data:** 360 raw NASA NeoWs files retrieved on 2026-10-17 → 5,033 asteroids, 5,000 orbits, 150,936 close approaches, 0 quarantined.

Build and check from a fresh clone with landed raw data:

```bash
python src/load.py
python src/clean.py
python src/validate.py
python src/validate.py --self-test
```

| File | Role |
|---|---|
| [`notebooks/m3_profile.ipynb`](../notebooks/m3_profile.ipynb) | Profile of the M2 database; the evidence for every issue (cited as §n) |
| [`sql/clean_schema.sql`](../sql/clean_schema.sql) | Cleaned tables (STRICT, foreign keys, `CHECK` on every flag), mapping tables, views for M4 |
| [`src/clean.py`](../src/clean.py) | Builds the cleaned layer from the M2 tables in one transaction |
| [`src/clean_config.py`](../src/clean_config.py) | Every threshold and constant (justified in section 5) |
| [`data/mappings/`](../data/mappings/) | Name and identity decisions as CSV (section 6) |
| [`src/validate.py`](../src/validate.py) | PASS / WARN / STOP checks; `--self-test` makes each STOP fail on purpose |

---

## 1. Summary

Our data is NASA's catalogue of near-Earth asteroids with their orbits and their close approaches to planets and the Moon between 1900 and 2200. The most important problems are about **coverage, not bad values**: 33 asteroids arrive only from the feed endpoint and have no designation and no orbit; 305 asteroids have no close approach at all and 571 none with Earth; and 56% of approaches are NASA's predictions, not observations. We also found 15 asteroids whose hazard label disagrees with NASA's own rule (H just above 22.0), three asteroids recorded under two NASA ids, two abbreviated body names (`Merc`, `Juptr`), and no impossible values: 17 of 18 physical rules found 0 violations. The cleaned layer (`asteroid_clean`, `orbit_clean`, `approach_clean`) has the same grain, keys and row counts as the M2 tables and keeps every raw value next to its cleaned value and a flag; nothing is deleted or imputed, and unusual values (e.g. a retrograde orbit) are flagged and kept. We still cannot say whether NASA considers the 15 mismatched asteroids hazardous, and MOID and miss distance cannot be compared as if they described the same moment.

**M2 issue fixed since the M2 tag:** the loader lost `designation` for 6 asteroids, because a newer feed record (which has no `designation` field) replaced an older browse record that had it. `src/load.py` now takes `designation` from the newest record that carries the field; missing designations went from 39 to 33, and the profile checks that no designation present in any raw record is lost (0, §2). Found by Burak Avşar.

---

## 2. Profile highlights

Full profile: [`notebooks/m3_profile.ipynb`](../notebooks/m3_profile.ipynb). It runs top to bottom on a fresh build. The tables below are the ones that led to findings.

**Entities by hazard label and orbit class (§1).** The 33 asteroids without an orbit (`none`) cannot be placed in an orbit class; 9 of them are labelled hazardous.

| Orbit class | Not hazardous | Hazardous | All |
|---|---:|---:|---:|
| AMO (Amor) | 1,918 | 61 | 1,979 |
| APO (Apollo) | 1,753 | 867 | 2,620 |
| ATE (Aten) | 287 | 107 | 394 |
| IEO (Atira) | 5 | 2 | 7 |
| none (no orbit) | 24 | 9 | 33 |
| **All** | **3,987** | **1,046** | **5,033** |

**Approaches per asteroid are very unequal (§1).** Median 16, maximum 473; 305 asteroids have none.

| Approaches per asteroid | AMO | APO | ATE | IEO | none | All |
|---|---:|---:|---:|---:|---:|---:|
| 0 | 255 | 48 | 2 | 0 | 0 | 305 |
| 1 | 186 | 197 | 0 | 1 | 33 | 417 |
| 2–10 | 720 | 517 | 7 | 0 | 0 | 1,244 |
| 11–100 | 815 | 1,733 | 195 | 2 | 0 | 2,745 |
| >100 | 3 | 125 | 190 | 4 | 0 | 322 |

**Which raw file shape carries which field (§2).** This table explains the missing designations and orbits.

| Field | browse | feed | lookup |
|---|:-:|:-:|:-:|
| `designation` | ✓ | ✗ | ✓ |
| `orbital_data` | ✓ | ✗ | ✓ |
| `name_limited` | ✓ | ✗ | ✓ |
| all other fields | ✓ | ✓ | ✓ |

**Hazard label vs NASA's rule H ≤ 22.0 and MOID ≤ 0.05 AU (§8).** 5,000 asteroids with an orbit:

| Label \ rule | Rule says no | Rule says yes |
|---|---:|---:|
| 0 | 3,963 | 0 |
| 1 | **15** | 1,022 |

**Robust z-score > 3.5 within each group (§9).**

| Column | Grouped by | Flagged | Share | High | Low |
|---|---|---:|---:|---:|---:|
| `orbits.eccentricity` | orbit class | 0 | 0.00% | 0 | 0 |
| `orbits.inclination` | orbit class | 121 | 2.42% | 121 | 0 |
| `orbits.semi_major_axis` | orbit class | 3 | 0.06% | 3 | 0 |
| `approaches.relative_velocity_km_s` | orbiting body | 642 | 0.43% | 642 | 0 |
| `approaches.miss_distance_km` (log10) | orbiting body | 2,502 | 1.66% | 0 | 2,502 |

We looked at what was flagged before believing it: key 1357 has a retrograde orbit (inclination 154°) and the fastest Venus passes (83 km/s); key 3177 has a = 17.8 AU. These are real objects.

---

## 3. Issues register

*Cause* says how we know: **Confirmed** (raw file contents or NASA documentation), **Inferred** (a pattern in the data supports it), or **Unknown**.

| ID | Family | Table.column | What | Where / when / how many | Evidence | Cause | Decision | Flag | Investigated by |
|---|---|---|---|---|---|---|---|---|---|
| I-01 | Missing | `asteroids.designation` | NULL | 33 asteroids, all only in the feed file (was 39 before the loader fix) | §2: field table above; 0 designations lost by the loader | **Confirmed**: the feed shape has no `designation` field | keep NULL; no imputation, although the name would give it; loader fixed in M2 | `missing_not_in_source` | Burak Avşar |
| I-02 | Missing | `orbits` (whole row) | no orbit row | the same 33 feed-only asteroids | §2: feed has no `orbital_data` | **Confirmed** | keep the asteroid; its hazard label cannot be checked against the rule | `unchecked_no_orbit` (on `is_potentially_hazardous`) | Burak Avşar |
| I-03 | Missing | `approaches` (whole asteroid) | no approach / no Earth approach | 305 / 571 asteroids; 255 of the 305 are Amor | §2: all 326 raw records of the 305 have an empty list | **Inferred**: the orbit never comes close enough to be listed (MNAR) | keep; label per asteroid | `approach_coverage` = `no_approach_in_source` / `no_earth_approach` | Burak Avşar |
| I-04 | Missing / coverage | `approaches` | future predictions | 84,274 of 150,936 rows (56%), 2026-10-17 to 2200-12-31 | §1: rows per decade | **Confirmed**: NASA lists approaches 1900–2200 | keep; label each row | `timing_flag` = `past` / `predicted` | Burak Avşar |
| I-05 | Invalid | `approaches.close_approach_date` | date outside 1900–2200 | 1 row, 1899-12-31T22:03Z, Earth | §6, §7 | **Inferred**: edge of NASA's window | keep, valid date | none | Burak Avşar |
| I-06 | Text | `approaches.orbiting_body` | abbreviations next to full names | `Merc` 8,569 + `Juptr` 7,556 = 16,125 rows | §4: `repr` of distinct values | **Confirmed**: NASA NeoWs codes | standardise via `orbiting_body.csv` | `standardised` | Rana Yalçın |
| I-07 | Text | `orbits.orbit_uncertainty` | ordered code 0–9 stored as text | 5,000 rows; 74% are `'0'` | §4 | **Confirmed**: NASA uncertainty parameter U | cleaned `INTEGER` column | `ok` / `invalid_not_a_code` (0) | Rana Yalçın |
| I-08 | Identity | `asteroids.source_id` | one asteroid under a provisional and a numbered id | 3 pairs, 6 rows, all from the one feed file | §5: same designation, H, approach minute and miss distance | **Inferred** | keep both rows; record in `asteroid_identity.csv`; resolve in `v_asteroid_clean` | `duplicate_id_resolved` | Rana Yalçın |
| I-09 | Cross-field | `asteroids.is_potentially_hazardous` | label 1, but H > 22.0 | 15 asteroids, H 22.01–22.57, MOID all ≤ 0.049 AU | §8: crosstab above | **Inferred**: H refined after the label was set; NASA's view **unknown** | keep the label as sent | `label_rule_mismatch` | Elif Şahin |
| I-10 | Cross-field | `approaches.miss_distance_km` vs `orbits.minimum_orbit_intersection` | Earth approach closer than the current MOID | 1,603 of 106,069 Earth approaches; 2.1% after 2100, 1.1–1.6% before | §8 | **Inferred**: the orbit drifts over centuries; MOID is for today's orbit | no flag on the value (both values are valid); documented for M4 | none | Elif Şahin |
| I-11 | Cross-field | `asteroids.diameter_min_km`, `diameter_max_km` | computed from H, not measured | all 5,033 | §3: ratio exactly √5; `D · 10^(H/5)` = 5,943.469 for every row | **Inferred** | keep in M2; not carried into the cleaned layer; not a model feature | none | Elif Şahin |
| I-12 | Unusual | `orbits.inclination`, `semi_major_axis`; `approaches.miss_distance_km`, `relative_velocity_km_s` | robust z > 3.5 in the group | 121 / 3 / 2,502 / 642 | §9: table above; flagged rows inspected | real objects (retrograde orbit, distant aphelion, closest passes) | flag and keep | `unusual_high` / `unusual_low` | Elif Şahin |

### Checked and not found

| Family | Check | Result |
|---|---|---|
| Missing | NULL in every column of all 3 tables (38 columns) | only `asteroids.designation` (§2) |
| Missing | records quarantined by the loader | 0 (§1) |
| Missing | designation present in a raw record but NULL in the database | 0 after the loader fix (§2) |
| Invalid | sentinels −9999, −999, −99, −1, 0, 99, 999, 9999 in every numeric column | 0 hits (§3) |
| Invalid | negative values in every numeric column | 0 (§3) |
| Invalid | 17 physical/definitional rules: 0 ≤ e < 1; 0 ≤ i ≤ 180; a > 0; q = a(1−e) and Q = a(1+e) within 0.001 AU; Kepler's period within 1%; mean motion × period = 360°; MOID ≥ 0; angles in [0, 360); orbit class matches its definition; orbit determined before retrieval; d_min ≤ d_max; d > 0; flags in {0, 1}; miss distance > 0; 0 < v < 100 km/s; Moon approaches within 0.01 AU | 0 violations each (§7) |
| Unusual | eccentricity, robust z per orbit class | 0 flagged (§9) |
| Across rows/fields | `close_approach_date` vs date of the epoch; `close_approach_date_full` vs the epoch to the minute | 0 mismatches in 150,936 rows (§6) |
| Across rows/fields | consecutive approaches of one asteroid to one body with an identical miss distance or velocity (stuck values) | 0 (§6) |
| Text | non-NFC strings, leading/trailing or double spaces, case variants in `name`, `designation`, `orbiting_body`, `orbit_class_*` | 0 (§4); the only non-ASCII character is `’` in the Apollo description, the same in all 2,620 rows |
| Identity | designation that disagrees with the name (`'144900 (2004 VG64)'` → `144900`) | 0 of 5,000 (§4) |

---

## 4. Missing values

| Pattern | Where / when | Mechanism | Evidence | What it means for M4 |
|---|---|---|---|---|
| No `designation` and no orbit (I-01, I-02) | 33 asteroids, all from the feed file of 2026-10-17 | **MAR** on the source shape: missingness depends entirely on which endpoint the asteroid was seen in, which is observed | every one of the 33 was loaded from a feed file; the feed shape has neither field; none has a browse or lookup record | These 33 have no orbital features and their label cannot be checked. They are a feed sample: asteroids with an approach in one week, so mostly close-passing objects. Exclude them from any analysis of orbital features, and say so; do not treat them as missing at random across all asteroids. |
| No approach at all (I-03) | 305 asteroids; 255 Amor, 48 Apollo, 2 Aten; 8 hazardous | **MNAR** (inferred): missing because of the value itself, an orbit that never comes close | the raw list is empty in all 326 records; 255 of 305 are Amor, whose orbits stay outside Earth's | "No event", not "unknown". A per-asteroid average over approaches silently drops these mostly non-hazardous asteroids, so approach statistics describe only asteroids that come close. Use `approach_coverage` to include them explicitly. |
| No Earth approach (I-03) | 571 more asteroids that approach other bodies only | **MNAR** (inferred), same reason | approaches exist, none with `orbiting_body = 'Earth'` | Same as above, for every Earth-only statistic (e.g. minimum Earth miss distance per asteroid). |
| Future approaches (I-04) | 84,274 rows after 2026-10-17 | not missing, but **not observed**: computed by NASA | NASA's fixed 1900–2200 window | Past and predicted approaches have different reliability. Compare them separately using `timing_flag`; never mix them in one "observed" count. |

No other column has a missing value (`validate.py`: 0.00% in every other checked column).

---

## 5. Flags and rules

One flag per value. `clean_value()` in `src/clean.py` tries the rules **in the order given**: the first rule that fires sets the flag, and later rules are not tried. A NULL raw value always gets `missing_not_reported` first, unless a more specific missing flag applies. **Invalid → NULL, unusual → kept, nothing imputed.** Counts are from `clean.py` (section 7).

Unusual values use the modified z-score `MAD_SCALE · (x − median) / MAD`, computed per orbit class (orbits) or per orbiting body (approaches), on valid values only, with the 3 duplicate asteroids left out so that they do not count twice (identity is resolved before any statistic). Miss distance is scored on log10 because it spans four orders of magnitude.

### 5.1 `asteroid_clean` (5,033 rows)

| Order | Column | Flag | Meaning | Rule (with constants) | Cleaned value | Count |
|---:|---|---|---|---|---|---:|
| 1 | `designation` | `missing_not_in_source` | the source shape has no such field | raw is NULL | NULL | 33 |
| 2 | | `invalid_inconsistent_with_name` | designation contradicts the name | designation ≠ number or bracket text of the name | NULL | 0 |
| – | | `ok` | | | raw | 5,000 |
| 1 | `absolute_magnitude_h` | `missing_not_reported` | NASA sent no value | raw is NULL | NULL | 0 |
| 2 | | `invalid_out_of_range` | H not physically possible for an NEA | not `H_MIN ≤ H ≤ H_MAX` (0–35) | NULL | 0 |
| – | | `ok` | | | raw | 5,033 |
| 1 | `is_potentially_hazardous` | `missing_not_reported` | NASA sent no label | raw is NULL | NULL | 0 |
| 2 | | `unchecked_no_orbit` | label cannot be compared with the rule | no MOID (no orbit row) or no valid H | raw (kept) | 33 |
| 3 | | `label_rule_mismatch` | label disagrees with NASA's own rule | label ≠ (H ≤ `PHA_H_MAX` and MOID ≤ `PHA_MOID_MAX_AU`) | raw (kept) | 15 |
| – | | `ok` | | | raw | 4,985 |
| – | `approach_coverage` | `earth_approaches` / `no_earth_approach` / `no_approach_in_source` | which approaches the source lists | ≥ 1 Earth approach / approaches, none with Earth / none | label | 4,157 / 571 / 305 |
| – | `identity_flag` | `duplicate_id_resolved` | provisional id of an asteroid also listed under its numbered id | `source_id` in `asteroid_identity.csv` | row kept; `resolved_asteroid_key` → numbered id | 3 |
| – | | `ok` | | | `resolved_asteroid_key = asteroid_key` | 5,030 |

### 5.2 `orbit_clean` (5,000 rows)

| Order | Column | Flag | Meaning | Rule (with constants) | Cleaned value | Count |
|---:|---|---|---|---|---|---:|
| 1 | `eccentricity` | `invalid_out_of_range` | not a closed orbit | not `0 ≤ e < ECCENTRICITY_MAX` | NULL | 0 |
| 2 | | `unusual_high` / `unusual_low` | extreme for its orbit class | \|z\| > `Z_LIMIT` | raw (kept) | 0 / 0 |
| 1 | `inclination` | `invalid_out_of_range` | not a valid angle | not `0 ≤ i ≤ INCLINATION_MAX_DEG` | NULL | 0 |
| 2 | | `unusual_high` / `unusual_low` | extreme for its orbit class | \|z\| > `Z_LIMIT` | raw (kept) | 121 / 0 (AMO 29, APO 89, ATE 3) |
| 1 | `semi_major_axis` | `invalid_out_of_range` | not a valid size | not `a > 0` | NULL | 0 |
| 2 | | `invalid_inconsistent` | contradicts perihelion and eccentricity | \|a(1 − e) − q\| > `AU_TOLERANCE` | NULL | 0 |
| 3 | | `unusual_high` / `unusual_low` | extreme for its orbit class | \|z\| > `Z_LIMIT` | raw (kept) | 3 / 0 (AMO 1, APO 2) |
| 1 | `minimum_orbit_intersection` | `invalid_negative` | a distance cannot be negative | MOID < 0 | NULL | 0 |
| 1 | `orbit_uncertainty` | `invalid_not_a_code` | not NASA's U parameter | not an integer in `UNCERTAINTY_CODES` (0–9) | NULL | 0 |

All other values are `ok`.

### 5.3 `approach_clean` (150,936 rows)

| Order | Column | Flag | Meaning | Rule (with constants) | Cleaned value | Count |
|---:|---|---|---|---|---|---:|
| – | `orbiting_body` | `standardised` | NASA abbreviation replaced by the full name | alias maps to a different name in `orbiting_body.csv` | full name | 16,125 |
| – | | `unmapped` | name not in the mapping | alias not in the CSV | NULL | 0 |
| 1 | `miss_distance_km` | `invalid_nonpositive` | a distance must be positive | d ≤ 0 | NULL | 0 |
| 2 | | `unusual_high` / `unusual_low` | extreme for its body | \|z\| of log10(d) > `Z_LIMIT` | raw (kept) | 0 / 2,502 |
| 1 | `relative_velocity_km_s` | `invalid_out_of_range` | faster than any possible encounter | not `0 < v < VELOCITY_MAX_KM_S` | NULL | 0 |
| 2 | | `unusual_high` / `unusual_low` | extreme for its body | \|z\| > `Z_LIMIT` | raw (kept) | 642 / 0 |
| – | `timing_flag` | `past` / `predicted` | observed or computed by NASA | date ≤ / > retrieval date (2026-10-17) | label | 66,662 / 84,274 |

### Constants

All defined once in `src/clean_config.py`. Changing one and running `python src/clean.py` again changes exactly the flags it controls.

- **`AU_KM = 149,597,870.7`**: the IAU 2012 exact definition of the astronomical unit. It is a definition, not a choice; it is only used to convert units.
- **`MAD_SCALE = 0.6745`**: makes the MAD comparable to a standard deviation for normal data, so that `Z_LIMIT` has its usual meaning. It is a statistical constant, not a choice.
- **`Z_LIMIT = 3.5`**: the cut-off recommended for the modified z-score by Iglewicz & Hoaglin (1993). A lower limit flags more values; every value flagged at 3.5 that we inspected was a real object, so a lower limit would only label more real objects as unusual. No value is removed at any limit.
- **`H_MIN, H_MAX = 0.0, 35.0`**: the brightest NEA has H ≈ 9 (Ganymed) and the faintest ever observed H ≈ 33; the data range is 9.17–30.10. Any upper limit above 30.10 gives the same 0 invalid values.
- **`INCLINATION_MAX_DEG = 180.0`**: inclination is defined on 0–180°. The data maximum is 154.35°; a lower limit would wrongly call the retrograde asteroid invalid.
- **`ECCENTRICITY_MAX = 1.0`**: e ≥ 1 is not a closed orbit around the Sun. The data maximum is 0.968.
- **`AU_TOLERANCE = 0.001` AU (~150,000 km)**: values carry 6+ decimals, so a larger gap between q and a(1 − e) cannot be rounding. The profile found 0 violations at this tolerance; tightening it towards the rounding level would start flagging rounding, not errors.
- **`VELOCITY_MAX_KM_S = 130.0`**: solar escape speed at Mercury (~67 km/s) plus Mercury's top orbital speed (~59 km/s), rounded up. The data maximum is 94.69 km/s (Mercury); any limit above that gives 0 invalid values.
- **`UNCERTAINTY_CODES = 0..9`**: NASA's orbit uncertainty parameter U is defined as an integer from 0 to 9. All 5,000 values are valid codes.
- **`PHA_H_MAX = 22.0`, `PHA_MOID_MAX_AU = 0.05`**: NASA/CNEOS definition of a potentially hazardous asteroid. These are NASA's numbers, not ours. Moving `PHA_H_MAX` to 22.6 would make all 15 mismatches disappear, which is why we say they fail "only just".

---

## 6. Mapping and identity decisions

Both decisions are stored as committed CSVs with `decided_by`, `decided_at` and a `note` with the evidence. `clean.py` loads them into `body_alias_map` and `asteroid_identity_map` and prints every CSV row that matched nothing. The CSVs map **source** names and ids; `clean.py` looks up the surrogate keys.

### 6.1 Orbiting body names — [`data/mappings/orbiting_body.csv`](../data/mappings/orbiting_body.csv)

| Step | What | Matched | Rows |
|---|---|---|---:|
| 1. Exact | already a standard name: `Earth`, `Venus`, `Mars`, `Moon` | 4 of 6 names | 134,811 |
| 2. Normalised key | NFC, strip, casefold | 0 new (no variants exist, §4) | 0 |
| 3. Fuzzy proposal | not needed: the 2 remaining names are NASA abbreviations, not misspellings | – | – |
| 4. Human decision | `Merc` → Mercury (velocities up to 95 km/s fit Mercury's 47 km/s orbital speed); `Juptr` → Jupiter (miss distances 7.8–299 million km match only Jupiter) | 2 of 6 names | 16,125 |
| Unmatched | | 0 | 0 |

Decided by Burak Avşar, 2026-11-06; investigated by Rana Yalçın (I-06). `clean.py`: `body_alias_map 6 rows · approach bodies matched 6 of 6`.

### 6.2 Asteroid identity — [`data/mappings/asteroid_identity.csv`](../data/mappings/asteroid_identity.csv)

| Step | What | Result |
|---|---|---|
| 1. Exact key | the provisional designation (the text in brackets in `name`) should belong to one `source_id` | 3 designations used by 2 ids each |
| 2. Evidence | compare H, label, approach time and miss distance of each pair | all 3 pairs agree (below) |
| 3. Human decision | resolve the provisional id (`3…`/`5…`) to the numbered id (`2…`) | 3 pairs resolved, 0 rejected |

| Provisional id | Numbered id | Designation | Evidence |
|---|---|---|---|
| 3430309 | 2614134 | 2008 TC4 | H 21.65 both; same approach 2026-10-17T04:02Z; identical miss distance |
| 3801936 | 2678976 | 2018 EH4 | H 21.67 / 21.68; same approach 2026-10-14T05:49Z; miss distance differs by 80 km (0.001%) |
| 54051300 | 2679786 | 2020 QG3 | H 21.22 both; same approach 2026-10-16T03:34Z; miss distance differs by 8 km |

Decided by Burak Avşar, 2026-11-06; investigated by Rana Yalçın (I-08). `clean.py`: `asteroid_identity_map 3 rows, matched 3 of 3`.

No row is merged, renamed or deleted: all six rows stay in `asteroid_clean` and the pairs are resolved in the views `v_asteroid_clean` and `v_approach_clean`. Identity is resolved before any median or MAD is computed (the 3 provisional ids are left out of the statistics). The match is **inferred** (NASA gives an unnumbered object a `3…`/`5…` id and a new `2…` id once it is numbered, and the feed returned both); reverting it means deleting one CSV line.

---

## 7. Counts and validation

### 7.1 `python src/clean.py`

Run twice in a row (`m3_clean_run1.txt`, `m3_clean_run2.txt`); the two outputs are identical line for line. Both report `M2 tables unchanged: OK` (SHA-256 of every M2 table before and after), `row counts equal raw: OK` and `foreign_key_check: OK`. The `·` separator in the `mappings:` line appears as `┬À` in the saved files because of the Windows console code page; it is shown corrected here.

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

### 7.2 `python src/validate.py`

Result: **4 PASS, 2 WARN, 0 STOP** (`m3_validation.txt`). `validate.py` exits non-zero when any STOP fails.

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

### 7.3 Each WARN: world, measurement or pipeline?

| WARN item | Value | Source | Explanation |
|---|---:|---|---|
| `asteroid_clean.designation` missing | 33 of 5,033 (0.66%) | **Measurement** | The feed endpoint does not send the field (I-01). |
| …earlier count 39 | 6 more | **Our pipeline** (fixed) | The M2 loader replaced a known designation with NULL; fixed in `load.py` (section 1). |
| all other missingness ratios | 0.00% | – | No other cleaned value is NULL: no value was invalid. |
| `no_approach_in_source` | 305 asteroids | **World** | Their orbits never bring them close enough in 1900–2200 (I-03). |
| `no_earth_approach` | 571 asteroids | **World** | They pass other bodies but never Earth. |
| `predicted` approaches | 84,274 of 150,936 | **Measurement** | NASA computes approaches up to 2200; they are predictions (I-04). |
| latest approach 2200-12-31 | – | **Measurement** | The end of NASA's window, not a sign of fresh data (I-05 is the other edge). |
| source freshness | not measurable | **Our pipeline** | All 360 raw files were retrieved on one day, so we cannot tell how often NASA updates values. |

### 7.4 Each STOP made to fail once

`python src/validate.py --self-test` copies the database to a temporary file, breaks it in one way, runs the full validator on the copy, and expects STOP and a non-zero exit. The real database is not touched. Result: **3/3** (`m3_validation_selftest.txt`).

| STOP check | How it was made to fail | Result |
|---|---|---|
| Row count equality | deleted the `asteroid_clean` row with the smallest key (5,033 → 5,032) | `[STOP] Row count equality: asteroids=5033, asteroid_clean=5032` |
| Impossible values | set `orbit_clean.eccentricity = 1.5` on one row (with `CHECK` constraints switched off on the copy) | `[STOP] Impossible values: 1 impossible values detected` |
| Foreign-key integrity | set `asteroid_clean.resolved_asteroid_key = 999999999` on one row (with foreign keys switched off on the copy) | `[STOP] Foreign key integrity: 1 foreign key violations` |

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

---

## 8. What we can't say

- **Whether an asteroid will hit Earth.** `is_potentially_hazardous` is NASA's screening label (H and MOID thresholds), not an impact probability. Our project asks which features go with the label, nothing more.
- **Whether NASA considers the 15 `label_rule_mismatch` asteroids hazardous.** We know only that the label and today's H disagree. M4 must choose between the label as sent and the rule recomputed from H and MOID, and say which it used, because the label is our target variable.
- **Anything about size beyond H.** Diameter is computed from H with assumed albedos (I-11). It adds no information, and a real asteroid's size can be outside the given range.
- **That MOID and miss distance describe the same moment.** MOID is for today's orbit; approaches far in the past or future come from an orbit that has drifted (I-10).
- **That predicted approaches will happen as listed.** 56% of approaches are predictions; their accuracy depends on orbit quality (`orbit_uncertainty`), which we did not model.
- **That approach statistics describe all asteroids.** 876 asteroids have no Earth approach. An average over approaches covers only asteroids that come close, and those are more often hazardous (section 4).
- **Anything about the orbits of the 33 feed-only asteroids.** They have no orbit row; 9 of them are labelled hazardous, and we cannot check those labels.
- **That the 3 identity pairs are certainly the same object.** The evidence is strong but inferred; NASA did not confirm it.
- **How values change over time.** All raw data is from one retrieval day, so "latest version wins" has never met a real update, and source freshness cannot be measured. We would revisit this with retrievals on several days.
- **That our 5,033 asteroids represent all near-Earth asteroids.** The sample is what the browse pages and one feed week returned, not a random sample; small, faint asteroids are under-represented in any survey.
