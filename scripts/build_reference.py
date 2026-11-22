"""Build SKOS concept schemes from the publisher's codelists and ČSÚ codelist 43.

Source: the Police CR API publishes each codelist as JSON-LD in the Czech
open-data codelist format (OFN "číselník"), with an IRI per item. This script
turns them into SKOS, adds the hand-maintained English labels and definitions
from ontology/reference/codelist-texts.csv (English labels and definitions, Czech
business definitions), and writes one Turtle file per scheme.

Municipalities come from the Czech Statistical Office's codelist 43 ("Obec a
vojenský újezd"), downloaded as CSV. The download is cached in build/cache with a
.updated stamp and reused for MAX_AGE_DAYS; --offline never downloads.

    .venv/bin/python scripts/build_reference.py [--offline]
"""
import csv
import gzip
import io
import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

from rdflib import RDF, SKOS, Literal, URIRef, Graph
from rdflib.namespace import DCTERMS, XSD

from common import API, CACHE, KRIM, KRIMC, REF, SCHEMES, VS, bind

SCHEME_TEXT = {
    "types": ("offence types", "typy deliktů",
              "The Police CR hierarchical classification of offence records by the kind of act."),
    "states": ("clearance states", "stavy objasnění",
               "The Police CR classification of offence records by the outcome of the police inquiry."),
    "relevance": ("location relevance", "relevance lokality",
                  "The Police CR classification of what the recorded location of an offence record stands for."),
}


def fetch(name: str, offline: bool) -> dict:
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"{name}.json"
    if not offline or not path.exists():
        with urllib.request.urlopen(f"{API}/{name}.json", timeout=60) as r:
            raw = r.read()
        if raw[:2] == b"\x1f\x8b":  # the server gzips without being asked
            raw = gzip.decompress(raw)
        path.write_bytes(raw)
    return json.loads(path.read_text(encoding="utf-8"))


CZSO_PAGE = "https://apl2.czso.cz/iSMS/cisdet.jsp?kodcis=43"
CZSO_EXPORT = "https://apl2.czso.cz/iSMS/do_cis_export?" + urllib.parse.urlencode(
    {"kodcis": 43, "typdat": 0, "cisjaz": 203, "format": 2})  # CSV, Czech, valid today
MAX_AGE_DAYS = 30


def fetch_czso(offline: bool) -> list[dict]:
    """ČSÚ codelist 43 as rows; downloaded at most once per MAX_AGE_DAYS."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path, stamp = CACHE / "czso-43.csv", CACHE / "czso-43.csv.updated"
    fresh = path.exists() and stamp.exists() and (
        datetime.now().astimezone() - datetime.fromisoformat(stamp.read_text().strip()) < timedelta(days=MAX_AGE_DAYS))
    if not path.exists() and offline:
        sys.exit("czso-43.csv is not cached; run once without --offline")
    if not offline and not fresh:
        with urllib.request.urlopen(CZSO_EXPORT, timeout=60) as r:
            path.write_bytes(r.read())
        stamp.write_text(datetime.now().astimezone().isoformat(timespec="seconds") + "\n")
    return list(csv.DictReader(io.StringIO(path.read_text(encoding="utf-8"))))


def build_municipalities(rows: list[dict], texts: dict) -> Graph:
    g = bind(Graph())
    scheme = KRIMC["municipality"]
    g.add((scheme, RDF.type, SKOS.ConceptScheme))
    g.add((scheme, SKOS.prefLabel, Literal("municipalities", lang="en")))
    g.add((scheme, SKOS.prefLabel, Literal("obce", lang="cs")))
    g.add((scheme, SKOS.definition, Literal(
        "The Czech Statistical Office's codelist of municipalities and military training areas (ČSÚ codelist 43).",
        lang="en")))
    g.add((scheme, DCTERMS.source, URIRef(CZSO_PAGE)))
    for row in rows:
        code = int(row["chodnota"])
        c = KRIMC[f"municipality/{code}"]
        g.add((c, RDF.type, SKOS.Concept))
        g.add((c, RDF.type, KRIM.Municipality))
        g.add((c, SKOS.inScheme, scheme))
        g.add((c, SKOS.topConceptOf, scheme))
        g.add((c, SKOS.notation, Literal(code, datatype=XSD.integer)))
        g.add((c, SKOS.prefLabel, Literal(row["text"].strip(), lang="cs")))
        _, defn, bdef = texts.get(("municipalities", code), (None, None, None))
        if defn:
            g.add((c, SKOS.definition, Literal(defn, lang="en")))
        if bdef:
            g.add((c, KRIM.businessDefinition, Literal(bdef, lang="cs")))
        g.add((c, VS.term_status, Literal("stable")))
    return g


def cs_label(item: dict) -> tuple[str, str | None]:
    """Readable Czech prefLabel plus an optional altLabel.

    Types carry a short group name ("nazev") and a description ("popis"); the
    description is the specific label except for the "bez podtřídy" items.
    """
    name = item["nazev"]["cs"].strip()
    popis = (item.get("popis") or {}).get("cs", "").strip()
    if not popis:
        return name, None
    if popis == "bez podtřídy":
        return name[:1].upper() + name[1:], None
    label = popis[:1] + popis[1:].lower() if popis.isupper() else popis
    label = " ".join(label.split())
    return label[:1].upper() + label[1:], (name if name.lower() != label.lower() else None)


def build(name: str, data: dict, en: dict) -> Graph:
    cls, slug = SCHEMES[name]
    g = bind(Graph())
    scheme = KRIMC[slug]
    label_en, label_cs, definition = SCHEME_TEXT[name]
    g.add((scheme, RDF.type, SKOS.ConceptScheme))
    g.add((scheme, SKOS.prefLabel, Literal(label_en, lang="en")))
    g.add((scheme, SKOS.prefLabel, Literal(label_cs, lang="cs")))
    g.add((scheme, SKOS.definition, Literal(definition, lang="en")))
    g.add((scheme, DCTERMS.source, URIRef(data["iri"])))
    g.add((scheme, SKOS.exactMatch, URIRef(data["iri"])))

    for item in data["polozky"]:
        code = int(item["kod"])
        c = KRIMC[f"{slug}/{code}"]
        g.add((c, RDF.type, SKOS.Concept))
        g.add((c, RDF.type, KRIM[cls]))
        g.add((c, SKOS.inScheme, scheme))
        g.add((c, SKOS.notation, Literal(code, datatype=XSD.integer)))
        g.add((c, SKOS.exactMatch, URIRef(item["iri"])))
        pref, alt = cs_label(item)
        g.add((c, SKOS.prefLabel, Literal(pref, lang="cs")))
        if alt:
            g.add((c, SKOS.altLabel, Literal(alt, lang="cs")))
        lab, defn, bdef = en.get((name, code), (None, None, None))
        if lab:
            g.add((c, SKOS.prefLabel, Literal(lab, lang="en")))
        if defn:
            g.add((c, SKOS.definition, Literal(defn, lang="en")))
        if bdef:
            g.add((c, KRIM.businessDefinition, Literal(bdef, lang="cs")))
        g.add((c, VS.term_status, Literal("stable")))
        # Hierarchy: the deepest non-null ancestor IRI is the direct broader concept.
        parents = [item.get(k) for k in ("iri_3", "iri_2", "iri_1")]
        parent = next((p for p in parents if p), None)
        if parent:
            g.add((c, SKOS.broader, KRIMC[f"{slug}/{int(parent.rstrip('/').rsplit('/', 1)[1])}"]))
        else:
            g.add((c, SKOS.topConceptOf, scheme))
    return g


def main():
    offline = "--offline" in sys.argv
    en = {}
    with open(REF / "codelist-texts.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            en[(row["scheme"], int(row["code"]))] = (row["label_en"] or None, row["definition_en"] or None,
                                                     row["business_definition_cs"] or None)
    for name in SCHEMES:
        g = build(name, fetch(name, offline), en)
        out = REF / f"{name}.ttl"
        header = f"# GENERATED by scripts/build_reference.py from {API}/{name}.json - do not edit.\n"
        out.write_text(header + g.serialize(format="turtle"), encoding="utf-8")
        print(f"{out.relative_to(REF.parent.parent)}: {len(g)} triples")
    g = build_municipalities(fetch_czso(offline), en)
    out = REF / "municipalities.ttl"
    header = f"# GENERATED by scripts/build_reference.py from ČSÚ codelist 43 ({CZSO_PAGE}) - do not edit.\n"
    out.write_text(header + g.serialize(format="turtle"), encoding="utf-8")
    print(f"{out.relative_to(REF.parent.parent)}: {len(g)} triples")


if __name__ == "__main__":
    main()
