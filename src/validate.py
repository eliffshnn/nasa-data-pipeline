
import shutil
import sqlite3
import sys
import tempfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "asteroids.db"


def connect(db_path):
    connection = sqlite3.connect(db_path)
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def print_result(status, name, detail):
    print(f"[{status}] {name}: {detail}")


# Fixed SQL only: no table or column name is ever formatted into a statement.
ROW_COUNT_SQL = [
    ("asteroids", "SELECT COUNT(*) FROM asteroids",
     "asteroid_clean", "SELECT COUNT(*) FROM asteroid_clean"),
    ("orbits", "SELECT COUNT(*) FROM orbits",
     "orbit_clean", "SELECT COUNT(*) FROM orbit_clean"),
    ("approaches", "SELECT COUNT(*) FROM approaches",
     "approach_clean", "SELECT COUNT(*) FROM approach_clean"),
]

# One fixed query per cleaned table: total rows, then NULL count per column (in the order of the names).
MISSINGNESS_SQL = [
    ("asteroid_clean",
     ["designation", "absolute_magnitude_h", "is_potentially_hazardous"],
     """SELECT COUNT(*),
               SUM(designation IS NULL),
               SUM(absolute_magnitude_h IS NULL),
               SUM(is_potentially_hazardous IS NULL)
        FROM asteroid_clean"""),
    ("orbit_clean",
     ["eccentricity", "inclination", "semi_major_axis",
      "minimum_orbit_intersection", "orbit_uncertainty"],
     """SELECT COUNT(*),
               SUM(eccentricity IS NULL),
               SUM(inclination IS NULL),
               SUM(semi_major_axis IS NULL),
               SUM(minimum_orbit_intersection IS NULL),
               SUM(orbit_uncertainty IS NULL)
        FROM orbit_clean"""),
    ("approach_clean",
     ["orbiting_body", "miss_distance_km", "relative_velocity_km_s"],
     """SELECT COUNT(*),
               SUM(orbiting_body IS NULL),
               SUM(miss_distance_km IS NULL),
               SUM(relative_velocity_km_s IS NULL)
        FROM approach_clean"""),
]


def check_row_counts(connection):
    problems = []

    for raw_table, raw_sql, clean_table, clean_sql in ROW_COUNT_SQL:
        raw_count = connection.execute(raw_sql).fetchone()[0]
        clean_count = connection.execute(clean_sql).fetchone()[0]

        print(
            f"  {raw_table}: {raw_count:,} | "
            f"{clean_table}: {clean_count:,}"
        )

        if raw_count != clean_count:
            problems.append(
                f"{raw_table}={raw_count}, {clean_table}={clean_count}"
            )

    if problems:
        print_result("STOP", "Row count equality", "; ".join(problems))
        return "STOP"

    print_result(
        "PASS",
        "Row count equality",
        "All raw and clean counts match",
    )
    return "PASS"


def check_impossible_values(connection):
    checks = {
        "asteroid_clean": """
            SELECT COUNT(*) FROM asteroid_clean
            WHERE
                (absolute_magnitude_h IS NOT NULL
                 AND (absolute_magnitude_h < 0
                      OR absolute_magnitude_h > 35))
                OR
                (is_potentially_hazardous IS NOT NULL
                 AND is_potentially_hazardous NOT IN (0, 1))
        """,
        "orbit_clean": """
            SELECT COUNT(*) FROM orbit_clean
            WHERE
                (eccentricity IS NOT NULL
                 AND (eccentricity < 0 OR eccentricity >= 1))
                OR
                (inclination IS NOT NULL
                 AND (inclination < 0 OR inclination > 180))
                OR
                (semi_major_axis IS NOT NULL
                 AND semi_major_axis <= 0)
                OR
                (minimum_orbit_intersection IS NOT NULL
                 AND minimum_orbit_intersection < 0)
                OR
                (orbit_uncertainty IS NOT NULL
                 AND orbit_uncertainty NOT BETWEEN 0 AND 9)
        """,
        "approach_clean": """
            SELECT COUNT(*) FROM approach_clean
            WHERE
                (miss_distance_km IS NOT NULL
                 AND miss_distance_km <= 0)
                OR
                (relative_velocity_km_s IS NOT NULL
                 AND (relative_velocity_km_s <= 0
                      OR relative_velocity_km_s >= 130))
        """,
    }

    total = 0

    for table, query in checks.items():
        count = connection.execute(query).fetchone()[0]
        print(f"  {table}: {count} impossible values")
        total += count

    if total:
        print_result(
            "STOP",
            "Impossible values",
            f"{total} impossible values detected",
        )
        return "STOP"

    print_result(
        "PASS",
        "Impossible values",
        "No impossible values detected",
    )
    return "PASS"


def check_foreign_keys(connection):
    violations = connection.execute(
        "PRAGMA foreign_key_check"
    ).fetchall()

    if violations:
        print_result(
            "STOP",
            "Foreign key integrity",
            f"{len(violations)} foreign key violations",
        )

        for violation in violations[:5]:
            print(f"  {violation}")

        return "STOP"

    print_result(
        "PASS",
        "Foreign key integrity",
        "foreign_key_check returned no violations",
    )
    return "PASS"


def check_missingness(connection):
    print("  Missingness ratios:")

    for table, fields, sql in MISSINGNESS_SQL:
        total, *missing_counts = connection.execute(sql).fetchone()

        for field, missing in zip(fields, missing_counts):
            missing = missing or 0  # SUM over an empty table is NULL
            ratio = missing / total if total else 0

            print(
                f"    {table}.{field}: "
                f"{missing:,}/{total:,} ({ratio:.2%})"
            )

    print_result(
        "WARN",
        "Missingness",
        "Missing values are reported for data-quality review",
    )
    return "WARN"


def check_coverage_and_freshness(connection):
    print("  Approach coverage:")

    coverage = connection.execute("""
        SELECT approach_coverage, COUNT(*)
        FROM asteroid_clean
        GROUP BY approach_coverage
        ORDER BY approach_coverage
    """).fetchall()

    for label, count in coverage:
        print(f"    {label}: {count:,}")

    print("  Approach timing:")

    timing = connection.execute("""
        SELECT timing_flag, COUNT(*)
        FROM approach_clean
        GROUP BY timing_flag
        ORDER BY timing_flag
    """).fetchall()

    for label, count in timing:
        print(f"    {label}: {count:,}")

    latest_epoch = connection.execute("""
        SELECT MAX(epoch_date_close_approach)
        FROM approach_clean
    """).fetchone()[0]

    if latest_epoch is not None:
        latest_date = datetime.fromtimestamp(
            latest_epoch / 1000,
            tz=timezone.utc,
        ).date()

        print(f"  Latest approach date (UTC): {latest_date}")
    else:
        print("  Latest approach date: unavailable")

    print_result(
        "WARN",
        "Coverage and freshness",
        "Coverage, timing, and latest approach date reported for review",
    )
    return "WARN"


def check_project_specific(connection):
    unmapped = connection.execute("""
        SELECT COUNT(*)
        FROM approach_clean
        WHERE orbiting_body_flag = 'unmapped'
    """).fetchone()[0]

    standardised = connection.execute("""
        SELECT COUNT(*)
        FROM approach_clean
        WHERE orbiting_body_flag = 'standardised'
    """).fetchone()[0]

    resolved_duplicates = connection.execute("""
        SELECT COUNT(*)
        FROM asteroid_clean
        WHERE identity_flag = 'duplicate_id_resolved'
    """).fetchone()[0]

    print(f"  Unmapped body names: {unmapped:,}")
    print(f"  Standardised body names: {standardised:,}")
    print(f"  Resolved duplicate identities: {resolved_duplicates:,}")

    if unmapped:
        print_result(
            "WARN",
            "Mapping completeness",
            f"{unmapped} approach records have unmapped body names",
        )
        return "WARN"

    print_result(
        "PASS",
        "Mapping completeness",
        "All approach body names are mapped",
    )
    return "PASS"


def run_validation(db_path):
    print("\n" + "=" * 60)
    print("NASA ASTEROID DATA PIPELINE - M3 VALIDATION")
    print("=" * 60)

    # closing() ensures the SQLite connection is closed on Windows.
    with closing(connect(db_path)) as connection:
        results = [
            check_row_counts(connection),
            check_impossible_values(connection),
            check_foreign_keys(connection),
            check_missingness(connection),
            check_coverage_and_freshness(connection),
            check_project_specific(connection),
        ]

    print("\n" + "-" * 60)
    print("VALIDATION SUMMARY")
    print("-" * 60)

    for status in ("PASS", "WARN", "STOP"):
        print(f"{status}: {results.count(status)}")

    if "STOP" in results:
        print("\nSTATUS: STOP")
        return 1

    if "WARN" in results:
        print("\nSTATUS: PASS WITH WARNINGS")
    else:
        print("\nSTATUS: PASS")

    return 0


def run_self_test():
    print("\n" + "=" * 60)
    print("M3 VALIDATOR STOP SELF-TEST")
    print("=" * 60)

    tests = [
        (
            "Row count STOP",
            """
            DELETE FROM asteroid_clean
            WHERE asteroid_key = (
                SELECT MIN(asteroid_key) FROM asteroid_clean
            );
            """,
        ),
        (
            "Impossible value STOP",
            """
            PRAGMA ignore_check_constraints = ON;

            UPDATE orbit_clean
            SET eccentricity = 1.5
            WHERE orbit_key = (
                SELECT MIN(orbit_key) FROM orbit_clean
            );
            """,
        ),
        (
            "Foreign key STOP",
            """
            PRAGMA foreign_keys = OFF;

            UPDATE asteroid_clean
            SET resolved_asteroid_key = 999999999
            WHERE asteroid_key = (
                SELECT MIN(asteroid_key) FROM asteroid_clean
            );
            """,
        ),
    ]

    passed = 0

    with tempfile.TemporaryDirectory() as temp_dir:
        for index, (name, mutation) in enumerate(tests, start=1):
            temp_db = Path(temp_dir) / f"broken_test_{index}.db"
            shutil.copy2(DB_PATH, temp_db)

            # Close the mutation connection before validation starts.
            with closing(sqlite3.connect(temp_db)) as connection:
                connection.executescript(mutation)
                connection.commit()

            print(f"\nTesting: {name}")

            exit_code = run_validation(temp_db)

            if exit_code == 1:
                print_result(
                    "PASS",
                    name,
                    "Validator correctly detected STOP",
                )
                passed += 1
            else:
                print_result(
                    "FAIL",
                    name,
                    "Validator did not detect STOP",
                )

    print("\n" + "=" * 60)
    print(f"SELF-TEST RESULT: {passed}/{len(tests)} passed")
    print("=" * 60)

    return 0 if passed == len(tests) else 1


if __name__ == "__main__":
    if not DB_PATH.exists():
        print(f"ERROR: Database not found: {DB_PATH}")
        sys.exit(1)

    if "--self-test" in sys.argv:
        sys.exit(run_self_test())

    sys.exit(run_validation(DB_PATH))
