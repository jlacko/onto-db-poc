"""The validation loop (PDF practice 5). Run after every change:

    .venv/bin/python scripts/validate.py

Checks, in order:
  1. parse      all Turtle files parse
  2. reasoner   HermiT finds the ontology + reference + sample data consistent,
                and finds a deliberately contradictory individual inconsistent
  3. lint       labels, definitions, status, duplicates, undeclared terms, policy,
                data-dictionary and Czech glossary completeness
  4. shacl      sample data conforms; each negative test fails for the expected reason
  5. artifacts  db/schema.sql, the data dictionary, the glossary and the sample table are up to
                date; the schema loads in SQLite
  6. cq         every competency question: SPARQL vs SQL vs the expected answer
                in ontology/competency-questions.md
  7. loader     the same record observed twice (in either order) ends as one row
                in the latest state; reloads are idempotent

Writes a readable report to build/validation-report.md. Exit code 1 on any failure.
For questions marked ✍ (answered by the domain expert), failures say where the
answer disagrees but never print the computed values; --show-answers prints them.
"""
import io
import re
import sqlite3
import sys
from contextlib import redirect_stderr, redirect_stdout
from decimal import Decimal
from pathlib import Path

from pyshacl import validate as shacl_validate
from rdflib import RDF, RDFS, OWL, SKOS, Graph, Literal, URIRef
from rdflib.namespace import SH

from common import BUILD, DB_DIR, KRIM, ONTO, REF, TESTS, VS, bind, load_graph, model_files

PREFIXES = """PREFIX krim: <https://example.org/kriminalita/ontology#>
PREFIX krimc: <https://example.org/kriminalita/code/>
PREFIX ktype: <https://example.org/kriminalita/code/type/>
PREFIX kstate: <https://example.org/kriminalita/code/state/>
PREFIX krel: <https://example.org/kriminalita/code/relevance/>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX dcterms: <http://purl.org/dc/terms/>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
"""


# Hand-answered (✍) questions never show computed values unless asked for.
SHOW_ANSWERS = "--show-answers" in sys.argv


class Report:
    def __init__(self):
        self.sections: list[tuple[str, list[tuple[str, str]]]] = []
        self.failed = False

    def section(self, title):
        self.sections.append((title, []))
        print(f"\n== {title}")

    def add(self, status, msg):
        self.sections[-1][1].append((status, msg))
        if status == "FAIL":
            self.failed = True
        print(f"  [{status:7}] {msg}")

    def markdown(self) -> str:
        icon = {"PASS": "✅", "FAIL": "❌", "WARN": "⚠️", "PENDING": "✍", "INFO": "ℹ️"}
        out = ["# Validation report", "", f"Overall: **{'FAILED' if self.failed else 'PASSED'}**", ""]
        for title, items in self.sections:
            out += [f"## {title}", ""]
            out += [f"- {icon.get(s, s)} {m}" for s, m in items]
            out.append("")
        return "\n".join(out)


# ---------------------------------------------------------------------------
def check_parse(rep: Report):
    rep.section("1. Parse")
    files = [ONTO / "kriminalita.ttl", ONTO / "shapes.ttl", *sorted(REF.glob("*.ttl")),
             TESTS / "sample-data.ttl", TESTS / "invalid-data.ttl"]
    for f in files:
        try:
            n = len(Graph().parse(f))
            rep.add("PASS", f"{f.relative_to(ONTO.parent)}: {n} triples")
        except Exception as e:  # noqa: BLE001
            rep.add("FAIL", f"{f.relative_to(ONTO.parent)}: {e}")


# ---------------------------------------------------------------------------
def _hermit_consistent(g: Graph) -> tuple[bool, str]:
    import owlready2
    BUILD.mkdir(exist_ok=True)
    path = BUILD / "reasoner-input.nt"
    g.serialize(path, format="nt", encoding="utf-8")
    world = owlready2.World()
    onto = world.get_ontology(path.as_uri()).load(format="ntriples")
    buf = io.StringIO()
    try:
        with redirect_stdout(buf), redirect_stderr(buf):
            owlready2.sync_reasoner_hermit(world, infer_property_values=False, debug=0)
        unsat = list(world.inconsistent_classes())
        if unsat:
            return False, f"unsatisfiable classes: {unsat}"
        return True, f"{len(set(g.subjects(RDF.type, None)))} typed resources checked"
    except owlready2.OwlReadyInconsistentOntologyError:
        return False, "ontology is inconsistent"
    except owlready2.OwlReadyJavaError as e:
        lines = [l for l in str(e).splitlines() if "Exception" in l or "datatype" in l.lower()]
        return False, "reasoner error: " + " ".join(lines)[:300]


def check_reasoner(rep: Report):
    rep.section("2. Reasoner (HermiT via owlready2)")
    g = load_graph(*model_files(), TESTS / "sample-data.ttl")
    ok, msg = _hermit_consistent(g)
    rep.add("PASS" if ok else "FAIL", f"ontology + reference data + sample data consistent: {msg}")

    # Negative test: a record that is also an offence type violates disjointness.
    bad = load_graph(*model_files())
    bad.add((URIRef("https://example.org/kriminalita/record/x"), RDF.type, KRIM.OffenceRecord))
    bad.add((URIRef("https://example.org/kriminalita/record/x"), RDF.type, KRIM.OffenceType))
    ok, msg = _hermit_consistent(bad)
    rep.add("PASS" if not ok else "FAIL",
            "negative test, an individual that is both OffenceRecord and OffenceType: "
            + ("detected as inconsistent" if not ok else "NOT detected"))


# ---------------------------------------------------------------------------
def check_lint(rep: Report):
    rep.section("3. Lint (labels, definitions, duplicates, policy)")
    onto = load_graph(ONTO / "kriminalita.ttl")
    model = load_graph(*model_files())
    ns = str(KRIM)

    terms = sorted({s for s in onto.subjects(RDF.type, None)
                    if isinstance(s, URIRef) and str(s).startswith(ns)})
    problems = 0
    for t in terms:
        name = t.removeprefix(ns)
        labels = {l.language for l in onto.objects(t, RDFS.label)}
        for lang in ("en", "cs"):
            if lang not in labels:
                rep.add("FAIL", f"krim:{name} has no rdfs:label@{lang}"); problems += 1
        defs = [d for d in onto.objects(t, SKOS.definition) if d.language == "en"]
        if len(defs) != 1:
            rep.add("FAIL", f"krim:{name} needs exactly one skos:definition@en"); problems += 1
        elif not re.match(r"^(An?|The) ", str(defs[0])):
            rep.add("WARN", f"krim:{name} definition is not in genus-differentia form ('A ... is a ...')")
        if onto.value(t, VS.term_status) is None:
            rep.add("FAIL", f"krim:{name} has no vs:term_status"); problems += 1
        if (t, RDFS.domain, None) in onto or (t, RDFS.range, None) in onto:
            rep.add("FAIL", f"krim:{name} uses rdfs:domain/range (policy: constraints belong in SHACL)"); problems += 1
        if onto.value(t, SKOS.editorialNote) is not None:
            rep.add("INFO", f"krim:{name} has an open editorial note: {onto.value(t, SKOS.editorialNote)}")
    if not problems:
        rep.add("PASS", f"{len(terms)} ontology terms have labels (en, cs), one definition and a status")

    # Duplicate labels among ontology terms (same language).
    seen = {}
    for t in terms:
        for l in onto.objects(t, RDFS.label):
            key = (str(l).lower(), l.language)
            if key in seen:
                rep.add("FAIL", f"duplicate label '{l}'@{l.language}: krim:{seen[key]} and krim:{t.removeprefix(ns)}")
            seen[key] = t.removeprefix(ns)

    # Codelist concepts: Czech label required; English expected; no duplicate labels among siblings.
    concepts = sorted(set(model.subjects(RDF.type, SKOS.Concept)))
    missing_cs = [c for c in concepts if not any(l.language == "cs" for l in model.objects(c, SKOS.prefLabel))]
    missing_en = [c for c in concepts if not any(l.language == "en" for l in model.objects(c, SKOS.prefLabel))]
    rep.add("FAIL" if missing_cs else "PASS", f"{len(concepts)} codelist concepts, {len(missing_cs)} without a Czech label")
    rep.add("WARN" if missing_en else "PASS", f"{len(missing_en)} codelist concepts without an English label")
    sib = {}
    dup_sib = 0
    for c in concepts:
        parent = model.value(c, SKOS.broader) or model.value(c, SKOS.inScheme)
        for l in model.objects(c, SKOS.prefLabel):
            key = (parent, str(l).lower(), l.language)
            if key in sib:
                rep.add("WARN", f"sibling concepts share label '{l}'@{l.language}: {sib[key]} and {c}"); dup_sib += 1
            sib[key] = c
    if not dup_sib:
        rep.add("PASS", "no duplicate labels among sibling concepts")

    # Every krim: term used anywhere (shapes, sample data, CQ queries) must be declared.
    used = set()
    for f in [ONTO / "shapes.ttl", TESTS / "sample-data.ttl"]:
        for triple in Graph().parse(f):
            used |= {x for x in triple if isinstance(x, URIRef) and str(x).startswith(ns)}
    for q in sorted((TESTS / "cq").glob("*.rq")):
        used |= {URIRef(ns + m) for m in re.findall(r"krim:([A-Za-z]+)", q.read_text())}
    declared = set(terms) | set(load_graph(ONTO / "shapes.ttl").subjects(RDF.type, SH.NodeShape))
    undeclared = sorted(u for u in used if u not in declared)
    for u in undeclared:
        rep.add("FAIL", f"krim:{u.removeprefix(ns)} is used but not declared in the ontology")
    if not undeclared:
        rep.add("PASS", f"all {len(used)} krim: terms used in shapes, samples and queries are declared")

    # Every shape that becomes a column states its rule in plain words.
    shapes = load_graph(ONTO / "shapes.ttl")
    no_desc = [ps for ps in shapes.subjects(SH.path, None) if shapes.value(ps, SH.description) is None]
    rep.add("FAIL" if no_desc else "PASS",
            f"{len(list(shapes.subjects(SH.path, None)))} property shapes, {len(no_desc)} without a plain-language rule (sh:description)")

    # Czech business glossary completeness (English internals, Czech business translations).
    KRIMBD = URIRef(ns + "businessDefinition")
    need = [t for t in terms if (t, RDF.type, OWL.Class) in onto or (t, RDF.type, OWL.DatatypeProperty) in onto]
    missing = [t for t in need if not any(getattr(v, "language", None) == "cs" for v in onto.objects(t, KRIMBD))]
    for t in missing:
        rep.add("FAIL", f"glossary: krim:{t.removeprefix(ns)} has no krim:businessDefinition@cs")
    codes = [c for cls in ("ClearanceState", "LocationRelevance") for c in model.subjects(RDF.type, URIRef(ns + cls))]
    missing_codes = [c for c in codes if not any(getattr(v, "language", None) == "cs" for v in model.objects(c, KRIMBD))]
    for c in missing_codes:
        rep.add("FAIL", f"glossary: codelist item {c} has no krim:businessDefinition@cs")
    shapes_g = load_graph(ONTO / "shapes.ttl")
    record_shapes = set(shapes_g.subjects(SH.targetClass, KRIM.OffenceRecord))
    no_cs_rule = [ps for sh_ in record_shapes for ps in shapes_g.objects(sh_, SH.property)
                  if not any(getattr(v, "language", None) == "cs" for v in shapes_g.objects(ps, SH.description))]
    for ps in no_cs_rule:
        rep.add("FAIL", f"glossary: a record rule on {shapes_g.value(ps, SH.path)} has no Czech sentence (sh:description@cs)")
    if not (missing or missing_codes or no_cs_rule):
        rep.add("PASS", f"glossary: {len(need)} business terms and {len(codes)} codelist items have a Czech "
                        "business definition; every record rule has a Czech sentence")

    # Data dictionary completeness: every column is a data element with names and a definition.
    import dictionary
    rows = dictionary.build_rows()
    gaps = [(r["table_name"], r["column_name"], f) for r in rows
            for f in ("data_element_en", "data_element_cs", "definition_en", "value_domain", "business_rule_en")
            if not r.get(f)]
    for t, c, f in gaps:
        rep.add("FAIL", f"data dictionary: {t}.{c} has no {f} (add sh:name@en/@cs, or skos:definition on the shape "
                        "when the path is a reused property)")
    if not gaps:
        rep.add("PASS", f"data dictionary: all {len(rows)} columns have en/cs names, a definition, "
                        "a value domain and a business rule")


# ---------------------------------------------------------------------------
def _shacl(data: Graph):
    shapes = load_graph(ONTO / "shapes.ttl")
    conforms, results, text = shacl_validate(
        data, shacl_graph=shapes, ont_graph=None, inference="none",
        advanced=True, allow_warnings=True, abort_on_first=False)
    rows = []
    for r in results.subjects(RDF.type, SH.ValidationResult):
        rows.append({
            "focus": results.value(r, SH.focusNode),
            "path": results.value(r, SH.resultPath),
            "severity": results.value(r, SH.resultSeverity),
            "message": str(results.value(r, SH.resultMessage)),
        })
    return conforms, rows


def check_shacl(rep: Report):
    rep.section("4. SHACL (closed-world data rules)")
    data = load_graph(*model_files(), TESTS / "sample-data.ttl")
    conforms, rows = _shacl(data)
    violations = [r for r in rows if r["severity"] == SH.Violation]
    warnings = [r for r in rows if r["severity"] == SH.Warning]
    rep.add("PASS" if conforms and not violations else "FAIL",
            f"reference data + sample data: {len(violations)} violations")
    for v in violations:
        rep.add("FAIL", f"  {v['focus']} {v['path']}: {v['message']}")
    expected_warn = {URIRef("https://example.org/kriminalita/record/1010")}
    got_warn = {w["focus"] for w in warnings}
    rep.add("PASS" if got_warn == expected_warn else "FAIL",
            f"warnings raised for {sorted(str(x).rsplit('/', 1)[1] for x in got_warn)} "
            "(expected: record 1010, foreign location outside the Czechia box)")

    # Negative tests: each individual in invalid-data.ttl must fail for the stated reason.
    text = (TESTS / "invalid-data.ttl").read_text(encoding="utf-8")
    expect = {}
    for m in re.finditer(r"^(\w+):(\w+) a .*# expect: (\w+)", text, re.M):
        prefix = {"rec": "https://example.org/kriminalita/record/"}[m.group(1)]
        expect[URIRef(prefix + m.group(2))] = m.group(3)
    bad = load_graph(*model_files(), TESTS / "sample-data.ttl", TESTS / "invalid-data.ttl")
    _, rows = _shacl(bad)
    viol = [r for r in rows if r["severity"] == SH.Violation]
    for node, prop in expect.items():
        hit = [r for r in viol if r["focus"] == node and r["path"] is not None and str(r["path"]).endswith(prop)]
        rep.add("PASS" if hit else "FAIL",
                f"negative test {str(node).rsplit('/', 1)[1]}: expected violation on {prop}"
                + (f", got: {hit[0]['message'][:90]}" if hit else ", NOT reported"))
    # A rule between two nodes (e.g. a duplicate identifier) flags both; the comment names the partner.
    partners = {URIRef("https://example.org/kriminalita/record/" + m.group(1))
                for m in re.finditer(r"also flags rec:(\w+)", text)}
    unexpected = {r["focus"] for r in viol} - set(expect) - partners
    if unexpected:
        rep.add("FAIL", f"unexpected violations for {sorted(map(str, unexpected))}")


# ---------------------------------------------------------------------------
def build_sample_db() -> sqlite3.Connection:
    import rdf2sql
    con = sqlite3.connect(":memory:")
    con.executescript((DB_DIR / "schema.sql").read_text(encoding="utf-8"))
    con.execute("PRAGMA defer_foreign_keys = ON")
    rdf2sql.load(load_graph(*model_files(), TESTS / "sample-data.ttl"), con)
    con.commit()
    return con


def check_ddl(rep: Report):
    rep.section("5. Generated artifacts (DDL, data dictionary, glossary, sample table)")
    import generate_ddl
    current = (DB_DIR / "schema.sql").read_text(encoding="utf-8") if (DB_DIR / "schema.sql").exists() else ""
    fresh = generate_ddl.generate()
    rep.add("PASS" if current == fresh else "FAIL",
            "db/schema.sql is up to date with ontology/shapes.ttl" if current == fresh
            else "db/schema.sql is stale: run scripts/generate_ddl.py")
    import render_sample
    for path, text in render_sample.render().items():
        ok = path.exists() and path.read_text(encoding="utf-8") == text
        rel = path.relative_to(ONTO.parent)
        rep.add("PASS" if ok else "FAIL", f"{rel} is up to date" if ok
                else f"{rel} is stale: run scripts/render_sample.py")
    import generate_glossary
    for path, text in generate_glossary.outputs()[1].items():
        ok = path.exists() and path.read_text(encoding="utf-8") == text
        rel = path.relative_to(ONTO.parent)
        rep.add("PASS" if ok else "FAIL", f"{rel} is up to date" if ok
                else f"{rel} is stale: run scripts/generate_glossary.py --pdf")
    import generate_dictionary
    for path, text in generate_dictionary.outputs()[3].items():
        ok = path.exists() and path.read_text(encoding="utf-8") == text
        rel = path.relative_to(ONTO.parent)
        rep.add("PASS" if ok else "FAIL", f"{rel} is up to date" if ok
                else f"{rel} is stale: run scripts/generate_dictionary.py --pdf")
    try:
        con = build_sample_db()
        fk = con.execute("PRAGMA foreign_key_check").fetchall()
        n = con.execute("SELECT COUNT(*) FROM offence_record").fetchone()[0]
        nt = con.execute("SELECT COUNT(*) FROM offence_type").fetchone()[0]
        rep.add("PASS" if not fk else "FAIL",
                f"schema loads; reference + sample data inserted ({nt} offence types, {n} records), "
                f"{len(fk)} foreign-key errors")
    except Exception as e:  # noqa: BLE001
        rep.add("FAIL", f"loading sample data into the schema failed: {e}")


# ---------------------------------------------------------------------------
def parse_cq_spec() -> dict[str, dict]:
    text = (ONTO / "competency-questions.md").read_text(encoding="utf-8")
    spec = {}
    for m in re.finditer(r"^### (CQ\d+)([^\n]*)\n(.*?)(?=^### |^## |\Z)", text, re.M | re.S):
        cq, heading, body = m.group(1), m.group(2), m.group(3)
        hand = "✍" in heading  # answered by the domain expert: never reveal the computed answer
        block = re.search(r"```expected\n(.*?)```", body, re.S)
        if not block:
            spec[cq] = {"expected": None}
            continue
        lines = [l.strip() for l in block.group(1).strip().splitlines() if l.strip()]
        pending = any("TODO" in l for l in lines)
        header = [h.strip() for h in lines[0].split("|")]
        rows = [] if pending else [[c.strip() for c in l.split("|")] for l in lines[1:]]
        spec[cq] = {"expected": rows, "header": header, "pending": pending, "hand": hand}
    return spec


def norm(v) -> str:
    if v is None:
        return ""
    if isinstance(v, Literal):
        v = v.toPython()
    if hasattr(v, "isoformat"):
        return v.isoformat()
    if isinstance(v, bool):
        return str(int(v))
    if isinstance(v, (int, float, Decimal)):
        f = round(float(v), 3)
        return str(int(f)) if f == int(f) else f"{f:.3f}".rstrip("0")
    s = str(v)
    try:
        # numbers as people write them: "0.5", ".5", "0,5" (Czech decimal comma)
        if re.fullmatch(r"-?(\d+([.,]\d*)?|[.,]\d+)", s):
            return norm(float(s.replace(",", ".")))
        return s
    except ValueError:
        return s


def as_set(rows) -> list[tuple]:
    return sorted(tuple(norm(c) for c in r) for r in rows)


def hand_hint(header: list[str], want: list[tuple], got: list[tuple]) -> str:
    """Where a hand answer disagrees, without revealing the computed values.

    Says which columns are missing, which of *your* rows (by first column) have no
    counterpart or differ, and in which columns, and how many rows the result has;
    it never prints a computed value other than the row keys you already wrote.
    """
    lines, width = [], len(header)
    if width == 1:  # a single value or a plain list: there is no key to line rows up by
        extra = sorted({r[0] for r in want} - {r[0] for r in got})
        missing = len({r[0] for r in got} - {r[0] for r in want})
        if len(want) == 1 and len(got) == 1:
            return f"      your value for {header[0]} differs from the result"
        if extra:
            lines.append(f"values in your answer that the result does not have: {', '.join(extra)}")
        if missing:
            lines.append(f"the result has {missing} value(s) your answer does not have")
        lines.append(f"values: yours {len(want)}, result {len(got)}")
        return "\n".join("      " + l for l in lines)
    short = sorted({r[0] for r in want if len(r) < width})
    if short:
        lines.append(f"incomplete rows (fewer than the {width} columns {' | '.join(header)}): {', '.join(short)}")
    got_by_key = {r[0]: r for r in got}
    extra = sorted(r[0] for r in want if r[0] not in got_by_key)
    if extra:
        lines.append(f"rows in your answer that the result does not have: {', '.join(extra)}")
    agree = []
    for r in want:
        g = got_by_key.get(r[0])
        if g is None:
            continue
        cols = [header[i] for i in range(1, min(len(r), width)) if i < len(g) and r[i] != g[i]]
        if cols:
            lines.append(f"row {r[0]}: differs in {', '.join(cols)}")
        elif len(r) > 1:
            agree.append(r[0])
    if agree:
        lines.append(f"rows whose filled columns agree: {', '.join(sorted(agree))}")
    missing = len({r[0] for r in got} - {r[0] for r in want})
    if missing:
        lines.append(f"the result has {missing} row(s) your answer does not have")
    if want and got and not ({r[0] for r in want} & {r[0] for r in got}):
        # No key in common: show the format of the result's keys, never their values.
        shapes = sorted({re.sub(r"[A-Za-z]", "a", re.sub(r"\d", "9", r[0])) for r in got})
        lines.append(f"no row key in common; the result's {header[0]} values look like: {', '.join(shapes)}")
    lines.append(f"rows: yours {len(want)}, result {len(got)}")
    return "\n".join("      " + l for l in lines)


def check_cq(rep: Report):
    rep.section("6. Competency questions (you vs SPARQL vs SQL)")
    spec = parse_cq_spec()
    g = load_graph(*model_files(), TESTS / "sample-data.ttl")
    con = build_sample_db()
    cq_dir = TESTS / "cq"
    for cq in sorted(spec):
        exp = spec[cq]
        rq, sq = cq_dir / f"{cq}.rq", cq_dir / f"{cq}.sql"
        if exp["expected"] is None and not exp.get("pending"):
            rep.add("INFO", f"{cq}: no expected block (gap or not testable)")
            continue
        sparql = sql = None
        try:
            if rq.exists():
                sparql = as_set(g.query(PREFIXES + rq.read_text(encoding="utf-8")))
            if sq.exists():
                sql = as_set(con.execute(sq.read_text(encoding="utf-8")).fetchall())
        except Exception as e:  # noqa: BLE001
            rep.add("FAIL", f"{cq}: query error: {e}")
            continue
        if sparql is not None and sql is not None and sparql != sql:
            if exp.get("hand") and not SHOW_ANSWERS:
                rep.add("FAIL", f"{cq}: SPARQL and SQL disagree ({len(sparql)} vs {len(sql)} rows; values hidden "
                                "for a hand-answered question, rerun with --show-answers to see them)")
            else:
                rep.add("FAIL", f"{cq}: SPARQL and SQL disagree\n      SPARQL {sparql}\n      SQL    {sql}")
            continue
        got = sparql if sparql is not None else sql
        layers = " + ".join(x for x, y in (("SPARQL", sparql), ("SQL", sql)) if y is not None)
        if exp["pending"]:
            rep.add("PENDING", f"{cq}: waiting for your answer in competency-questions.md "
                               f"({layers} agree on {len(got)} row(s))")
            continue
        want = as_set(exp["expected"])
        if got == want:
            rep.add("PASS", f"{cq}: {layers} match the expected answer ({len(got)} row(s))")
        else:
            if exp.get("hand") and not SHOW_ANSWERS:
                rep.add("FAIL", f"{cq}: your answer differs from {layers}\n" + hand_hint(exp["header"], want, got))
            else:
                rep.add("FAIL", f"{cq}: {layers} differ from the expected answer\n"
                                f"      expected {want}\n      got      {got}")


# ---------------------------------------------------------------------------
def check_loader(rep: Report):
    rep.section("7. Loader: one occurrence = one record, latest state wins")
    import load
    obs = TESTS / "observations"
    o1 = ((obs / "observation-1.csv").read_text(encoding="utf-8"), "2026-01-10T00:00:00")
    o2 = ((obs / "observation-2.csv").read_text(encoding="utf-8"), "2026-06-10T00:00:00")

    def run(sequence):
        con = load.create_db(":memory:")
        known, stats = load.known_codes(con), []
        for text, observed in sequence:
            records, types, _ = load.parse(text, observed, 2025, known)
            with con:
                stats.append(load.merge(con, records, types))
        return con, stats

    def final_state(con):
        ids = [r[0] for r in con.execute("SELECT id FROM offence_record ORDER BY id")]
        st, asof = con.execute("SELECT clearance_state_code, state_as_of FROM offence_record WHERE id = 5001").fetchone()
        types = sorted(r[0] for r in con.execute(
            "SELECT offence_type_code FROM offence_record_type WHERE offence_record_id = 5001"))
        return ids, st, asof, types

    want = ([5001, 5002, 5003], 1, "2026-06-10T00:00:00", [18, 20])
    for label, seq in (("older then newer", [o1, o2]), ("newer then older", [o2, o1])):
        con, stats = run(seq)
        got = final_state(con)
        rep.add("PASS" if got == want else "FAIL",
                f"{label}: records {got[0]}, record 5001 state {got[1]} as of {got[2]}, types {got[3]}"
                + ("" if got == want else f" (expected {want})"))
    con, stats = run([o2, o1])
    rep.add("PASS" if stats[1]["superseded"] == 1 and stats[1]["new"] == 1 else "FAIL",
            f"older observation loaded last is ignored for 5001 (superseded {stats[1]['superseded']}), "
            f"5002 still added (new {stats[1]['new']})")
    con, stats = run([o1, o2, o2])
    n = con.execute("SELECT COUNT(*) FROM offence_record").fetchone()[0]
    rep.add("PASS" if n == 3 and stats[2]["new"] == 0 else "FAIL",
            f"reloading the same observation is idempotent ({n} records, {stats[2]['new']} new)")
    rep.add("PASS" if stats[1]["state_changes"] == 1 else "FAIL",
            f"state change detected for 5001 (unsolved -> cleared): {stats[1]['state_changes']}")


# ---------------------------------------------------------------------------
def main():
    sys.path.insert(0, str(Path(__file__).parent))
    rep = Report()
    check_parse(rep)
    if not rep.failed:
        check_reasoner(rep)
        check_lint(rep)
        check_shacl(rep)
        check_ddl(rep)
        check_cq(rep)
        check_loader(rep)
    BUILD.mkdir(exist_ok=True)
    (BUILD / "validation-report.md").write_text(rep.markdown(), encoding="utf-8")
    print(f"\n{'FAILED' if rep.failed else 'PASSED'}. Report: build/validation-report.md")
    sys.exit(1 if rep.failed else 0)


if __name__ == "__main__":
    main()
