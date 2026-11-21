"""Build a continuous history of offence records for one report year.

    .venv/bin/python scripts/load.py                  # year 2025, incremental
    .venv/bin/python scripts/load.py --year 2025 --rebuild --shacl-sample 5000

Model (see ontology/competency-questions.md, CQ11, CQ18, CQ19):
  * one occurrence = one row, keyed by the publisher's record id;
  * only the latest observed state is kept; a record read again replaces the
    stored one if its observation (krim:stateAsOf = the publisher's 'updated'
    timestamp of the download) is the same or newer, whatever the load order;
  * the year means report year (krim:reportDateTime); the publisher's monthly
    download files are pagination, recorded only in the technical table
    source_file for incremental refresh.

Steps:
  1. create build/kriminalita.sqlite from db/schema.sql; fill codelist tables from
     the ontology's SKOS files; refresh metadata (release, data dictionary)
  2. read every download file that can hold records of the year; downloads are
     cached in build/cache/zips and fetched again only if the publisher has a newer
     version AND the cached copy is older than --max-age-days (default 7);
     --offline uses the cache only; files already merged at that stamp are skipped
  3. merge each file's records (latest observation wins; type links replaced)
  4. data-quality report: duplicates, holes in the calendar, stale records,
     SHACL warning rules in SQL, and SHACL on a random sample converted to RDF
"""
import argparse
import csv
import io
import json
import sqlite3
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime

from rdflib import RDF, Literal, URIRef
from rdflib.namespace import XSD

import rdf2sql
from common import API, BUILD, CACHE, DB_DIR, KRIM, ONTO, load_graph, model_files
from shapes_model import read_model

DB = BUILD / "kriminalita.sqlite"
REC = "https://example.org/kriminalita/record/"
CODE = "https://example.org/kriminalita/code/"


# --------------------------------------------------------------------------- I/O
def http_get(url: str, tries: int = 6) -> bytes:
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "onto-db-poc/0.1"})
            with urllib.request.urlopen(req, timeout=180) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 429 and i < tries - 1:  # the API rate-limits; back off
                wait = 5 * 2 ** i
                print(f"    429 Too Many Requests, waiting {wait}s")
                time.sleep(wait)
                continue
            raise
    raise RuntimeError("unreachable")


def as_of(stamp: str) -> str:
    """Publisher 'updated' stamp -> canonical xsd:dateTime to the second."""
    return datetime.fromisoformat(stamp).replace(microsecond=0).isoformat()


def norm_datetime(v: str) -> str:
    """'2025-02-19T20:34:00.0000+01:00' -> canonical xsd:dateTime '2025-02-19T20:34:00+01:00'."""
    return datetime.fromisoformat(v).isoformat()


# ---------------------------------------------------------------------- database
def create_db(path) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript((DB_DIR / "schema.sql").read_text(encoding="utf-8"))
    con.execute("PRAGMA defer_foreign_keys = ON")
    rdf2sql.load(load_graph(*model_files()), con, only={"offence_type", "clearance_state", "location_relevance"})
    con.commit()
    return con


def open_db(rebuild: bool) -> sqlite3.Connection:
    BUILD.mkdir(exist_ok=True)
    if rebuild and DB.exists():
        DB.unlink()
    if not DB.exists():
        con = create_db(DB)
        print(f"created {DB.relative_to(BUILD.parent)}; codelists filled from the ontology")
        return con
    con = sqlite3.connect(DB)
    con.execute("PRAGMA foreign_keys = ON")
    refresh_metadata(con)
    return con


def refresh_metadata(con):
    """Replace meta_release and meta_column (the data dictionary) from the current schema.sql."""
    ddl = (DB_DIR / "schema.sql").read_text(encoding="utf-8")
    meta = ddl[ddl.index("-- Metadata:"):]
    with con:
        con.execute("DROP TABLE IF EXISTS meta_release")
        con.execute("DROP TABLE IF EXISTS meta_column")
        con.executescript(meta)
    built = con.execute("SELECT ontology_version FROM meta_release").fetchone()[0]
    print(f"using {DB.relative_to(BUILD.parent)}; metadata refreshed (ontology release {built})")


# ------------------------------------------------------------------------- merge
def field_map():
    """CSV field -> (column, converter), from kdb:sourceField in the shapes; plus the link field."""
    t = read_model()["offence_record"]
    m = {}
    for c in t.columns:
        if not c.source_field:
            continue
        if c.name == "municipal_police":
            m[c.source_field] = (c.name, lambda v: 1 if v.strip().lower() == "true" else 0)
        elif c.name == "report_datetime":
            m[c.source_field] = (c.name, norm_datetime)
        else:
            m[c.source_field] = (c.name, {"INTEGER": int, "REAL": float}.get(c.sql_type, str))
    return m, t.links[0].source_field


def parse(csv_text: str, observed: str, year: int, known: dict) -> tuple[dict, set, dict]:
    """One download file -> records of the year (one per id) and their type links."""
    fmap, link_field = field_map()
    records, types = {}, set()
    st = {"rows": 0, "outside_year": 0, "unknown_code": 0, "inconsistent": 0}
    for row in csv.DictReader(io.StringIO(csv_text)):
        st["rows"] += 1
        rec = {col: fn(row[src]) for src, (col, fn) in fmap.items()}
        if int(rec["report_datetime"][:4]) != year:
            st["outside_year"] += 1
            continue
        t = int(row[link_field])
        if (rec["clearance_state_code"] not in known["state"] or t not in known["type"]
                or rec["location_relevance_code"] not in known["relevance"]):
            st["unknown_code"] += 1
            continue
        rec["iri"], rec["state_as_of"] = REC + str(rec["id"]), observed
        prev = records.get(rec["id"])
        if prev is not None and prev != rec:
            st["inconsistent"] += 1  # same id, different attributes within one file
        records[rec["id"]] = rec
        types.add((rec["id"], t))
    return records, types, st


def merge(con, records: dict, types: set) -> dict:
    """Latest observation wins: insert new records, replace older ones, ignore older observations."""
    if not records:
        return {"new": 0, "updated": 0, "superseded": 0, "state_changes": 0}
    cols = list(next(iter(records.values())))
    con.execute("DROP TABLE IF EXISTS temp.stg_record")
    con.execute("DROP TABLE IF EXISTS temp.stg_type")
    con.execute(f"CREATE TEMP TABLE stg_record AS SELECT {', '.join(cols)} FROM offence_record WHERE 0")
    con.execute("CREATE TEMP TABLE stg_type (offence_record_id INTEGER, offence_type_code INTEGER)")
    con.executemany(f"INSERT INTO stg_record ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                    ([r[c] for c in cols] for r in records.values()))
    con.executemany("INSERT INTO stg_type VALUES (?, ?)", types)
    con.execute("DROP TABLE IF EXISTS temp.win")
    con.execute("""CREATE TEMP TABLE win AS
        SELECT s.id, r.id IS NULL AS is_new,
               (r.id IS NOT NULL AND r.clearance_state_code <> s.clearance_state_code) AS state_changed
        FROM stg_record s LEFT JOIN offence_record r ON r.id = s.id
        WHERE r.id IS NULL OR s.state_as_of >= r.state_as_of""")
    new, updated, changed = con.execute(
        "SELECT COALESCE(SUM(is_new), 0), COALESCE(SUM(1 - is_new), 0), COALESCE(SUM(state_changed), 0) FROM win"
    ).fetchone()
    con.execute("DELETE FROM offence_record_type WHERE offence_record_id IN (SELECT id FROM win)")
    upd = ", ".join(f"{c} = excluded.{c}" for c in cols if c != "id")
    con.execute(f"""INSERT INTO offence_record ({', '.join(cols)})
        SELECT {', '.join(cols)} FROM stg_record WHERE id IN (SELECT id FROM win)
        ON CONFLICT(id) DO UPDATE SET {upd}""")
    con.execute("""INSERT INTO offence_record_type
        SELECT DISTINCT offence_record_id, offence_type_code FROM stg_type
        WHERE offence_record_id IN (SELECT id FROM win)""")
    return {"new": new, "updated": updated, "superseded": len(records) - new - updated, "state_changes": changed}


def known_codes(con) -> dict:
    return {
        "type": {r[0] for r in con.execute("SELECT code FROM offence_type")},
        "state": {r[0] for r in con.execute("SELECT code FROM clearance_state")},
        "relevance": {r[0] for r in con.execute("SELECT code FROM location_relevance")},
    }


def reusable_cache(name: str, updated: str, max_age_days: float, offline: bool) -> str | None:
    """As-of stamp of the cached download if it may be reused, else None."""
    path = CACHE / "zips" / f"{name}.zip"
    stamp_file = path.with_suffix(".updated")
    if not (path.exists() and stamp_file.exists()):
        return None
    cached = stamp_file.read_text().strip()
    age_days = (time.time() - path.stat().st_mtime) / 86400
    return cached if (offline or cached >= as_of(updated) or age_days < max_age_days) else None


def fetch_zip(name: str, updated: str, max_age_days: float, offline: bool) -> tuple[bytes, str, bool]:
    """Return (zip bytes, as-of stamp, downloaded?) with polite caching.

    A cached file is reused if it is at least as new as the publisher's version, or
    younger than max_age_days (the publisher regenerates all files often; we do not
    follow every regeneration). The as-of stamp of a reused file is the publisher
    stamp recorded when it was downloaded (sidecar .updated file).
    """
    path = CACHE / "zips" / f"{name}.zip"
    stamp_file = path.with_suffix(".updated")
    path.parent.mkdir(parents=True, exist_ok=True)
    cached = reusable_cache(name, updated, max_age_days, offline)
    if cached:
        return path.read_bytes(), cached, False
    if offline:
        raise SystemExit(f"--offline: {name}.zip is not cached")
    data = http_get(f"{API}/{name}.zip")
    path.write_bytes(data)
    stamp_file.write_text(as_of(updated))
    return data, as_of(updated), True


def load_file(con, name: str, updated: str, year: int, known: dict,
              max_age_days: float = 7, offline: bool = False) -> dict:
    data, observed, downloaded = fetch_zip(name, updated, max_age_days, offline)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        text = z.read(f"{name}.csv").decode("utf-8")
    records, types, st = parse(text, observed, year, known)
    with con:
        m = merge(con, records, types)
        con.execute("INSERT OR REPLACE INTO source_file VALUES (?, ?, ?, ?)",
                    (name, observed, datetime.now().replace(microsecond=0).isoformat(), len(records)))
    print(f"  file {name} ({'downloaded' if downloaded else 'cache'}, as of {observed}): "
          f"{len(records):>7} records | new {m['new']:>7}, updated {m['updated']:>6} "
          f"(state changed {m['state_changes']}), older observation ignored {m['superseded']} | "
          f"outside {year}: {st['outside_year']}, unknown code: {st['unknown_code']}")
    m["downloaded"] = downloaded
    if st["inconsistent"]:
        print(f"    WARNING: {st['inconsistent']} rows repeat a record id with different attributes")
    return m


# ------------------------------------------------------------------------ checks
def quality_report(con, year: int):
    print(f"\n== Data quality for report year {year}")
    q = {
        "duplicate record identifiers (CQ18; must be 0)":
            "SELECT COUNT(*) FROM (SELECT id FROM offence_record GROUP BY id HAVING COUNT(*) > 1)",
        f"days of {year} with no records (CQ19 over the year; holes in the history)":
            f"""WITH RECURSIVE day(d) AS (SELECT '{year}-01-01' UNION ALL
                  SELECT date(d, '+1 day') FROM day WHERE d < '{year}-12-31')
                SELECT COUNT(*) FROM day WHERE d NOT IN
                  (SELECT DISTINCT substr(report_datetime, 1, 10) FROM offence_record)""",
        f"records with a report date outside {year}":
            f"SELECT COUNT(*) FROM offence_record WHERE substr(report_datetime, 1, 4) <> '{year}'",
        "stale records: not in the latest download of their month (kept, older state)":
            """SELECT COUNT(*) FROM offence_record r JOIN source_file f
                 ON f.name = substr(r.report_datetime, 1, 4) || substr(r.report_datetime, 6, 2)
               WHERE r.state_as_of < f.publisher_updated""",
        "records outside the Czechia box (warning shape)":
            "SELECT COUNT(*) FROM offence_record WHERE latitude NOT BETWEEN 48.5 AND 51.1 OR longitude NOT BETWEEN 12.0 AND 18.9",
        "records missing a broader type of one of their types (warning shape)":
            """SELECT COUNT(DISTINCT rt.offence_record_id) FROM offence_record_type rt
               JOIN offence_type t ON t.code = rt.offence_type_code
               WHERE t.broader_code IS NOT NULL AND NOT EXISTS (
                 SELECT 1 FROM offence_record_type rt2
                 WHERE rt2.offence_record_id = rt.offence_record_id AND rt2.offence_type_code = t.broader_code)""",
        "records reported at exactly 00:00 (open question)":
            "SELECT COUNT(*) FROM offence_record WHERE substr(report_datetime, 12, 5) = '00:00'",
        "foreign-key violations": "SELECT COUNT(*) FROM pragma_foreign_key_check",
    }
    for label, sql in q.items():
        print(f"  {con.execute(sql).fetchone()[0]:>9}  {label}")
    lo, hi = con.execute("SELECT MIN(state_as_of), MAX(state_as_of) FROM offence_record").fetchone()
    print(f"  states as of {lo} .. {hi}")


def shacl_sample(con, n: int):
    """Convert n random real records back to RDF and validate them with the shapes."""
    from pyshacl import validate
    from rdflib.namespace import SH
    ids = [r[0] for r in con.execute("SELECT id FROM offence_record ORDER BY random() LIMIT ?", (n,))]
    if not ids:
        return
    g = load_graph(*model_files())
    t = read_model()["offence_record"]
    q = ",".join("?" * len(ids))
    slug = {"clearance_state": "state", "location_relevance": "relevance"}
    for row in con.execute(f"SELECT iri, {', '.join(c.name for c in t.columns)} FROM offence_record WHERE id IN ({q})", ids):
        s = URIRef(row[0])
        g.add((s, RDF.type, KRIM.OffenceRecord))
        for c, v in zip(t.columns, row[1:]):
            if c.references:
                g.add((s, c.path, URIRef(f"{CODE}{slug[c.references]}/{v}")))
            elif c.name == "municipal_police":
                g.add((s, c.path, Literal(bool(v))))
            elif c.name in ("report_datetime", "state_as_of"):
                g.add((s, c.path, Literal(v, datatype=XSD.dateTime)))
            elif c.sql_type == "REAL":
                g.add((s, c.path, Literal(str(v), datatype=XSD.decimal)))
            else:
                g.add((s, c.path, Literal(v)))
    for rid, code in con.execute(f"SELECT offence_record_id, offence_type_code FROM offence_record_type "
                                 f"WHERE offence_record_id IN ({q})", ids):
        g.add((URIRef(REC + str(rid)), KRIM.hasOffenceType, URIRef(f"{CODE}type/{code}")))
    conforms, res, _ = validate(g, shacl_graph=load_graph(ONTO / "shapes.ttl"), advanced=True, allow_warnings=True)
    sev = {}
    for r in res.subjects(RDF.type, SH.ValidationResult):
        key = (str(res.value(r, SH.resultSeverity)).rsplit("#", 1)[1], str(res.value(r, SH.resultMessage))[:80])
        sev[key] = sev.get(key, 0) + 1
    print(f"\n== SHACL on {len(ids)} random real records: {'conforms' if conforms else 'DOES NOT CONFORM'}")
    for (s, m), k in sorted(sev.items(), key=lambda x: -x[1])[:10]:
        print(f"  {k:>6} {s}: {m}")


# -------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=2025)
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--shacl-sample", type=int, default=1000,
                    help="records checked with SHACL; the uniqueness rule is quadratic, keep it small")
    ap.add_argument("--max-age-days", type=float, default=7,
                    help="reuse a cached download younger than this, even if the publisher regenerated it")
    ap.add_argument("--offline", action="store_true", help="no network: cached listing and downloads only")
    a = ap.parse_args()

    con = open_db(a.rebuild)
    known = known_codes(con)
    started = datetime.now().replace(microsecond=0).isoformat()
    with con:
        run_id = con.execute("INSERT INTO load_run (started_at, year) VALUES (?, ?)", (started, a.year)).lastrowid

    # The download files are monthly pagination by report date; read every file of the year.
    listing_path = CACHE / "downloads.json"
    if a.offline:
        listing = json.loads(listing_path.read_text(encoding="utf-8"))["data"]
    else:
        raw = http_get(API)
        listing_path.parent.mkdir(parents=True, exist_ok=True)
        listing_path.write_bytes(raw)
        listing = json.loads(raw)["data"]
    files = sorted((f["name"], f["updated"]) for f in listing if f["name"].isdigit() and f["name"][:4] == str(a.year))
    have = dict(con.execute("SELECT name, publisher_updated FROM source_file"))
    downloads = 0
    total = {"new": 0, "updated": 0, "state_changes": 0}
    print(f"{len(files)} download files can hold records of {a.year}")
    for name, updated in files:
        will_load = reusable_cache(name, updated, a.max_age_days, a.offline) or as_of(updated)
        if have.get(name) == will_load:
            print(f"  file {name}: already merged as of {will_load}, skipped")
            continue
        m = load_file(con, name, updated, a.year, known, a.max_age_days, a.offline)
        for k in total:
            total[k] += m[k]
        if m["downloaded"]:
            downloads += 1
            time.sleep(1)  # be polite to the API
    print(f"  {downloads} file(s) downloaded, the rest served from build/cache/zips")
    with con:
        con.execute("UPDATE load_run SET finished_at = ?, records_new = ?, records_updated = ?, state_changes = ? "
                    "WHERE run_id = ?", (datetime.now().replace(microsecond=0).isoformat(),
                                         total["new"], total["updated"], total["state_changes"], run_id))
    quality_report(con, a.year)
    if a.shacl_sample:
        shacl_sample(con, a.shacl_sample)
    n = con.execute("SELECT COUNT(*) FROM offence_record").fetchone()[0]
    print(f"\n{n} offence records in {DB.relative_to(BUILD.parent)}, as of load run {run_id} ({started})")


if __name__ == "__main__":
    main()
