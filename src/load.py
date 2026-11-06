"""data/raw/*.json -> SQLite. API'ye istek atmaz. Çalıştırma: python src/load.py"""
import json
import math
import pathlib
import re
from datetime import datetime, timedelta

from db import PROJECT_ROOT as ROOT, DB_PATH as DEFAULT_DB, connect

RAW = ROOT / "data" / "raw"
SCHEMA = ROOT / "sql" / "schema.sql"
MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}


def retrieved_at_from_name(path):
    # browse_20261017T123742Z_page0.json        -> 2026-10-17T12:37:42.000000Z
    # browse_20261017T125321207719Z_page0.json  -> 2026-10-17T12:53:21.207719Z
    # Kesir her zaman 6 hane yazılır; böylece metin karşılaştırması zaman sırasıyla aynı olur.
    m = re.search(r"(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})(\d{0,6})Z", path.name)
    if not m:
        raise ValueError(f"dosya adında zaman damgası yok: {path.name}")
    y, mo, d, h, mi, s, frac = m.groups()
    return f"{y}-{mo}-{d}T{h}:{mi}:{s}.{frac.ljust(6, '0')}Z"


def to_float(v, stats):
    """None = kayıt yok (NULL, sayılmaz). Çevrilemeyen metin = NULL, sayılır."""
    if v is None:
        return None
    try:
        if isinstance(v, bool):
            raise ValueError
        f = float(v)
        if not math.isfinite(f):
            raise ValueError
        return f
    except (TypeError, ValueError):
        stats["cleaned"] += 1
        return None


def to_bool(v, stats):
    if v is None:
        return None
    if isinstance(v, bool):
        return int(v)
    stats["cleaned"] += 1
    return None


def to_text(v):
    return None if v is None else str(v)


def to_epoch(v):
    """Tam sayı (ms) ya da rakamlardan oluşan metin; aksi halde None (-> karantina)."""
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, str) and re.fullmatch(r"-?\d+", v.strip()):
        return int(v)
    return None


def iso_from_full(full):
    """'1901-Aug-23 17:36' (UTC kabul edilir) -> '1901-08-23T17:36Z'. Çözülemezse None."""
    try:
        date, time = full.strip().split(" ")
        y, mon, d = date.split("-")
        h, mi = time.split(":")
        return f"{int(y):04d}-{MONTHS[mon]:02d}-{int(d):02d}T{int(h):02d}:{int(mi):02d}Z"
    except (AttributeError, ValueError, KeyError):
        return None


def iso_date(s):
    """'1901-08-23' -> sıfır dolgulu YYYY-MM-DD; geçersizse None."""
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d").strftime("%Y-%m-%d")
    except (AttributeError, ValueError):
        return None


def date_from_epoch(ms):
    # datetime.fromtimestamp negatif değerlerde bazı sistemlerde patlar; timedelta güvenli
    try:
        return (datetime(1970, 1, 1) + timedelta(milliseconds=ms)).strftime("%Y-%m-%d")
    except (OverflowError, ValueError):
        return None


def iso_from_orbit_date(s):
    """'2026-10-11 06:57:01' (UTC kabul edilir) -> '2026-10-11T06:57:01Z'."""
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d %H:%M:%S").strftime("%Y-%m-%dT%H:%M:%SZ")
    except (AttributeError, ValueError):
        return None


def read_raw(raw_dir):
    """Bozuk JSON burada hata verir -> henüz hiçbir şey yazılmamıştır."""
    files = sorted(pathlib.Path(raw_dir).rglob("*.json"))
    items = []
    for f in files:
        data = json.loads(f.read_text(encoding="utf-8"))
        ra = retrieved_at_from_name(f)
        if isinstance(data, dict) and "near_earth_objects" not in data and "id" in data:
            neo = [data]  # lookup biçimi: tek asteroid nesnesi
        else:
            neo = data.get("near_earth_objects", [])
        if isinstance(neo, dict):  # feed biçimi: {"2026-10-11": [asteroid, ...]}
            neo = [a for day in neo.values() for a in day]
        for ast in neo:
            items.append((ra, ast))
    return files, items


def count(con, table):
    # Tablo adı sabit listeden gelir, kullanıcı verisinden değil
    return con.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]


def load(db_path=DEFAULT_DB, raw_dir=RAW):
    pathlib.Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    con = connect(db_path)
    con.executescript(SCHEMA.read_text(encoding="utf-8"))  # transaction'dan ÖNCE
    files, items = read_raw(raw_dir)
    stats = {"cleaned": 0}

    ast_best, orbit_best, ev_best, quarantine = {}, {}, {}, []
    # feed kayıtlarında 'designation' alanı hiç yok; daha yeni bir feed kaydı, eski browse kaydındaki
    # değeri silmesin diye bu alan ayrıca seçilir: alanı *taşıyan* en yeni kayıt kazanır.
    des_best = {}

    for ra, ast in items:
        if not isinstance(ast, dict):
            quarantine.append(("kayıt sözlük değil", json.dumps(ast, sort_keys=True), ra))
            continue
        sid = ast.get("id")
        if not sid:
            quarantine.append(("asteroid id yok", json.dumps(ast, sort_keys=True), ra))
            continue
        sid = str(sid)
        if sid not in ast_best or ra > ast_best[sid][0]:
            ast_best[sid] = (ra, ast)
        if "designation" in ast and (sid not in des_best or ra > des_best[sid][0]):
            des_best[sid] = (ra, ast["designation"])
        od = ast.get("orbital_data")
        if od and (sid not in orbit_best or ra > orbit_best[sid][0]):
            orbit_best[sid] = (ra, od)
        for ca in ast.get("close_approach_data") or []:
            ep = to_epoch(ca.get("epoch_date_close_approach"))
            if ep is None:
                quarantine.append(("yaklaşma epoch değeri geçersiz",
                                   json.dumps({"id": sid, **ca}, sort_keys=True), ra))
                continue
            body = ca.get("orbiting_body")
            if not isinstance(body, str) or not body.strip():
                quarantine.append(("yaklaşma orbiting_body yok",
                                   json.dumps({"id": sid, **ca}, sort_keys=True), ra))
                continue
            k = (sid, ep, body)  # aynı anda Dünya ve Ay'a yaklaşma olabilir
            if k not in ev_best or ra > ev_best[k][0]:
                ev_best[k] = (ra, ca)

    with con:  # tek transaction: hata olursa hepsi geri alınır
        n0 = {t: count(con, t) for t in ("asteroids", "orbits", "approaches", "quarantine")}

        for sid, (ra, a) in ast_best.items():
            dia = ((a.get("estimated_diameter") or {}).get("kilometers")) or {}
            con.execute(
                """INSERT INTO asteroids
                       (source_id, name, designation, absolute_magnitude_h, is_potentially_hazardous,
                        is_sentry_object, diameter_min_km, diameter_max_km, retrieved_at)
                   VALUES (:sid, :name, :des, :h, :haz, :sentry, :dmin, :dmax, :ra)
                   ON CONFLICT(source_id) DO UPDATE SET
                       name = excluded.name,
                       designation = excluded.designation,
                       absolute_magnitude_h = excluded.absolute_magnitude_h,
                       is_potentially_hazardous = excluded.is_potentially_hazardous,
                       is_sentry_object = excluded.is_sentry_object,
                       diameter_min_km = excluded.diameter_min_km,
                       diameter_max_km = excluded.diameter_max_km,
                       retrieved_at = excluded.retrieved_at
                   WHERE excluded.retrieved_at >= asteroids.retrieved_at""",
                {"sid": sid, "name": a.get("name"), "des": to_text(des_best.get(sid, (None, None))[1]),
                 "h": to_float(a.get("absolute_magnitude_h"), stats),
                 "haz": to_bool(a.get("is_potentially_hazardous_asteroid"), stats),
                 "sentry": to_bool(a.get("is_sentry_object"), stats),
                 "dmin": to_float(dia.get("estimated_diameter_min"), stats),
                 "dmax": to_float(dia.get("estimated_diameter_max"), stats),
                 "ra": ra})

        for sid, (ra, od) in orbit_best.items():
            row = con.execute("SELECT asteroid_key FROM asteroids WHERE source_id = ?", (sid,)).fetchone()
            if row is None:
                quarantine.append(("orbit: bilinmeyen asteroid", json.dumps({"id": sid, **od}, sort_keys=True), ra))
                continue
            oc = od.get("orbit_class") or {}
            det_raw = od.get("orbit_determination_date")
            det = iso_from_orbit_date(det_raw)
            if det_raw is not None and det is None:
                stats["cleaned"] += 1
            p = {"sid": sid, "k": row[0], "ra": ra, "det": det,
                 "unc": to_text(od.get("orbit_uncertainty")),
                 "oct": oc.get("orbit_class_type"), "ocd": oc.get("orbit_class_description"),
                 "ocr": oc.get("orbit_class_range")}
            for col in ("eccentricity", "inclination", "semi_major_axis", "orbital_period",
                        "minimum_orbit_intersection", "ascending_node_longitude",
                        "perihelion_argument", "perihelion_distance", "aphelion_distance",
                        "mean_anomaly", "mean_motion"):
                p[col] = to_float(od.get(col), stats)
            con.execute(
                """INSERT INTO orbits
                       (source_id, asteroid_key, eccentricity, inclination, semi_major_axis, orbital_period,
                        minimum_orbit_intersection, ascending_node_longitude, perihelion_argument,
                        perihelion_distance, aphelion_distance, mean_anomaly, mean_motion,
                        orbit_class_type, orbit_class_description, orbit_class_range,
                        orbit_uncertainty, orbit_determination_date, retrieved_at)
                   VALUES (:sid, :k, :eccentricity, :inclination, :semi_major_axis, :orbital_period,
                        :minimum_orbit_intersection, :ascending_node_longitude, :perihelion_argument,
                        :perihelion_distance, :aphelion_distance, :mean_anomaly, :mean_motion,
                        :oct, :ocd, :ocr, :unc, :det, :ra)
                   ON CONFLICT(source_id) DO UPDATE SET
                       eccentricity = excluded.eccentricity, inclination = excluded.inclination,
                       semi_major_axis = excluded.semi_major_axis, orbital_period = excluded.orbital_period,
                       minimum_orbit_intersection = excluded.minimum_orbit_intersection,
                       ascending_node_longitude = excluded.ascending_node_longitude,
                       perihelion_argument = excluded.perihelion_argument,
                       perihelion_distance = excluded.perihelion_distance,
                       aphelion_distance = excluded.aphelion_distance,
                       mean_anomaly = excluded.mean_anomaly, mean_motion = excluded.mean_motion,
                       orbit_class_type = excluded.orbit_class_type,
                       orbit_class_description = excluded.orbit_class_description,
                       orbit_class_range = excluded.orbit_class_range,
                       orbit_uncertainty = excluded.orbit_uncertainty,
                       orbit_determination_date = excluded.orbit_determination_date,
                       retrieved_at = excluded.retrieved_at
                   WHERE excluded.retrieved_at >= orbits.retrieved_at""", p)

        for (sid, ep, body), (ra, ca) in ev_best.items():
            row = con.execute("SELECT asteroid_key FROM asteroids WHERE source_id = ?", (sid,)).fetchone()
            if row is None:  # bilinmeyen varlık -> karantina
                quarantine.append(("bilinmeyen asteroid", json.dumps({"id": sid, **ca}, sort_keys=True), ra))
                continue
            date = iso_date(ca.get("close_approach_date"))
            if date is None:  # yedek: epoch'tan türet
                date = date_from_epoch(ep)
                stats["cleaned"] += 1
            if date is None:
                quarantine.append(("yaklaşma tarihi çözülemedi", json.dumps({"id": sid, **ca}, sort_keys=True), ra))
                continue
            full_raw = ca.get("close_approach_date_full")
            full = iso_from_full(full_raw)
            if full_raw is not None and full is None:
                stats["cleaned"] += 1
            con.execute(
                """INSERT INTO approaches
                       (asteroid_key, epoch_date_close_approach, close_approach_date, close_approach_date_full,
                        relative_velocity_km_s, miss_distance_km, orbiting_body, retrieved_at)
                   VALUES (:k, :ep, :d, :full, :v, :md, :body, :ra)
                   ON CONFLICT(asteroid_key, epoch_date_close_approach, orbiting_body) DO UPDATE SET
                       close_approach_date = excluded.close_approach_date,
                       close_approach_date_full = excluded.close_approach_date_full,
                       relative_velocity_km_s = excluded.relative_velocity_km_s,
                       miss_distance_km = excluded.miss_distance_km,
                       retrieved_at = excluded.retrieved_at
                   WHERE excluded.retrieved_at >= approaches.retrieved_at""",
                {"k": row[0], "ep": ep, "d": date, "full": full,
                 "v": to_float((ca.get("relative_velocity") or {}).get("kilometers_per_second"), stats),
                 "md": to_float((ca.get("miss_distance") or {}).get("kilometers"), stats),
                 "body": body, "ra": ra})

        for reason, raw, ra in quarantine:
            con.execute("INSERT INTO quarantine (reason, raw_record, retrieved_at) VALUES (?, ?, ?) "
                        "ON CONFLICT DO NOTHING", (reason, raw, ra))

        n1 = {t: count(con, t) for t in n0}

    fk = con.execute("PRAGMA foreign_key_check").fetchall()
    con.close()

    dates = sorted(retrieved_at_from_name(f)[:10] for f in files)
    rng = f" ({dates[0]} .. {dates[-1]})" if dates else ""
    print(f"files read: {len(files)} raw files{rng}")
    print(f"asteroids: {n1['asteroids']:,} in database ({n1['asteroids'] - n0['asteroids']:+d} this run)")
    print(f"orbits: {n1['orbits']:,} in database ({n1['orbits'] - n0['orbits']:+d} this run)")
    print(f"approaches: {n1['approaches']:,} in database ({n1['approaches'] - n0['approaches']:+d} this run)")
    print(f"values cleaned: {stats['cleaned']} (non-numeric/invalid -> NULL)")
    print(f"quarantined: {n1['quarantine']:,} in table ({n1['quarantine'] - n0['quarantine']:+d} this run)")
    print(f"foreign_key_check: {'OK' if not fk else 'FAILED ' + str(fk)}")
    print("STATUS: COMPLETE" if not fk else "STATUS: FAILED")
    return n1


if __name__ == "__main__":
    load()