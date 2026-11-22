"""Read the SHACL shapes into a small relational model (tables and columns).

This is the bridge from the ontology to the data model (PDF part III): each
node shape with kdb:table becomes a table, each property shape a column, a
foreign key or a link table. Both the DDL generator and the RDF -> SQLite
loader use this one interpretation.
"""
from dataclasses import dataclass, field

from rdflib import RDF, Graph, URIRef
from rdflib.collection import Collection
from rdflib.namespace import SH, XSD

from common import KDB, ONTO, load_graph

SQL_TYPES = {
    XSD.integer: "INTEGER",
    XSD.decimal: "REAL",
    XSD.double: "REAL",
    XSD.boolean: "INTEGER",
    XSD.string: "TEXT",
    XSD.dateTime: "TEXT",
    XSD.date: "TEXT",
    XSD.gYearMonth: "TEXT",
    RDF.langString: "TEXT",
}


@dataclass
class Column:
    name: str
    path: URIRef
    sql_type: str = "TEXT"
    not_null: bool = False
    primary_key: bool = False
    references: str | None = None  # table name
    lang: str | None = None  # for language columns
    checks: list[str] = field(default_factory=list)
    description: str = ""
    source_field: str | None = None
    is_iri: bool = False  # value is an IRI (stored as text)
    index: bool = False  # kdb:index: a secondary index (foreign keys get one anyway)
    shape: object = None  # the SHACL property shape this column realises


@dataclass
class LinkTable:
    name: str
    path: URIRef
    owner_table: str
    target_table: str
    column: str
    description: str = ""
    source_field: str | None = None
    shape: object = None


@dataclass
class Table:
    name: str
    shape: URIRef
    target_class: URIRef
    iri_column: str | None
    columns: list[Column] = field(default_factory=list)
    links: list[LinkTable] = field(default_factory=list)
    unique_keys: list[list[str]] = field(default_factory=list)  # kdb:uniqueColumns (column names)

    @property
    def pk(self) -> Column:
        return next(c for c in self.columns if c.primary_key)


def _str(g, s, p):
    v = g.value(s, p)
    return None if v is None else str(v)


def _en(g, s, p):
    """The English value of a multilingual annotation (falls back to any)."""
    vals = list(g.objects(s, p))
    for v in vals:
        if getattr(v, "language", None) == "en":
            return str(v)
    return str(vals[0]) if vals else None


def _property_shapes(g: Graph, shape):
    """Own property shapes plus those inherited through sh:node, in sh:order."""
    props = list(g.objects(shape, SH.property))
    for parent in g.objects(shape, SH.node):
        props = list(g.objects(parent, SH.property)) + props
    return sorted(props, key=lambda p: float(g.value(p, SH.order) or 99))


def read_model(g: Graph | None = None) -> dict[str, Table]:
    g = g or load_graph(ONTO / "shapes.ttl")
    tables: dict[str, Table] = {}
    class_to_table: dict[URIRef, str] = {}
    shapes = [s for s in g.subjects(KDB.table, None)]
    for s in shapes:
        t = Table(_str(g, s, KDB.table), s, g.value(s, SH.targetClass), _str(g, s, KDB.iriColumn))
        for key in g.objects(s, KDB.uniqueColumns):
            t.unique_keys.append([str(x) for x in Collection(g, key)])
        tables[t.name] = t
        class_to_table[t.target_class] = t.name

    for t in tables.values():
        for ps in _property_shapes(g, t.shape):
            col = _str(g, ps, KDB.column)
            if col is None:
                continue  # constraint-only shape (e.g. a stricter minCount), no column
            path = g.value(ps, SH.path)
            desc = _en(g, ps, SH.description) or ""
            src = _str(g, ps, KDB.sourceField)
            min_count = int(g.value(ps, SH.minCount) or 0)
            target_cls = g.value(ps, SH["class"])
            # A constraint-only shape on the same path in this table's own shape can tighten minCount.
            for other in g.objects(t.shape, SH.property):
                if g.value(other, SH.path) == path and g.value(other, KDB.column) is None:
                    min_count = max(min_count, int(g.value(other, SH.minCount) or 0))

            link = _str(g, ps, KDB.linkTable)
            if link:
                t.links.append(LinkTable(link, path, t.name, class_to_table[target_cls], col, desc, src, ps))
                continue

            langs = g.value(ps, KDB.languageColumns)
            if langs is not None:
                qual_langs = set()
                q = g.value(ps, SH.qualifiedValueShape)
                if q is not None and int(g.value(ps, SH.qualifiedMinCount) or 0) > 0:
                    qual_langs = {str(x) for x in Collection(g, g.value(q, SH.languageIn))}
                for lang in Collection(g, langs):
                    t.columns.append(Column(f"{col}_{lang}", path, "TEXT", str(lang) in qual_langs,
                                            lang=str(lang), description=desc, shape=ps))
                continue

            c = Column(col, path, not_null=min_count > 0,
                       primary_key=bool(g.value(ps, KDB.primaryKey)), description=desc, source_field=src,
                       shape=ps, index=bool(g.value(ps, KDB["index"])))  # KDB.index would be str.index
            if target_cls is not None:
                c.references = class_to_table[target_cls]
            elif g.value(ps, SH.nodeKind) == SH.IRI:
                c.is_iri = True
            else:
                dt = g.value(ps, SH.datatype)
                c.sql_type = SQL_TYPES[dt]
                if dt == XSD.boolean:
                    c.checks.append(f"{col} IN (0, 1)")
                lo, hi = g.value(ps, SH.minInclusive), g.value(ps, SH.maxInclusive)
                if lo is not None:
                    c.checks.append(f"{col} >= {lo}")
                if hi is not None:
                    c.checks.append(f"{col} <= {hi}")
                pattern = _str(g, ps, SH.pattern)
                if pattern == "^[0-9]{6}$":  # translate the one regex we use into GLOB
                    c.checks.append(f"{col} GLOB '[0-9][0-9][0-9][0-9][0-9][0-9]'")
            t.columns.append(c)

    # FK column types follow the referenced primary key.
    for t in tables.values():
        for c in t.columns:
            if c.references:
                c.sql_type = tables[c.references].pk.sql_type
    return tables


def table_order(tables: dict[str, Table]) -> list[Table]:
    """Referenced tables first."""
    done, out = set(), []

    def visit(t: Table):
        if t.name in done:
            return
        done.add(t.name)
        for c in t.columns:
            if c.references and c.references != t.name:
                visit(tables[c.references])
        out.append(t)

    for t in sorted(tables.values(), key=lambda t: t.name):
        visit(t)
    return out
