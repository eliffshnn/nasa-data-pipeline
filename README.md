# NASA Near-Earth Asteroid Hazard Analysis



## Project Question



**Which asteroid features are linked to a “potentially hazardous” label?**



This project uses NASA's Near Earth Object Web Service (NeoWs) to collect data about near-Earth asteroids, their orbital characteristics, and close approaches. Asteroid, orbit, and close-approach data are connected using the asteroid ID to compare potentially hazardous and non-hazardous asteroids.



The project investigates which orbital and close-approach features are associated with the potentially hazardous label. A simple classifier will be developed in a later stage. Since the hazard label is built from absolute magnitude (H) and minimum orbit intersection distance (MOID), H, MOID, and diameter will not be used as model features. The hazard label is treated as a screening label, not an impact forecast.



---



## Data Sources



### NASA Near Earth Object Web Service (NeoWs)



The primary data source is NASA's Near Earth Object Web Service (NeoWs), a public REST API that provides JSON data about near-Earth asteroids.



The project uses the following NeoWs endpoints:



- **Browse** — provides the asteroid catalogue.

- **Feed** — provides close-approach data for a specified date range.

- **Lookup** — provides detailed information about an individual asteroid.



Official NASA API documentation:



https://api.nasa.gov/#asteroids-neows



Detailed source and provenance information is available in [`docs/sources.md`](docs/sources.md).



The API requires a NASA API key. The key must be provided through an environment variable and must never be committed to the repository.



### Data Entities



The project organizes the collected data into three entities, plus one table for records that cannot be loaded:



- **`asteroids`** — one row per asteroid.

- **`orbits`** — one row per asteroid orbit.

- **`approaches`** — one row per close-approach event.

- **`quarantine`** — one row per raw record that could not be loaded.



The entity tables are connected using the asteroid identifier.



The initial data collection target is at least 5,000 asteroids and their associated close-approach data.



---



## How to Run



### Prerequisites



- Python 3

- Git

- A NASA API key from the [NASA API portal](https://api.nasa.gov/) (only for ingestion, not for building the database)



### 1. Clone the repository



```bash

git clone https://github.com/se-220717030/nasa-data-pipeline.git

cd nasa-data-pipeline

```



### 2. Create a virtual environment



```bash

python -m venv .venv

```



### 3. Activate the virtual environment



**Windows:**



```powershell

.venv\Scripts\activate

```



**macOS / Linux:**



```bash

source .venv/bin/activate

```



### 4. Install dependencies



```bash

pip install -r requirements.txt

```



### 5. Configure the NASA API key



Create a local `.env` file in the repository root and configure the NASA API key using the environment variable expected by the ingestion script.



Check `.env.example` for the required variable name and format.



Never commit the `.env` file or expose API credentials in the repository.



### 6. Run the ingestion script (M1)



From the repository root, run:



```bash

python src/ingest.py

```



The ingestion script retrieves data from the approved NASA NeoWs endpoints and saves the raw responses in `data/raw/`.



Each run preserves the original responses and uses UTC retrieval timestamps in filenames. Subsequent runs create new files rather than overwriting previously retrieved files.



### 7. Build the database (M2)



From a fresh clone with landed raw data in `data/raw/`:



```bash

python src/load.py      *# builds data/asteroids.db from scratch; safe to run again*

python src/checks.py    *# runs the six checks on a temporary copy (see Checks below)*

```



`load.py` reads only the files in `data/raw/` and never calls the API. It creates `data/asteroids.db` if it does not exist. Running it again leaves the database unchanged.



---



## Repository Structure



```text

nasa-data-pipeline/

├── README.md

├── .gitignore

├── .env.example

├── requirements.txt

├── data/

│   └── raw/

├── docs/

│   └── sources.md

├── sql/

│   ├── schema.sql

│   └── queries/

└── src/

    ├── ingest.py

    ├── db.py

    ├── load.py

    ├── key_tests.py

    └── checks.py

```



### Directory and File Descriptions



| Path | Description |

|---|---|

| `README.md` | Project overview, data model, and instructions |

| `.gitignore` | Specifies files and directories Git should ignore |

| `.env.example` | Documents the required environment variables |

| `requirements.txt` | Lists the required Python dependencies |

| `data/raw/` | Stores raw data retrieved during ingestion |

| `data/asteroids.db` | Generated SQLite database; not committed to Git |

| `src/ingest.py` | Retrieves raw data from NASA NeoWs |

| `src/db.py` | Provides the shared `connect()` function and database initialization |

| `src/load.py` | Loads and validates raw data in the database |

| `src/key_tests.py` | Tests the key assumptions of the schema on the raw data |

| `src/checks.py` | Runs database integrity and loading checks |

| `sql/schema.sql` | Defines database tables, constraints, and indexes |

| `sql/queries/` | Stores analytical SQL queries |

| `docs/sources.md` | Documents data sources and provenance |



---



## Ingestion Scope — M1



Milestone M1 focuses on the ingestion stage of the data engineering lifecycle.



The ingestion script is designed to:



1. Retrieve data from the approved NASA NeoWs sources.

2. Save raw responses without cleaning, filtering, renaming, or reshaping them.

3. Include UTC retrieval timestamps in saved filenames.

4. Create new files on subsequent runs without overwriting previous files.

5. Read credentials from environment variables.

6. Handle request failures, timeouts, rate limits, and server errors.

7. Report the retrieved sources, record or file counts, and any errors.



Data cleaning, transformation, feature engineering, database loading, and machine learning are outside the scope of M1.



---



## Data Model — M2



Milestone M2 turns the landed raw files into a SQLite database that cannot contradict itself, refuses invalid data, and gives the same result however many times the load runs.



### ER diagram



```mermaid

erDiagram

    ASTEROIDS ||--o| ORBITS : "has at most one"

    ASTEROIDS ||--o{ APPROACHES : "has many"



    ASTEROIDS {

        INTEGER asteroid_key PK

        TEXT source_id UK

        TEXT name

        TEXT designation

        REAL absolute_magnitude_h

        INTEGER is_potentially_hazardous

        INTEGER is_sentry_object

        REAL diameter_min_km

        REAL diameter_max_km

        TEXT retrieved_at

    }

    ORBITS {

        INTEGER orbit_key PK

        TEXT source_id UK

        INTEGER asteroid_key FK

        REAL eccentricity

        REAL inclination

        REAL semi_major_axis

        TEXT orbit_determination_date

        TEXT retrieved_at

    }

    APPROACHES {

        INTEGER asteroid_key PK, FK

        INTEGER epoch_date_close_approach PK

        TEXT orbiting_body PK

        TEXT close_approach_date

        TEXT close_approach_date_full

        REAL relative_velocity_km_s

        REAL miss_distance_km

        TEXT retrieved_at

    }

    QUARANTINE {

        INTEGER quarantine_id PK

        TEXT reason

        TEXT raw_record

        TEXT retrieved_at

    }

```



`orbits` is shown with a subset of its columns; all columns are in `sql/schema.sql`. `quarantine` has no foreign key on purpose: it holds records whose entity we do not have.



### Grain of every table



- `asteroids`: one row is one near-Earth asteroid, identified by NASA's id.

- `orbits`: one row is the latest known orbital solution of one asteroid (at most one per asteroid).

- `approaches`: one row is one close approach of one asteroid to one body (Earth, Moon, ...) at one moment (epoch).

- `quarantine`: one row is one raw record that could not be loaded, with the reason.



### Schema



The schema is in `sql/schema.sql` and uses `CREATE TABLE IF NOT EXISTS` and `CREATE INDEX IF NOT EXISTS`, so it can be run repeatedly.



- All four tables are `STRICT`.

- Entity tables have a surrogate `INTEGER PRIMARY KEY`; NASA's id is kept as `source_id TEXT NOT NULL UNIQUE`.

- `approaches` has the composite primary key `(asteroid_key, epoch_date_close_approach, orbiting_body)`; every key column is `NOT NULL`.

- `orbits.asteroid_key` is `UNIQUE`, so an asteroid has at most one orbit row.

- Every relationship is a declared foreign key, and enforced: `connect()` in `src/db.py` runs `PRAGMA foreign_keys = ON` right after connecting, and every script uses it.

- Every table has `retrieved_at` (UTC), taken from the timestamp in the name of the raw file the row came from.

- Timestamps are ISO 8601 UTC text (`1901-08-23T17:36Z`); dates are zero-padded `YYYY-MM-DD`.

- Asteroid status flags are constrained to `0`, `1`, or `NULL`.



### The loader



`python src/load.py` reads every `.json` file in `data/raw/` (the `browse` shape, a list of asteroids; the `feed` shape, asteroids grouped by date; and the `lookup` shape, one asteroid object per file) and loads three entity/event tables plus quarantine.



File names carry the UTC retrieval time with or without microseconds (`20261017T123742Z`, `20261017T125321207719Z`). Both are read, and `retrieved_at` is always stored with six fractional digits (`2026-10-17T12:53:21.207719Z`) so that comparing the text gives the same order as comparing the times.



- **Deduplication by key, not by row.** Records are grouped by their key; the version with the latest `retrieved_at` wins. The decision uses the timestamp in the file name, never the order in which files are read.

- **Upserts.** All writes use `INSERT ... ON CONFLICT ... DO UPDATE` with a guard on `retrieved_at`. No `INSERT OR REPLACE` (it would change surrogate keys) and no `df.to_sql`.

- **Atomic.** The whole load runs in one transaction (`with con:`). A broken raw file stops the run before anything is written; an error during writing rolls everything back. The schema is created before the transaction starts.

- **Parameterised.** Every value reaches SQL through a `:name` or `?` placeholder.

- **Validation.** Text where a number belongs becomes `NULL` and is counted. Timestamps are converted to ISO 8601 UTC before insertion.



### Run summary



Output of two consecutive runs on a fresh database, built from the 360 landed raw files (256 browse, 4 feed, 100 lookup):



```text

# run 1

files read: 360 raw files (2026-10-17 .. 2026-10-17)

asteroids: 5,033 in database (+5033 this run)

orbits: 5,000 in database (+5000 this run)

approaches: 150,936 in database (+150936 this run)

values cleaned: 0 (non-numeric/invalid -> NULL)

quarantined: 0 in table (+0 this run)

foreign_key_check: OK

STATUS: COMPLETE



# run 2

files read: 360 raw files (2026-10-17 .. 2026-10-17)

asteroids: 5,033 in database (+0 this run)

orbits: 5,000 in database (+0 this run)

approaches: 150,936 in database (+0 this run)

values cleaned: 0 (non-numeric/invalid -> NULL)

quarantined: 0 in table (+0 this run)

foreign_key_check: OK

STATUS: COMPLETE

```



### Decisions and findings



**Keys.**

- Asteroid: surrogate `asteroid_key`; NASA's `id` is kept as `source_id`.

- Approach: `(asteroid_key, epoch_date_close_approach, orbiting_body)`. The epoch is an integer in milliseconds since 1970 (UTC), so no time-zone conversion is needed.

- Tests, run on the 360 landed raw files with `src/key_tests.py`:

  - Uniqueness: (asteroid id, epoch) alone is **not** unique: 15 pairs appear twice in the same file, once for Earth and once for the Moon (or Venus/Mars), with different miss distances. With (asteroid id, epoch, orbiting body) there are 0 duplicates, so the body is part of the key. Our first key, tested on 4 files from 2026-10-12, had missed this; with it, the loader silently kept only one of the two approaches.

  - Stability: 0 asteroids changed name between files, and 0 keys had more than one `miss_distance` value across files.

  - References: approaches and orbits are nested inside their asteroid in the source, so every one resolves by construction. The load confirmed it: 0 quarantined records and `foreign_key_check: OK`.

  - Limit of these tests: all raw files were retrieved on 2026-10-17, so they say little about how values change over several days. We will re-check once more retrievals exist.



**Missing values.** A field that is absent in the source is stored as `NULL` and means "not provided by the source", never zero. A value that is present but cannot be converted (for example text where a number belongs) is also stored as `NULL` and counted in the run summary as "values cleaned". In the current data this count is 0.



**Timestamps.** `close_approach_date_full` ("1901-Aug-23 17:36") and `orbit_determination_date` ("2026-10-11 06:57:01") are assumed to be UTC and stored as ISO 8601. If `close_approach_date` is invalid, it is derived from the epoch and counted as cleaned.



**Unknown references.** A record that points to an asteroid we do not have goes to the `quarantine` table with a reason and its raw JSON; it is neither dropped nor does it stop the load. Quarantine writes are idempotent (`UNIQUE` plus `ON CONFLICT DO NOTHING`). Because approaches and orbits arrive nested inside their asteroid, orphans are not expected; the quarantine mostly catches records without an id or with an invalid epoch. Current count: 0.



**Change over time.** We use type 1: the version with the latest `retrieved_at` wins. A renamed asteroid is updated in place and keeps its `asteroid_key`. M6 may revisit this.



**Known issues.**

- 33 of 5,033 asteroids have no orbit row. They appear only in `feed` files, which carry no `orbital_data`. The schema allows asteroids without orbits; the data can be completed later from the `lookup` endpoint.

- All 360 raw files were retrieved on 2026-10-17, so the "latest retrieval wins" rule has only been exercised within one day.

- Raw files come in three shapes (`browse`, `feed`, `lookup`); the loader handles all three.

- We have not checked whether `epoch_date_close_approach` and `close_approach_date_full` always describe the same instant.



### Checks



`src/checks.py` runs against a temporary copy of the database (never the real one) and reports PASS or FAIL for: duplicate natural key, orphan event, NULL key, wrong type, idempotence, and atomicity. It exits with code 1 if any check fails.



Checks 1–4 each have two parts: a **scan** that confirms the loaded data has no violation, and a **probe** that tries a deliberately bad write (a duplicate key, an approach for an unknown asteroid, a `NULL` key, text in a number column, a flag value of 7) and confirms that SQLite refuses it. The probe shows that the guarantee comes from the schema, not from the data happening to be clean. Probes run inside a savepoint and are rolled back.



- **Idempotence:** loads all raw files again into the copy and compares row counts and table contents before and after.

- **Atomicity:** (a) on a new empty database, a trigger makes the load fail after 1,000 approaches have been written; afterwards every table must be empty. (b) A broken JSON file is added to a copy of the raw folder; the load must stop before writing anything.



```text

$ python src/checks.py

checks on a temporary copy of asteroids.db: asteroids/orbits/approaches/quarantine = 5,033/5,000/150,936/0

PASS  1. duplicate natural key   duplicates: asteroids=0, orbits=0, approaches=0; duplicate insert rejected: True

PASS  2. orphan event            foreign_key_check rows=0, orphan rows=0; orphan insert rejected: True

PASS  3. NULL key                NULL key values=0; NULL key insert rejected: True

PASS  4. wrong type              rows with wrong type=0; text-in-number and bad flag rejected: True

PASS  5. idempotence             reloaded all raw files into the copy; before=5,033/5,000/150,936/0, after=5,033/5,000/150,936/0, identical=True

PASS  6. atomicity               failure after 1,000 approaches -> rows left=0; broken JSON file -> rows left=0

6/6 checks passed

```



### Analytical query



`sql/queries/asteroid_analysis.sql`:



```sql

*-- Question: How do potentially hazardous asteroids differ from non-hazardous ones*

*--           in their orbits and in their close approaches to Earth?*

*--*

*-- Result grain: one row per value of asteroids.is_potentially_hazardous (1 = hazardous, 0 = not).*

*--*

*-- Why the aggregation is correct at this grain:*

*--   approaches has many rows per asteroid (one per close approach), orbits has at most one.*

*--   Joining approaches straight onto asteroids and then averaging would weight every asteroid*

*--   by its number of approaches, and COUNT(*) would count approaches instead of asteroids.*

*--   So the CTE first collapses approaches to ONE row per asteroid (Earth approaches only),*

*--   and only then is it LEFT JOINed to asteroids and orbits. After the joins every row is still*

*--   one asteroid, so COUNT(*) counts asteroids and each AVG gives every asteroid equal weight.*

*--   LEFT JOINs keep asteroids without an orbit or without an Earth approach; AVG skips their NULLs,*

*--   and the n_with_* columns show how many asteroids each average is based on.*

*--   H, MOID and diameter define the hazard label, so they are deliberately left out.*



WITH earth_approaches AS (          *-- grain: one row per asteroid*

    SELECT

        asteroid_key,

        COUNT(*)                    AS n_approaches,

        MIN(miss_distance_km)       AS closest_miss_km,

        MAX(relative_velocity_km_s) AS fastest_km_s

    FROM approaches

    WHERE orbiting_body = 'Earth'

    GROUP BY asteroid_key

)

SELECT

    a.is_potentially_hazardous                       AS hazardous,

    COUNT(*)                                         AS n_asteroids,

    COUNT(o.asteroid_key)                            AS n_with_orbit,

    ROUND(AVG(o.eccentricity), 3)                    AS avg_eccentricity,

    ROUND(AVG(o.inclination), 1)                     AS avg_inclination_deg,

    ROUND(AVG(o.semi_major_axis), 2)                 AS avg_semi_major_axis_au,

    COUNT(e.asteroid_key)                            AS n_with_earth_approach,

    ROUND(AVG(e.n_approaches), 1)                    AS avg_earth_approaches,

    ROUND(AVG(e.closest_miss_km) / 1e6, 2)           AS avg_closest_miss_million_km,

    ROUND(AVG(e.fastest_km_s), 1)                    AS avg_fastest_km_s

FROM asteroids AS a

LEFT JOIN orbits AS o           ON o.asteroid_key = a.asteroid_key

LEFT JOIN earth_approaches AS e ON e.asteroid_key = a.asteroid_key

GROUP BY a.is_potentially_hazardous

ORDER BY hazardous DESC;

```



Result:



| hazardous | n_asteroids | n_with_orbit | avg_eccentricity | avg_inclination_deg | avg_semi_major_axis_au | n_with_earth_approach | avg_earth_approaches | avg_closest_miss_million_km | avg_fastest_km_s |

|---|---|---|---|---|---|---|---|---|---|

| 1 | 1046 | 1037 | 0.507 | 13.5 | 1.67 | 1030 | 30.6 | 6.26 | 22.6 |

| 0 | 3987 | 3963 | 0.453 | 16.2 | 1.82 | 3127 | 23.8 | 17.97 | 18.1 |



About 21% of the asteroids (1,046 of 5,033) are labelled potentially hazardous. On average they have more eccentric, slightly less inclined orbits, make more recorded Earth approaches, come about three times closer at their closest approach (6.3 vs 18.0 million km) and pass faster. Closest miss distance is related to MOID, which is part of the label's definition, so that difference is partly built into the label. This is a descriptive comparison, not a model.



---





## Planned Analysis



The completed M2 analytical query compares orbital and Earth close-approach characteristics between potentially hazardous and non-hazardous asteroids.



In a later project stage, a simple classifier will be developed to investigate whether the selected orbital and close-approach features can help distinguish the two hazard-label groups.



Absolute magnitude (H), minimum orbit intersection distance (MOID), and diameter will be excluded from predictive features, as specified in the project proposal.



Because potentially hazardous asteroids may be less common than non-hazardous asteroids, model evaluation will emphasize recall and PR-AUC rather than accuracy alone.



The objective is to investigate associations with a screening label, not to forecast asteroid impacts.



---



## Data Quality and Cleaning — M3

Milestone M3 adds a cleaned data layer while preserving the original M2 tables. The cleaning pipeline uses explicit quality flags and mapping tables so that source values and cleaning decisions remain traceable.

**Most important findings.** The data's main problems are about coverage, not bad values: 33 asteroids come only from the feed endpoint and have no designation and no orbit, 876 asteroids have no Earth close approach, and 56% of approaches are NASA predictions rather than observations. 15 asteroids are labelled hazardous although their H is just above NASA's 22.0 limit; we keep the label and flag them, because the label is our target variable. Three asteroids appear under two NASA ids and are resolved through a mapping table, and no impossible value was found by 17 physical rules. Every finding, decision, flag and constant is documented in [`docs/cleaning_report.md`](docs/cleaning_report.md).

### Cleaned tables

| Cleaned table | Source table | Rows |
|---|---|---:|
| `asteroid_clean` | `asteroids` | 5,033 |
| `orbit_clean` | `orbits` | 5,000 |
| `approach_clean` | `approaches` | 150,936 |

The cleaned layer includes missing-value flags, range and plausibility flags, standardised close-approach body names, asteroid identity resolution, approach coverage labels, and past/predicted timing labels. Raw values are retained in the cleaned tables alongside their cleaned counterparts where applicable.

### Cleaning pipeline

Run the cleaning pipeline from the repository root:

```bash
python src/clean.py
```

The pipeline rebuilds the cleaned tables transactionally. It is designed to be idempotent: consecutive runs produce the same row counts and do not modify the original M2 tables.

### Validation

Run the validation checks:

```bash
python src/validate.py
```

Run the STOP-condition self-tests on temporary copies of the database:

```bash
python src/validate.py --self-test
```

The validator includes the following checks:

| Check | Severity | Purpose |
|---|---|---|
| Raw/clean row-count equality | STOP | Detects missing or extra cleaned records |
| Impossible values | STOP | Detects values outside defined physical or numeric limits |
| Foreign-key integrity | STOP | Detects referential-integrity violations |
| Missingness ratios | WARN | Reports missing values in selected cleaned fields |
| Approach coverage and temporal range | WARN | Reports approach coverage, past/predicted records, and latest approach date |
| Body-name mapping completeness | WARN | Reports unmapped close-approach body names |

A STOP indicates a critical validation failure. WARN indicates a data-quality limitation that should be documented and reviewed; it does not by itself fail validation.

### Current validation results

The current validation run reports:

- **4 PASS**
- **2 WARN**
- **0 STOP**

The STOP self-test deliberately introduces each of the three critical failure types into separate temporary database copies. The validator detected all three conditions (**3/3 self-tests passed**). The production database is not modified by these tests.

### Known data-quality warnings

**Missing designation values:** 33 of 5,033 asteroid records (0.66%) have no designation value in the source. These values are retained as missing and flagged as `missing_not_in_source`; they are not inferred or fabricated. (An earlier run showed 39: the M2 loader lost 6 designations, which is fixed in `src/load.py`.)

**Approach coverage:** 4,157 asteroids are labelled `earth_approaches`, 305 are labelled `no_approach_in_source`, and 571 are labelled `no_earth_approach`. These categories distinguish missing source coverage from the absence of an Earth close-approach record.

**Temporal coverage and freshness:** The latest close-approach date in the current dataset is 2200-12-31. This is the latest event date represented in the approach data; it is not the NASA source's retrieval or update date. Therefore, the current check reports temporal coverage but does not establish source freshness.

**Body-name mapping:** The current validation found 0 unmapped body names and 16,125 standardised body-name records. Three duplicate asteroid identities were resolved using the identity mapping table.

### Idempotency results

The cleaning command was executed twice. Both runs completed with `STATUS: COMPLETE` and produced identical counts:

| Cleaned table | Run 1 | Run 2 |
|---|---:|---:|
| `asteroid_clean` | 5,033 | 5,033 |
| `orbit_clean` | 5,000 | 5,000 |
| `approach_clean` | 150,936 | 150,936 |

Both runs also reported `M2 tables unchanged: OK` and `foreign_key_check: OK`.

### M3 command summary

From a fresh clone with landed raw data in `data/raw/`:

```bash
python src/load.py
python src/clean.py
python src/validate.py
python src/validate.py --self-test
```

The outputs are retained as M3 execution evidence: `m3_clean_run1.txt`, `m3_clean_run2.txt`, `m3_validation.txt`, `m3_validation_selftest.txt` (and `m2_checks.txt` for M2). Every cleaning decision, flag, constant and mapping is documented in [`docs/cleaning_report.md`](docs/cleaning_report.md). The SQLite database remains a generated local artifact and should be submitted separately if required by the course; it should not be committed unless the project instructions explicitly require it.

---

## Team



- **Rana Yalçın** — `@se-220717030`

- **Burak Avşar** — `@se-220717054`

- **Elif Şahin** — `@se-230717060`



---



## Status



**M1 — Complete.** NASA NeoWs data ingestion is implemented. Raw API responses are preserved with UTC retrieval timestamps, and repeated runs create new files without overwriting previous data.



**M2 — Complete.** The SQLite schema, database connection utilities, idempotent loader, integrity checks, and analytical SQL query are implemented and tested. All six checks pass, including duplicate-key rejection, foreign-key integrity, type enforcement, idempotence, and atomicity.



The database contains 5,033 asteroids, 5,000 orbits, 150,936 close-approach records, and 0 quarantined records. The analytical query compares orbital and Earth close-approach characteristics between potentially hazardous and non-hazardous asteroids.


**M3 — cleaned layer and quality report complete.** `src/clean.py` builds `asteroid_clean`, `orbit_clean` and `approach_clean` from the M2 tables (idempotent, atomic, M2 tables unchanged); `src/validate.py` reports 4 PASS, 2 WARN, 0 STOP, and each STOP check was made to fail once (3/3). See [`docs/cleaning_report.md`](docs/cleaning_report.md).
