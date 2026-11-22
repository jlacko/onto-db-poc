"""Build SKOS concept schemes from the publisher's codelists and ČSÚ codelists.

Source: the Police CR API publishes each codelist as JSON-LD in the Czech
open-data codelist format (OFN "číselník"), with an IRI per item. This script
turns them into SKOS, adds the hand-maintained English labels and definitions
from ontology/reference/codelist-texts.csv (English labels and definitions, Czech
business definitions), and writes one Turtle file per scheme.

Territorial units come from the Czech Statistical Office (ČSÚ): codelist 43
(municipalities and military training areas), 65 (ORP areas), 101 (okresy) and
100 (kraje), and ČSÚ's relations between them (municipality -> ORP area, okres;
ORP area, okres -> kraj), all downloaded as CSV. Each download is cached in
build/cache with a .updated stamp and reused for MAX_AGE_DAYS; --offline never
downloads.

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


CZSO = "https://apl2.czso.cz/iSMS/"
MAX_AGE_DAYS = 30
# ČSÚ relation ids (the "cisvaz" export parameter): (from, to) -> id
CZSO_RELATIONS = {(43, 65): "65_1182", (43, 101): "101_333", (65, 100): "100_398", (101, 100): "100_132"}
NUTS = "http://data.europa.eu/nuts/code/"


def czso_page(kodcis: int) -> str:
    return f"{CZSO}cisdet.jsp?kodcis={kodcis}"


def _fresh(stamp) -> bool:
    if not stamp.exists():
        return False
    when = datetime.fromisoformat(stamp.read_text().strip())
    if when.tzinfo is None:
        when = when.astimezone()
    return datetime.now().astimezone() - when < timedelta(days=MAX_AGE_DAYS)


def fetch_czso(kodcis: int, offline: bool, to: int | None = None) -> list[dict]:
    """A ČSÚ codelist (or, with `to`, its relation to another codelist) as rows;
    downloaded at most once per MAX_AGE_DAYS."""
    CACHE.mkdir(parents=True, exist_ok=True)
    name = f"czso-{kodcis}.csv" if to is None else f"czso-{kodcis}-{to}.csv"
    path, stamp = CACHE / name, CACHE / f"{name}.updated"
    if not path.exists() and offline:
        sys.exit(f"{name} is not cached; run once without --offline")
    if not offline and not (path.exists() and _fresh(stamp)):
        query = {"kodcis": kodcis, "typdat": 0, "cisjaz": 203, "format": 2}  # CSV, Czech, valid today
        if to is not None:
            query.update(typdat=1, cisvaz=CZSO_RELATIONS[(kodcis, to)])
        with urllib.request.urlopen(f"{CZSO}do_cis_export?" + urllib.parse.urlencode(query), timeout=60) as r:
            path.write_bytes(r.read())
        stamp.write_text(datetime.now().astimezone().isoformat(timespec="seconds") + "\n")
    return list(csv.DictReader(io.StringIO(path.read_text(encoding="utf-8"))))


def czso_links(kodcis: int, to: int, offline: bool) -> dict[int, int]:
    """{code in kodcis: code in `to`}; fails if an item has more than one."""
    links = {}
    for r in fetch_czso(kodcis, offline, to):
        a, b = int(r["chodnota1"]), int(r["chodnota2"])
        if links.setdefault(a, b) != b:
            sys.exit(f"ČSÚ relation {kodcis} -> {to}: item {a} has two targets ({links[a]}, {b})")
    return links


# Territorial codelists other than municipalities: file, class, slug, labels, definition.
UNITS = {
    65: ("orp-areas", "OrpArea", "orp-area", "ORP areas", "správní obvody ORP",
         "The Czech Statistical Office's codelist of administrative districts of municipalities "
         "with extended powers (ČSÚ codelist 65)."),
    101: ("okresy", "Okres", "okres", "okresy", "okresy",
          "The Czech Statistical Office's codelist of okresy (LAU 1, ČSÚ codelist 101)."),
    100: ("kraje", "Kraj", "kraj", "kraje", "kraje",
          "The Czech Statistical Office's codelist of kraje (NUTS 3, ČSÚ codelist 100)."),
}


def build_units(kodcis: int, rows: list[dict], kraj_of: dict[int, int] | None) -> Graph:
    """ORP areas, okresy or kraje as a SKOS scheme; ORP areas and okresy link to their kraj,
    kraje to their NUTS 3 region. ČSÚ's Extra-Regio item (no territory) is left out."""
    _, cls, slug, label_en, label_cs, definition = UNITS[kodcis]
    g = bind(Graph())
    scheme = KRIMC[slug]
    g.add((scheme, RDF.type, SKOS.ConceptScheme))
    g.add((scheme, SKOS.prefLabel, Literal(label_en, lang="en")))
    g.add((scheme, SKOS.prefLabel, Literal(label_cs, lang="cs")))
    g.add((scheme, SKOS.definition, Literal(definition, lang="en")))
    g.add((scheme, DCTERMS.source, URIRef(czso_page(kodcis))))
    for row in rows:
        if row.get("cznuts", "").startswith("CZZZ"):
            continue  # Extra-Regio
        code = int(row["chodnota"])
        c = KRIMC[f"{slug}/{code}"]
        g.add((c, RDF.type, SKOS.Concept))
        g.add((c, RDF.type, KRIM[cls]))
        g.add((c, SKOS.inScheme, scheme))
        g.add((c, SKOS.topConceptOf, scheme))
        g.add((c, SKOS.notation, Literal(code, datatype=XSD.integer)))
        g.add((c, SKOS.prefLabel, Literal(row["text"].strip(), lang="cs")))
        g.add((c, VS.term_status, Literal("stable")))
        if kraj_of is not None:
            g.add((c, KRIM.inKraj, KRIMC[f"kraj/{kraj_of[code]}"]))
        if kodcis == 100:
            g.add((c, SKOS.exactMatch, URIRef(NUTS + row["cznuts"])))
    return g


def build_municipalities(rows: list[dict], texts: dict, orp_of: dict[int, int],
                         okres_of: dict[int, int]) -> Graph:
    g = bind(Graph())
    scheme = KRIMC["municipality"]
    g.add((scheme, RDF.type, SKOS.ConceptScheme))
    g.add((scheme, SKOS.prefLabel, Literal("municipalities", lang="en")))
    g.add((scheme, SKOS.prefLabel, Literal("obce", lang="cs")))
    g.add((scheme, SKOS.definition, Literal(
        "The Czech Statistical Office's codelist of municipalities and military training areas (ČSÚ codelist 43).",
        lang="en")))
    g.add((scheme, DCTERMS.source, URIRef(czso_page(43))))
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
        g.add((c, KRIM.inOrpArea, KRIMC[f"orp-area/{orp_of[code]}"]))
        g.add((c, KRIM.inOkres, KRIMC[f"okres/{okres_of[code]}"]))
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
    graphs = {"municipalities": (43, build_municipalities(
        fetch_czso(43, offline), en, czso_links(43, 65, offline), czso_links(43, 101, offline)))}
    for kodcis, (file, *_) in UNITS.items():
        kraj_of = czso_links(kodcis, 100, offline) if kodcis != 100 else None
        graphs[file] = (kodcis, build_units(kodcis, fetch_czso(kodcis, offline), kraj_of))
    for file, (kodcis, g) in graphs.items():
        out = REF / f"{file}.ttl"
        header = (f"# GENERATED by scripts/build_reference.py from ČSÚ codelist {kodcis} "
                  f"({czso_page(kodcis)}) - do not edit.\n")
        out.write_text(header + g.serialize(format="turtle"), encoding="utf-8")
        print(f"{out.relative_to(REF.parent.parent)}: {len(g)} triples")


if __name__ == "__main__":
    main()
