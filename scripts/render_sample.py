"""Render the sample data as CSV files for answering CQs by hand in a spreadsheet.

    .venv/bin/python scripts/render_sample.py

Writes (generated from ontology/tests/sample-data.ttl; do not edit):
  ontology/tests/sample-records.csv   one row per record, with its area, municipality, ORP area,
                                      okres and kraj
  ontology/tests/sample-types.csv     the offence types used, with broader type and category
  ontology/tests/sample-areas.csv     the anonymisation areas, with municipality and centre
UTF-8, comma-separated, dot as decimal separator. Multi-valued cells (a record's
types and categories) are separated by spaces. The categories column was added at
the domain expert's request; the most-specific type is still not pre-computed.
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


def top_of(g, t):
    """The category (top-level type) a type rolls up to."""
    while g.value(t, SKOS.broader) is not None:
        t = g.value(t, SKOS.broader)
    return t


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
        a = g.value(r, KRIM.inAnonymisationArea)
        m = g.value(a, KRIM.inMunicipality)
        orp, okres = g.value(m, KRIM.inOrpArea), g.value(m, KRIM.inOkres)
        kraj = g.value(okres, KRIM.inKraj)  # the same through the ORP area (MunicipalityKrajShape)
        types = sorted(g.objects(r, KRIM.hasOffenceType), key=lambda t: code(g, t))
        used |= set(types)
        cats = sorted({code(g, top_of(g, t)) for t in types})
        rows.append([
            str(g.value(r, DCTERMS.identifier)),
            dt[:10], dt[11:16], dt[:7],
            str(g.value(a, DCTERMS.identifier)), code(g, m), label(g, m, "cs"),
            code(g, orp), label(g, orp, "cs"), code(g, okres), label(g, okres, "cs"), code(g, kraj), label(g, kraj, "cs"),
            str(g.value(a, KRIM.centreLatitude)), str(g.value(a, KRIM.centreLongitude)),
            "yes" if g.value(r, KRIM.recordedByMunicipalPolice).toPython() else "no",
            code(g, st), label(g, st), code(g, rel), label(g, rel),
            " ".join(str(code(g, t)) for t in types),
            " ".join(str(c) for c in cats),
            str(g.value(r, KRIM.stateAsOf)),
        ])
    records = _csv(["record", "report_date", "report_time", "report_month", "area", "municipality_code",
                    "municipality", "orp_area_code", "orp_area", "okres_code", "okres", "kraj_code", "kraj",
                    "centre_latitude", "centre_longitude", "municipal_police", "state_code", "state", "relevance_code", "relevance", "types",
                    "categories", "state_as_of"], rows)

    trows = []
    for t in sorted(used, key=lambda t: code(g, t)):
        b, top = g.value(t, SKOS.broader), t
        while g.value(top, SKOS.broader) is not None:
            top = g.value(top, SKOS.broader)
        trows.append([code(g, t), label(g, t), label(g, t, "cs"),
                      "" if b is None else code(g, b), code(g, top), label(g, top),
                      "yes" if top == t else "no"])
    types = _csv(["type", "label_en", "label_cs", "broader", "category_code", "category", "is_category"], trows)
    arows = []
    for a in sorted(g.subjects(RDF.type, KRIM.AnonymisationArea), key=lambda a: int(g.value(a, DCTERMS.identifier))):
        m = g.value(a, KRIM.inMunicipality)
        arows.append([str(g.value(a, DCTERMS.identifier)), code(g, m), label(g, m, "cs"),
                      str(g.value(a, KRIM.centreLatitude)), str(g.value(a, KRIM.centreLongitude))])
    areas = _csv(["area", "municipality_code", "municipality", "centre_latitude", "centre_longitude"], arows)
    return {TESTS / "sample-records.csv": records, TESTS / "sample-types.csv": types,
            TESTS / "sample-areas.csv": areas}


def main():
    for path, text in render().items():
        path.write_text(text, encoding="utf-8")
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
