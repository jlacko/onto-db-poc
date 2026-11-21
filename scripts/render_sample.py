"""Render the sample data as CSV files for answering CQs by hand in a spreadsheet.

    .venv/bin/python scripts/render_sample.py

Writes (generated from ontology/tests/sample-data.ttl; do not edit):
  ontology/tests/sample-records.csv   one row per record
  ontology/tests/sample-types.csv     the offence types used, with broader type and category
UTF-8, comma-separated, dot as decimal separator. Multi-valued cells (a record's
types) are separated by spaces. Nothing here pre-computes a CQ answer.
"""
import csv
import io

from rdflib import RDF, SKOS
from rdflib.namespace import DCTERMS

from common import KRIM, TESTS, load_graph, model_files


def label(g, c, lang="en"):
    for l in g.objects(c, SKOS.prefLabel):
        if l.language == lang:
            return str(l)
    return ""


def code(g, c):
    return int(g.value(c, SKOS.notation))


def _csv(header, rows) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    w.writerows(rows)
    return buf.getvalue()


def render() -> dict:
    """{path: csv text}"""
    g = load_graph(*model_files(), TESTS / "sample-data.ttl")
    recs = sorted(g.subjects(RDF.type, KRIM.OffenceRecord), key=lambda r: int(g.value(r, DCTERMS.identifier)))
    rows, used = [], set()
    for r in recs:
        dt = str(g.value(r, KRIM.reportDateTime))
        st, rel = g.value(r, KRIM.hasClearanceState), g.value(r, KRIM.hasLocationRelevance)
        types = sorted(g.objects(r, KRIM.hasOffenceType), key=lambda t: code(g, t))
        used |= set(types)
        rows.append([
            str(g.value(r, DCTERMS.identifier)),
            dt[:10], dt[11:16], dt[:7],
            str(g.value(r, KRIM.anonymisedLatitude)), str(g.value(r, KRIM.anonymisedLongitude)),
            "yes" if g.value(r, KRIM.recordedByMunicipalPolice).toPython() else "no",
            code(g, st), label(g, st), code(g, rel), label(g, rel),
            " ".join(str(code(g, t)) for t in types),
            str(g.value(r, KRIM.stateAsOf)),
        ])
    records = _csv(["record", "report_date", "report_time", "report_month", "latitude", "longitude",
                    "municipal_police", "state_code", "state", "relevance_code", "relevance", "types",
                    "state_as_of"], rows)

    trows = []
    for t in sorted(used, key=lambda t: code(g, t)):
        b, top = g.value(t, SKOS.broader), t
        while g.value(top, SKOS.broader) is not None:
            top = g.value(top, SKOS.broader)
        trows.append([code(g, t), label(g, t), label(g, t, "cs"),
                      "" if b is None else code(g, b), code(g, top), label(g, top),
                      "yes" if top == t else "no"])
    types = _csv(["type", "label_en", "label_cs", "broader", "category_code", "category", "is_category"], trows)
    return {TESTS / "sample-records.csv": records, TESTS / "sample-types.csv": types}


def main():
    for path, text in render().items():
        path.write_text(text, encoding="utf-8")
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
