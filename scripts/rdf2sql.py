"""Load RDF individuals into SQLite using the relational model read from the shapes.

Used for (a) reference data: codelist tables are filled from the ontology's SKOS
files, so the database and the glossary share one source; and (b) the test
suite: the sample RDF is loaded into a scratch database so every competency
question can be answered in SPARQL and SQL and the results compared.
"""
import sqlite3

from rdflib import RDF, Graph, Literal
from rdflib.namespace import XSD

from shapes_model import Table, read_model, table_order


def _value(g: Graph, node, col, tables):
    if col.references:
        target = g.value(node, col.path)
        return None if target is None else _plain(g.value(target, tables[col.references].pk.path))
    if col.lang:
        for v in g.objects(node, col.path):
            if isinstance(v, Literal) and v.language == col.lang:
                return str(v)
        return None
    v = g.value(node, col.path)
    if v is None:
        return None
    if col.is_iri:
        return str(v)
    return _plain(v)


def _plain(v):
    if v is None:
        return None
    if isinstance(v, Literal):
        if v.datatype == XSD.boolean:
            return int(v.toPython())
        if v.datatype in (XSD.integer, XSD.int, XSD.long):
            return int(v)
        if v.datatype in (XSD.decimal, XSD.double, XSD.float):
            return float(v)
        return str(v)  # dateTime, gYearMonth, strings: ISO lexical form
    return str(v)


def load(g: Graph, con: sqlite3.Connection, only: set[str] | None = None) -> dict[str, int]:
    """Insert every instance of every shape's target class. Returns row counts."""
    tables = read_model()
    counts = {}
    for t in table_order(tables):
        if only and t.name not in only:
            continue
        cols = ([t.iri_column] if t.iri_column else []) + [c.name for c in t.columns]
        sql = f"INSERT INTO {t.name} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})"
        rows, link_rows = [], {l.name: [] for l in t.links}
        for node in sorted(g.subjects(RDF.type, t.target_class)):
            row = ([str(node)] if t.iri_column else []) + [_value(g, node, c, tables) for c in t.columns]
            rows.append(row)
            own_pk = _plain(g.value(node, t.pk.path))
            for l in t.links:
                target_pk = tables[l.target_table].pk
                for v in g.objects(node, l.path):
                    link_rows[l.name].append((own_pk, _plain(g.value(v, target_pk.path))))
        # Self-references (skos:broader) need parents first: insert, then FKs are checked at commit.
        con.executemany(sql, rows)
        counts[t.name] = len(rows)
        for l in t.links:
            con.executemany(f"INSERT INTO {l.name} VALUES (?, ?)", link_rows[l.name])
            counts[l.name] = len(link_rows[l.name])
    return counts
