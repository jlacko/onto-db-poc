"""Build the data dictionary from the ontology and the SHACL shapes.

One row per database column (an ISO/IEC 11179 data element): object class +
property + value domain, with names, definition, rule, source lineage and
status. Nothing here is written by hand; every field comes from an existing
source (see FIELDS). Used by generate_ddl.py (meta_column table) and
generate_dictionary.py (CSV, Excel, Quarto/PDF).
"""
import re
from dataclasses import dataclass

from rdflib import OWL, RDF, RDFS, SKOS, Literal, URIRef
from rdflib.namespace import SH

from common import KRIM, ONTO, VS, load_graph, model_files
from shapes_model import read_model, table_order

# (field, title, source) - the source column is printed in the document itself.
FIELDS = [
    ("table_name", "Table", "kdb:table"),
    ("column_name", "Column", "kdb:column"),
    ("data_element_en", "Data element (en)", "sh:name@en"),
    ("data_element_cs", "Data element (cs)", "sh:name@cs"),
    ("definition_en", "Definition", "skos:definition of the ontology term, or of the shape for reused properties"),
    ("scope_note_en", "Scope note", "skos:scopeNote of the ontology term"),
    ("object_class_iri", "Object class IRI", "sh:targetClass"),
    ("object_class", "Object class", "rdfs:label of the target class"),
    ("property_iri", "Property IRI", "sh:path"),
    ("property", "Property", "rdfs:label of the property"),
    ("value_domain", "Value domain", "sh:datatype, sh:class, ranges, pattern, languages"),
    ("sql_type", "SQL type", "generated from sh:datatype / referenced key"),
    ("cardinality", "Cardinality", "sh:minCount, sh:maxCount"),
    ("nullable", "Nullable", "sh:minCount"),
    ("key", "Key", "kdb:primaryKey, sh:class"),
    ("business_rule_en", "Business rule", "sh:description"),
    ("source_field", "Source field (CSV)", "kdb:sourceField"),
    ("status", "Status", "vs:term_status"),
    ("ontology_version", "Ontology release", "owl:versionInfo"),
]

# Technical tables: loader bookkeeping, deliberately outside the ontology. The
# publisher's download files are pagination; they matter only for incremental
# refresh, never for the meaning of a record. Declared once here, used by the DDL
# generator and the dictionary (status "technical").
TECHNICAL_TABLES = {
    "source_file": ("A download file of the publisher (monthly pagination) as last read by the loader.", [
        ("name", "TEXT PRIMARY KEY", "file name", "název souboru",
         "The publisher's download name (YYYYMM); pagination only."),
        ("publisher_updated", "TEXT NOT NULL", "publisher updated", "aktualizace vydavatelem",
         "The 'updated' timestamp the publisher's download listing gives for the file; becomes krim:stateAsOf of the records read from it."),
        ("loaded_at", "TEXT NOT NULL", "loaded at", "načteno",
         "When the loader last read the file."),
        ("records_read", "INTEGER NOT NULL", "records read", "načtené záznamy",
         "Distinct records in the file whose report date falls in the loaded year."),
    ]),
    "load_run": ("One run of the loader; the latest finished run is the 'as of' date of the whole database.", [
        ("run_id", "INTEGER PRIMARY KEY", "run id", "identifikátor běhu", "Sequence number of the load run."),
        ("started_at", "TEXT NOT NULL", "started at", "zahájeno", "When the run started."),
        ("finished_at", "TEXT", "finished at", "dokončeno", "When the run finished; empty if it failed."),
        ("year", "INTEGER NOT NULL", "year", "rok", "The report-date year the run covers."),
        ("records_new", "INTEGER", "new records", "nové záznamy", "Records inserted for the first time."),
        ("records_updated", "INTEGER", "updated records", "aktualizované záznamy",
         "Records replaced by a newer observation."),
        ("state_changes", "INTEGER", "state changes", "změny stavu",
         "Updated records whose clearance state changed."),
    ]),
}

PREFIXES = {
    str(KRIM): "krim:",
    "http://www.w3.org/2004/02/skos/core#": "skos:",
    "http://purl.org/dc/terms/": "dcterms:",
    "http://www.w3.org/2001/XMLSchema#": "xsd:",
    "http://www.w3.org/1999/02/22-rdf-syntax-ns#": "rdf:",
}


def curie(iri) -> str:
    s = str(iri)
    for ns, p in PREFIXES.items():
        if s.startswith(ns):
            return p + s[len(ns):]
    return s


def clean(v) -> str:
    return "" if v is None else re.sub(r"\s+", " ", str(v)).strip()


def lang_value(g, s, p, lang="en"):
    for o in g.objects(s, p):
        if isinstance(o, Literal) and o.language == lang:
            return clean(o)
    return None


@dataclass
class Context:
    onto: object
    shapes: object
    version: str
    modified: str


def context() -> Context:
    onto = load_graph(*model_files())
    shapes = load_graph(ONTO / "shapes.ttl")
    head = URIRef(str(KRIM).rstrip("#"))
    return Context(onto, shapes, clean(onto.value(head, OWL.versionInfo)),
                   clean(onto.value(head, URIRef("http://purl.org/dc/terms/modified")))[:10])


def _term(ctx, path, prop, lang="en"):
    """Annotation of an own (krim:) ontology term; None for reused vocabulary."""
    if not str(path).startswith(str(KRIM)):
        return None
    return lang_value(ctx.onto, path, prop, lang)


def _status(ctx, path):
    if str(path).startswith(str(KRIM)):
        return clean(ctx.onto.value(path, VS.term_status)) or "missing"
    return "reused (" + curie(path).split(":")[0] + ")"


def _domain(ctx, tables, c, ps):
    S = ctx.shapes
    if c.references:
        ref = tables[c.references]
        n = len(set(ctx.onto.subjects(RDF.type, ref.target_class)))
        if n:
            return f"code from codelist {ref.name} ({n} values, see appendix)"
        return f"identifier of a row in {ref.name}"
    if c.is_iri:
        return "IRI"
    dt = S.value(ps, SH.datatype)
    parts = [curie(dt)] if dt is not None else []
    lo, hi = S.value(ps, SH.minInclusive), S.value(ps, SH.maxInclusive)
    if lo is not None or hi is not None:
        parts.append(f"from {lo} to {hi}")
    if S.value(ps, SH.pattern) is not None:
        parts.append(f"pattern {S.value(ps, SH.pattern)}")
    if c.lang:
        parts.append(f"text in language '{c.lang}'")
    if dt is not None and curie(dt) == "xsd:boolean":
        parts.append("stored as 1 (true) / 0 (false)")
    if dt is not None and curie(dt) == "xsd:dateTime":
        parts.append("ISO 8601 text, local time with offset where published")
    return "; ".join(parts)


def _cardinality(ctx, c, ps):
    S = ctx.shapes
    if c.lang:
        return "1..1" if c.not_null else "0..1"
    mn = int(S.value(ps, SH.minCount) or 0)
    if c.not_null:
        mn = max(mn, 1)
    mx = S.value(ps, SH.maxCount)
    return f"{mn}..{mx if mx is not None else '*'}"


def build_rows(ctx: Context | None = None) -> list[dict]:
    ctx = ctx or context()
    tables = read_model(ctx.shapes)
    rows = []
    for t in table_order(tables):
        cls_label = lang_value(ctx.onto, t.target_class, RDFS.label) or curie(t.target_class)
        base = {"table_name": t.name, "object_class_iri": str(t.target_class),
                "object_class": cls_label, "ontology_version": ctx.version}
        if t.iri_column:
            rows.append({**base, "column_name": t.iri_column,
                         "data_element_en": f"{cls_label} IRI", "data_element_cs": "IRI",
                         "definition_en": f"The IRI that identifies the {cls_label} in the ontology namespace; "
                                          "the join key between the database row and the ontology.",
                         "scope_note_en": "", "property_iri": "", "property": "(focus node)",
                         "value_domain": "IRI", "sql_type": "TEXT", "cardinality": "1..1", "nullable": "no",
                         "key": "UNIQUE", "business_rule_en": "Every row has exactly one IRI.",
                         "source_field": "", "status": "generated"})
        for c in t.columns:
            ps = c.shape
            name_en = lang_value(ctx.shapes, ps, SH.name, "en") or c.name
            name_cs = lang_value(ctx.shapes, ps, SH.name, "cs") or ""
            if c.lang:
                lang_name = {"cs": ("Czech", "česky"), "en": ("English", "anglicky")}[c.lang]
                name_en, name_cs = f"{name_en} ({lang_name[0]})", f"{name_cs} ({lang_name[1]})"
            definition = (_term(ctx, c.path, SKOS.definition)
                          or lang_value(ctx.shapes, ps, SKOS.definition) or "")
            key = "PK" if c.primary_key else ""
            if c.references:
                key = (key + " " if key else "") + f"FK -> {c.references}({tables[c.references].pk.name})"
            rows.append({**base, "column_name": c.name,
                         "data_element_en": name_en, "data_element_cs": name_cs,
                         "definition_en": definition,
                         "scope_note_en": _term(ctx, c.path, SKOS.scopeNote) or "",
                         "property_iri": str(c.path),
                         "property": _term(ctx, c.path, RDFS.label) or curie(c.path),
                         "value_domain": _domain(ctx, tables, c, ps),
                         "sql_type": c.sql_type, "cardinality": _cardinality(ctx, c, ps),
                         "nullable": "no" if (c.not_null or c.primary_key) else "yes",
                         "key": key, "business_rule_en": clean(c.description),
                         "source_field": c.source_field or "", "status": _status(ctx, c.path)})
        for l in t.links:
            owner_pk, target = t.pk, tables[l.target_table]
            owner_col = f"{t.name}_{owner_pk.name}"
            lbase = {**base, "table_name": l.name}
            rows.append({**lbase, "column_name": owner_col,
                         "data_element_en": f"{cls_label} (owner)", "data_element_cs": "vlastník vazby",
                         "definition_en": f"Identifier of the {cls_label} that the link row belongs to.",
                         "scope_note_en": "", "property_iri": str(owner_pk.path),
                         "property": curie(owner_pk.path), "value_domain": f"identifier of a row in {t.name}",
                         "sql_type": owner_pk.sql_type, "cardinality": "1..1", "nullable": "no",
                         "key": f"PK, FK -> {t.name}({owner_pk.name})",
                         "business_rule_en": "Every link row belongs to exactly one owner.",
                         "source_field": owner_pk.source_field or "", "status": "generated"})
            n = len(set(ctx.onto.subjects(RDF.type, target.target_class)))
            rows.append({**lbase, "column_name": l.column,
                         "data_element_en": lang_value(ctx.shapes, l.shape, SH.name, "en") or l.column,
                         "data_element_cs": lang_value(ctx.shapes, l.shape, SH.name, "cs") or "",
                         "definition_en": _term(ctx, l.path, SKOS.definition) or "",
                         "scope_note_en": _term(ctx, l.path, SKOS.scopeNote) or "",
                         "property_iri": str(l.path), "property": _term(ctx, l.path, RDFS.label) or curie(l.path),
                         "value_domain": f"code from codelist {target.name} ({n} values, see appendix)",
                         "sql_type": target.pk.sql_type,
                         "cardinality": _cardinality(ctx, type("C", (), {"lang": None, "not_null": True})(), l.shape),
                         "nullable": "no", "key": f"PK, FK -> {target.name}({target.pk.name})",
                         "business_rule_en": clean(l.description), "source_field": l.source_field or "",
                         "status": _status(ctx, l.path)})
    for tname, (desc, cols) in TECHNICAL_TABLES.items():
        for col, sql, name_en, name_cs, definition in cols:
            rows.append({"table_name": tname, "column_name": col, "data_element_en": name_en,
                         "data_element_cs": name_cs, "definition_en": definition, "scope_note_en": "",
                         "object_class_iri": "", "object_class": "(technical: loader bookkeeping)",
                         "property_iri": "", "property": "", "value_domain": sql.split()[0].lower(),
                         "sql_type": sql.split()[0], "cardinality": "1..1" if "NOT NULL" in sql or "PRIMARY" in sql else "0..1",
                         "nullable": "no" if ("NOT NULL" in sql or "PRIMARY" in sql) else "yes",
                         "key": "PK" if "PRIMARY" in sql else "", "business_rule_en": desc,
                         "source_field": "", "status": "technical", "ontology_version": ctx.version})
    return rows


def codelists(ctx: Context | None = None) -> dict[str, list[dict]]:
    """Allowed values of every codelist column, from the SKOS reference data."""
    ctx = ctx or context()
    tables = read_model(ctx.shapes)
    out = {}
    for t in table_order(tables):
        if not any(c.path == SKOS.notation for c in t.columns):
            continue
        items = []
        for c in ctx.onto.subjects(RDF.type, t.target_class):
            b = ctx.onto.value(c, SKOS.broader)
            items.append({
                "code": int(ctx.onto.value(c, SKOS.notation)),
                "label_cs": lang_value(ctx.onto, c, SKOS.prefLabel, "cs") or "",
                "label_en": lang_value(ctx.onto, c, SKOS.prefLabel, "en") or "",
                "broader": "" if b is None else str(int(ctx.onto.value(b, SKOS.notation))),
                "definition_en": lang_value(ctx.onto, c, SKOS.definition) or "",
            })
        out[t.name] = sorted(items, key=lambda i: i["code"])
    return out


def table_definitions(ctx: Context | None = None) -> dict[str, tuple[str, str, str]]:
    """table -> (class label, class definition, scope note); link tables describe their property."""
    ctx = ctx or context()
    out = {}
    for t in read_model(ctx.shapes).values():
        out[t.name] = (lang_value(ctx.onto, t.target_class, RDFS.label) or "",
                       lang_value(ctx.onto, t.target_class, SKOS.definition) or "",
                       lang_value(ctx.onto, t.target_class, SKOS.scopeNote) or "")
        for l in t.links:
            out[l.name] = (lang_value(ctx.onto, l.path, RDFS.label) or "",
                           "Link table for the many-valued property " + curie(l.path) + ": "
                           + (lang_value(ctx.onto, l.path, SKOS.definition) or ""),
                           lang_value(ctx.onto, l.path, SKOS.scopeNote) or "")
    for tname, (desc, _) in TECHNICAL_TABLES.items():
        out[tname] = ("technical table (not part of the ontology)", desc, "")
    return out
