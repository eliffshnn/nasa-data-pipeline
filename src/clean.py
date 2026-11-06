"""M2 tables -> cleaned layer (sql/clean_schema.sql).

Reads only the M2 tables and the committed CSVs in data/mappings/; never the raw files or the API.
Never writes to an M2 table: a fingerprint of every M2 table is taken before and after, and the run fails if they differ.
The cleaned tables are rebuilt from scratch inside one transaction, so a run is idempotent and atomic.

Run from the repository root:  python src/load.py && python src/clean.py
"""
import csv
import hashlib
import math
import statistics
import sys
from collections import Counter, defaultdict

import clean_config as C
from db import DB_PATH, PROJECT_ROOT as ROOT, connect

CLEAN_SCHEMA = ROOT / "sql" / "clean_schema.sql"
MAPPINGS = ROOT / "data" / "mappings"

# Fixed SQL only: no table or column name is ever formatted into a statement.
M2_DUMPS = {
    "asteroids": "SELECT * FROM asteroids ORDER BY asteroid_key",
    "orbits": "SELECT * FROM orbits ORDER BY orbit_key",
    "approaches": "SELECT * FROM approaches ORDER BY asteroid_key, epoch_date_close_approach, orbiting_body",
    "quarantine": "SELECT * FROM quarantine ORDER BY quarantine_id",
}
CLEAR = [  # children before parents
    "DELETE FROM approach_clean",
    "DELETE FROM orbit_clean",
    "DELETE FROM asteroid_clean",
    "DELETE FROM asteroid_identity_map",
    "DELETE FROM body_alias_map",
]
COUNTS = {
    "asteroid_clean": ("SELECT COUNT(*) FROM asteroid_clean", "SELECT COUNT(*) FROM asteroids"),
    "orbit_clean": ("SELECT COUNT(*) FROM orbit_clean", "SELECT COUNT(*) FROM orbits"),
    "approach_clean": ("SELECT COUNT(*) FROM approach_clean", "SELECT COUNT(*) FROM approaches"),
}


def m2_fingerprint(con):
    """SHA-256 of every row of every M2 table, in key order."""
    out = {}
    for table, sql in M2_DUMPS.items():
        h = hashlib.sha256()
        for row in con.execute(sql):
            h.update(repr(row).encode("utf-8"))
        out[table] = h.hexdigest()
    return out


def read_csv(name, columns):
    with open(MAPPINGS / name, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        missing = [c for c in columns if not (r.get(c) or "").strip()]
        if missing:
            raise ValueError(f"{name}: empty {missing} in row {r}")
    return rows


# ------------------------------------------------------------------ robust statistics

def group_stats(values_by_group):
    """median and MAD per group."""
    stats = {}
    for g, vals in values_by_group.items():
        med = statistics.median(vals)
        stats[g] = (med, statistics.median(abs(v - med) for v in vals))
    return stats


def unusual(value, group, stats):
    """'unusual_high' / 'unusual_low' / None, by the modified z-score within the group."""
    med, mad = stats.get(group, (None, 0))
    if value is None or not mad:
        return None
    z = C.MAD_SCALE * (value - med) / mad
    if z > C.Z_LIMIT:
        return "unusual_high"
    if z < -C.Z_LIMIT:
        return "unusual_low"
    return None


def clean_value(raw, rules):
    """Apply rules in order; the first that fires sets the flag. Invalid -> NULL, unusual -> kept."""
    if raw is None:
        return None, "missing_not_reported"
    for flag, fires in rules:
        if flag and fires:  # unusual() returns None when the value is not unusual
            return (None if flag.startswith("invalid") else raw), flag
    return raw, "ok"


def designation_from_name(name):
    """'144900 (2004 VG64)' -> '144900';  '(2002 TH68)' -> '2002 TH68'  (rule checked in the profile, section 4)."""
    head = name.split(" ", 1)[0]
    if head.isdigit():
        return head
    if name.startswith("(") and name.endswith(")"):
        return name[1:-1]
    return None


# ------------------------------------------------------------------ build

def build(con):
    summary = {"unmatched": []}

    # ---- mapping tables from the committed CSVs
    bodies = read_csv("orbiting_body.csv", ["alias", "name", "decided_by", "decided_at", "note"])
    identity = read_csv("asteroid_identity.csv", ["source_id", "resolved_source_id", "decided_by", "decided_at", "note"])
    con.executemany("INSERT INTO body_alias_map (alias, name, decided_by, decided_at, note) "
                    "VALUES (:alias, :name, :decided_by, :decided_at, :note)", bodies)
    con.executemany("INSERT INTO asteroid_identity_map (source_id, resolved_source_id, decided_by, decided_at, note) "
                    "VALUES (:source_id, :resolved_source_id, :decided_by, :decided_at, :note)", identity)
    body_name = {b["alias"]: b["name"] for b in bodies}

    # ---- read M2
    ast = con.execute("SELECT asteroid_key, source_id, name, designation, absolute_magnitude_h, "
                      "is_potentially_hazardous, retrieved_at FROM asteroids").fetchall()
    key_of = {sid: k for k, sid, *_ in ast}
    orbits = con.execute("SELECT orbit_key, asteroid_key, orbit_class_type, eccentricity, inclination, "
                         "semi_major_axis, perihelion_distance, minimum_orbit_intersection, orbit_uncertainty "
                         "FROM orbits").fetchall()
    moid_of = {o[1]: o[7] for o in orbits}
    retrieval_date = con.execute("SELECT MAX(retrieved_at) FROM asteroids").fetchone()[0][:10]

    # ---- identity: resolve before any statistic
    resolved = {k: k for k, *_ in ast}
    identity_flag = {k: "ok" for k, *_ in ast}
    matched_identity = 0
    for m in identity:
        src, dst = key_of.get(m["source_id"]), key_of.get(m["resolved_source_id"])
        if src is None or dst is None:
            summary["unmatched"].append(f"asteroid_identity {m['source_id']}->{m['resolved_source_id']}")
            continue
        resolved[src], identity_flag[src] = dst, "duplicate_id_resolved"
        matched_identity += 1
    duplicate_keys = {k for k, f in identity_flag.items() if f != "ok"}

    # ---- approach coverage per asteroid
    n_any, n_earth = Counter(), Counter()
    for k, body in con.execute("SELECT asteroid_key, orbiting_body FROM approaches"):
        n_any[k] += 1
        n_earth[k] += body == "Earth"

    # ---- asteroid_clean
    rows = []
    for k, sid, name, des, h, haz, _ in ast:
        des_c, des_f = clean_value(des, [("invalid_inconsistent_with_name",
                                          des is not None and designation_from_name(name) not in (None, des))])
        if des is None:
            des_f = "missing_not_in_source"  # feed records carry no designation field (profile section 2)
        h_c, h_f = clean_value(h, [("invalid_out_of_range", h is not None and not C.H_MIN <= h <= C.H_MAX)])
        moid = moid_of.get(k)
        rule = (h_c is not None and moid is not None
                and h_c <= C.PHA_H_MAX and moid <= C.PHA_MOID_MAX_AU)
        haz_c, haz_f = clean_value(haz, [("unchecked_no_orbit", moid is None or h_c is None),
                                         ("label_rule_mismatch", haz is not None and bool(haz) != rule)])
        coverage = ("earth_approaches" if n_earth[k] else
                    "no_earth_approach" if n_any[k] else "no_approach_in_source")
        rows.append({"k": k, "des_raw": des, "des": des_c, "des_f": des_f,
                     "h_raw": h, "h": h_c, "h_f": h_f,
                     "haz_raw": haz, "haz": haz_c, "haz_f": haz_f,
                     "cov": coverage, "res": resolved[k], "id_f": identity_flag[k]})
    con.executemany(
        "INSERT INTO asteroid_clean (asteroid_key, designation_raw, designation, designation_flag, "
        "absolute_magnitude_h_raw, absolute_magnitude_h, absolute_magnitude_h_flag, "
        "is_potentially_hazardous_raw, is_potentially_hazardous, is_potentially_hazardous_flag, "
        "approach_coverage, resolved_asteroid_key, identity_flag) "
        "VALUES (:k, :des_raw, :des, :des_f, :h_raw, :h, :h_f, :haz_raw, :haz, :haz_f, :cov, :res, :id_f)", rows)
    summary["asteroid_clean"] = rows

    # ---- orbit_clean: robust statistics per orbit class, on valid values of non-duplicate asteroids
    def valid_e(e): return e is not None and 0 <= e < C.ECCENTRICITY_MAX
    def valid_i(i): return i is not None and 0 <= i <= C.INCLINATION_MAX_DEG
    def valid_a(a): return a is not None and a > 0

    groups = {"e": defaultdict(list), "i": defaultdict(list), "a": defaultdict(list)}
    for _, k, cls, e, i, a, *_ in orbits:
        if k in duplicate_keys:
            continue
        if valid_e(e):
            groups["e"][cls].append(e)
        if valid_i(i):
            groups["i"][cls].append(i)
        if valid_a(a):
            groups["a"][cls].append(a)
    st = {name: group_stats(g) for name, g in groups.items()}

    rows = []
    for ok_, k, cls, e, i, a, q, moid, unc in orbits:
        e_c, e_f = clean_value(e, [("invalid_out_of_range", not valid_e(e)),
                                   (unusual(e, cls, st["e"]), True)])
        i_c, i_f = clean_value(i, [("invalid_out_of_range", not valid_i(i)),
                                   (unusual(i, cls, st["i"]), True)])
        inconsistent = (valid_a(a) and valid_e(e) and q is not None
                        and abs(a * (1 - e) - q) > C.AU_TOLERANCE)
        a_c, a_f = clean_value(a, [("invalid_out_of_range", not valid_a(a)),
                                   ("invalid_inconsistent", inconsistent),
                                   (unusual(a, cls, st["a"]), True)])
        m_c, m_f = clean_value(moid, [("invalid_negative", moid is not None and moid < 0)])
        code = int(unc) if unc is not None and unc.strip().isdigit() else None
        u_c, u_f = clean_value(unc, [("invalid_not_a_code", code not in C.UNCERTAINTY_CODES)])
        rows.append({"ok": ok_, "k": k, "e_raw": e, "e": e_c, "e_f": e_f, "i_raw": i, "i": i_c, "i_f": i_f,
                     "a_raw": a, "a": a_c, "a_f": a_f, "m_raw": moid, "m": m_c, "m_f": m_f,
                     "u_raw": unc, "u": code if u_c is not None else None, "u_f": u_f})
    con.executemany(
        "INSERT INTO orbit_clean (orbit_key, asteroid_key, eccentricity_raw, eccentricity, eccentricity_flag, "
        "inclination_raw, inclination, inclination_flag, semi_major_axis_raw, semi_major_axis, semi_major_axis_flag, "
        "minimum_orbit_intersection_raw, minimum_orbit_intersection, minimum_orbit_intersection_flag, "
        "orbit_uncertainty_raw, orbit_uncertainty, orbit_uncertainty_flag) "
        "VALUES (:ok, :k, :e_raw, :e, :e_f, :i_raw, :i, :i_f, :a_raw, :a, :a_f, :m_raw, :m, :m_f, :u_raw, :u, :u_f)",
        rows)
    summary["orbit_clean"] = rows

    # ---- approach_clean: robust statistics per orbiting body (miss distance on log10, it spans 4 orders of magnitude)
    app = con.execute("SELECT asteroid_key, epoch_date_close_approach, orbiting_body, close_approach_date, "
                      "miss_distance_km, relative_velocity_km_s FROM approaches").fetchall()

    def valid_md(d): return d is not None and d > 0
    def valid_v(v): return v is not None and 0 < v < C.VELOCITY_MAX_KM_S

    md_g, v_g = defaultdict(list), defaultdict(list)
    for k, _, body, _, d, v in app:
        if k in duplicate_keys:
            continue
        if valid_md(d):
            md_g[body].append(math.log10(d))
        if valid_v(v):
            v_g[body].append(v)
    md_st, v_st = group_stats(md_g), group_stats(v_g)

    rows, unmapped = [], Counter()
    for k, ep, body, date, d, v in app:
        name = body_name.get(body)
        if name is None:
            unmapped[body] += 1
        b_f = "unmapped" if name is None else ("ok" if name == body else "standardised")
        d_c, d_f = clean_value(d, [("invalid_nonpositive", not valid_md(d)),
                                   (unusual(math.log10(d) if valid_md(d) else None, body, md_st), True)])
        v_c, v_f = clean_value(v, [("invalid_out_of_range", not valid_v(v)),
                                   (unusual(v, body, v_st), True)])
        rows.append({"k": k, "ep": ep, "body_raw": body, "body": name, "b_f": b_f,
                     "d_raw": d, "d": d_c, "d_f": d_f, "v_raw": v, "v": v_c, "v_f": v_f,
                     "t": "past" if date <= retrieval_date else "predicted"})
    con.executemany(
        "INSERT INTO approach_clean (asteroid_key, epoch_date_close_approach, orbiting_body_raw, orbiting_body, "
        "orbiting_body_flag, miss_distance_km_raw, miss_distance_km, miss_distance_km_flag, "
        "relative_velocity_km_s_raw, relative_velocity_km_s, relative_velocity_km_s_flag, timing_flag) "
        "VALUES (:k, :ep, :body_raw, :body, :b_f, :d_raw, :d, :d_f, :v_raw, :v, :v_f, :t)", rows)
    summary["approach_clean"] = rows

    summary["unmatched"] += [f"orbiting_body {b!r} ({n} rows)" for b, n in unmapped.items()]
    used_bodies = {r["body_raw"] for r in rows}
    summary["mappings"] = (
        f"body_alias_map {len(bodies)} rows · approach bodies matched {len(used_bodies) - len(unmapped)} "
        f"of {len(used_bodies)} · asteroid_identity_map {len(identity)} rows, matched {matched_identity} "
        f"of {len(identity)}")
    return summary


# ------------------------------------------------------------------ report

def flag_table(title, rows, group_key, flag_keys):
    """Print flag counts: one line per group (entity group), one column per flag value."""
    print(f"\n{title}")
    for label, fk in flag_keys:
        counts = defaultdict(Counter)
        for r in rows:
            counts[r[group_key] if group_key else "all"][r[fk]] += 1
        flags = sorted({f for c in counts.values() for f in c}, key=lambda f: (f != "ok", f))
        print(f"  {label:<26}" + "".join(f"{f:>24}" for f in flags))
        for g in sorted(counts):
            print(f"    {str(g):<24}" + "".join(f"{counts[g][f]:>24,}" for f in flags))


def report(con, s):
    for table, (clean_sql, raw_sql) in COUNTS.items():
        print(f"{table}: {con.execute(clean_sql).fetchone()[0]:,} rows "
              f"(raw: {con.execute(raw_sql).fetchone()[0]:,})")
    flag_table("asteroid_clean flags (per asteroid; one column per flag)", s["asteroid_clean"], None,
               [("designation", "des_f"), ("absolute_magnitude_h", "h_f"),
                ("is_potentially_hazardous", "haz_f"), ("approach_coverage", "cov"), ("identity", "id_f")])
    orbit_class = dict(con.execute("SELECT orbit_key, orbit_class_type FROM orbits"))
    for r in s["orbit_clean"]:
        r["cls"] = orbit_class[r["ok"]]
    flag_table("orbit_clean flags (per orbit class)", s["orbit_clean"], "cls",
               [("eccentricity", "e_f"), ("inclination", "i_f"), ("semi_major_axis", "a_f"),
                ("minimum_orbit_intersection", "m_f"), ("orbit_uncertainty", "u_f")])
    flag_table("approach_clean flags (per orbiting body, raw name)", s["approach_clean"], "body_raw",
               [("orbiting_body", "b_f"), ("miss_distance_km", "d_f"),
                ("relative_velocity_km_s", "v_f"), ("timing", "t")])
    print(f"\nmappings: {s['mappings']}")
    print("unmatched mapping entries:", ", ".join(s["unmatched"]) if s["unmatched"] else "none")


def main():
    con = connect(DB_PATH)
    try:
        con.executescript(CLEAN_SCHEMA.read_text(encoding="utf-8"))  # CREATE ... IF NOT EXISTS, before the transaction
        before = m2_fingerprint(con)
        with con:  # one transaction: on any error nothing of this run is kept
            for sql in CLEAR:
                con.execute(sql)
            summary = build(con)
        after = m2_fingerprint(con)
        report(con, summary)
        fk = con.execute("PRAGMA foreign_key_check").fetchall()
        mismatch = [t for t, (c, r) in COUNTS.items()
                    if con.execute(c).fetchone()[0] != con.execute(r).fetchone()[0]]
        print("M2 tables unchanged:", "OK" if before == after else "FAILED " + str([t for t in before if before[t] != after[t]]))
        print("row counts equal raw:", "OK" if not mismatch else "FAILED " + str(mismatch))
        print("foreign_key_check:", "OK" if not fk else "FAILED " + str(fk[:5]))
        ok = before == after and not mismatch and not fk
    except Exception as exc:  # report, then fail loudly
        print(f"ERROR: {type(exc).__name__}: {exc}")
        ok = False
    finally:
        con.close()
    print("STATUS: COMPLETE" if ok else "STATUS: FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
