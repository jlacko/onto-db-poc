"""Generate the Czech business glossary ("Slovník pojmů") from the ontology.

    .venv/bin/python scripts/generate_glossary.py          # Quarto source + diagram source
    .venv/bin/python scripts/generate_glossary.py --pdf    # ... and render docs/glossary.pdf

English internals, Czech business translations: every entry comes from Czech
annotations on the ontology terms (rdfs:label@cs, krim:businessDefinition@cs,
skos:example@cs, skos:scopeNote@cs, skos:altLabel@cs), codelists from the SKOS
reference data, rules from sh:description@cs / sh:message@cs on the shapes,
examples from the sample data. The only text written here is the document frame.
Outputs (generated, never edited by hand):
  docs/glossary.qmd, docs/img/concepts.dot (-> .pdf), docs/glossary.pdf
"""
import subprocess
import sys
from datetime import datetime

from rdflib import OWL, RDF, RDFS, SKOS, Literal, URIRef
from rdflib.namespace import DCTERMS, SH

from common import KRIM, ONTO, ROOT, TESTS, load_graph, model_files
from dictionary import build_rows, context, lang_value, clean
from shapes_model import read_model

DOCS = ROOT / "docs"
IMG = DOCS / "img"
CZ_ORDER = "aábcčdďeéěfghchiíjklmnňoópqrřsštťuúůvwxyýzž"


def czech_key(s: str):
    """Approximate Czech collation (ch after h, háčky after the base letter)."""
    s, out, i = s.lower(), [], 0
    while i < len(s):
        if s[i:i + 2] == "ch":
            out.append(CZ_ORDER.index("ch")); i += 2; continue
        ch = s[i]
        out.append(CZ_ORDER.index(ch) if ch in CZ_ORDER else 100 + ord(ch))
        i += 1
    return out


def esc(s) -> str:
    s = clean(s)
    for a, b in (("\\", "\\\\"), ("|", "\\|"), ("$", "\\$"), ("^", "\\^"), ("*", "\\*"), ("<", "\\<"), ("_", "\\_")):
        s = s.replace(a, b)
    return s


def breakable(name: str) -> str:
    """A table.column name that LaTeX may wrap after '.' and '_' (narrow table cells)."""
    return "\\texttt{" + esc(name).replace(".", ".\\allowbreak{}").replace("\\_", "\\_\\allowbreak{}") + "}"


def lower_first(s: str) -> str:
    return s[:1].lower() + s[1:] if s else s


def cs_date(dt: str, with_time=True) -> str:
    d = datetime.fromisoformat(str(dt))
    return f"{d.day}. {d.month}. {d.year}" + (f", {d.hour}:{d.minute:02d}" if with_time else "")


def cs(g, s, p):
    return lang_value(g, s, p, "cs")


# --------------------------------------------------------------------------- terms
def glossary_terms(ctx):
    g = ctx.onto
    terms = [t for t in g.subjects(KRIM.businessDefinition, None)
             if str(t).startswith(str(KRIM)) and (t, RDF.type, OWL.AnnotationProperty) not in g]
    return sorted(set(terms), key=lambda t: czech_key(cs(g, t, RDFS.label) or ""))


def dictionary_links(ctx):
    """term IRI -> where it is realised in the (English) data dictionary."""
    links = {}
    for r in build_rows(ctx):
        if r["status"] in ("technical", "generated"):
            continue
        if r["property_iri"]:
            links.setdefault(r["property_iri"], []).append(f"{r['table_name']}.{r['column_name']}")
        links.setdefault(r["object_class_iri"], [])
        if r["table_name"] not in links[r["object_class_iri"]] and "_type" not in r["table_name"]:
            links[r["object_class_iri"]].append(r["table_name"])
    return links


def terms_table(ctx) -> list[str]:
    g, links = ctx.onto, dictionary_links(ctx)
    o = ["| Pojem | Význam | Příklad | Nezaměňovat s | Také nazýváno | V datovém slovníku |",
         "|---|---|---|---|---|---|"]
    for t in glossary_terms(ctx):
        alt = ", ".join(sorted(clean(a) for a in g.objects(t, SKOS.altLabel) if getattr(a, "language", None) == "cs"))
        en = lang_value(g, t, RDFS.label, "en")
        where = links.get(str(t), [])
        ref = f"*{esc(en)}*" + ("; " + ", ".join(breakable(w) for w in where) if where else "")
        o.append(f"| **{esc(cs(g, t, RDFS.label))}** | {esc(cs(g, t, KRIM.businessDefinition))} | "
                 f"{esc(cs(g, t, SKOS.example) or '')} | {esc(cs(g, t, SKOS.scopeNote) or '')} | {esc(alt)} | {ref} |")
    o += ["", ': Pojmy {tbl-colwidths="[13,24,13,24,8,18]"}', ""]
    return o


# ------------------------------------------------------------------------- diagram
def concept_dot(ctx) -> str:
    """Concept diagram from the shapes: classes, their attributes and relations (Czech labels)."""
    g, S = ctx.onto, ctx.shapes
    tables = read_model(S)
    label = lambda iri: cs(g, iri, RDFS.label) or str(iri)
    o = ['digraph concepts {', '  graph [rankdir=LR, fontname="Noto Sans", nodesep=0.5, ranksep=1.1];',
         '  node [shape=box, style="rounded,filled", fillcolor="#eef2f5", color="#36444e", fontname="Noto Sans", fontsize=11];',
         '  edge [color="#36444e", fontname="Noto Sans", fontsize=9];']
    for t in tables.values():
        attrs = [cs(S, c.shape, SH.name) for c in t.columns
                 if not c.references and not c.lang and not c.is_iri and c.path != SKOS.definition]
        title = label(t.target_class)
        if t.name == "offence_record":
            body = "\\l".join(attrs) + "\\l"
            o.append(f'  {t.name} [label="{title}\\n\\n{body}", fillcolor="#dbe6ee"];')
        else:
            o.append(f'  {t.name} [label="{title}"];')
    def card(ps):
        mn, mx = S.value(ps, SH.minCount), S.value(ps, SH.maxCount)
        return f"{mn or 0}..{mx if mx is not None else '*'}"
    for t in tables.values():
        for c in t.columns:
            if c.references and c.references != t.name:
                o.append(f'  {t.name} -> {c.references} [label="{cs(S, c.shape, SH.name)} ({card(c.shape)})"];')
            elif c.references == t.name:
                o.append(f'  {t.name} -> {t.name} [label="{cs(S, c.shape, SH.name)} ({card(c.shape)})"];')
        for l in t.links:
            o.append(f'  {t.name} -> {l.target_table} [label="{cs(S, l.shape, SH.name)} ({card(l.shape)})"];')
    o.append("}")
    return "\n".join(o) + "\n"


# ----------------------------------------------------------------------- codelists
def codelist_tables(ctx) -> list[str]:
    g = ctx.onto
    o = []
    for cls in (KRIM.ClearanceState, KRIM.LocationRelevance):
        o += [f"## {cs(g, cls, RDFS.label).capitalize()}", "", esc(cs(g, cls, KRIM.businessDefinition)), "",
              "| Kód | Název | Význam |", "|---|---|---|"]
        for c in sorted(g.subjects(RDF.type, cls), key=lambda c: int(g.value(c, SKOS.notation))):
            o.append(f"| {g.value(c, SKOS.notation)} | {esc(lang_value(g, c, SKOS.prefLabel, 'cs'))} | "
                     f"{esc(cs(g, c, KRIM.businessDefinition) or '')} |")
        o += ["", f': {cs(g, cls, RDFS.label).capitalize()} {{tbl-colwidths="[8,30,62]"}}', ""]
    return o


def type_tree(ctx) -> list[str]:
    g = ctx.onto
    types = list(g.subjects(RDF.type, KRIM.OffenceType))
    children = {}
    for t in types:
        children.setdefault(g.value(t, SKOS.broader), []).append(t)
    code = lambda t: int(g.value(t, SKOS.notation))
    o = ["| Kód | Třída deliktu | Kód | Třída deliktu |", "|---|---|---|---|"]
    lines = []

    def walk(t, depth):
        lab = esc(lang_value(g, t, SKOS.prefLabel, "cs"))
        lines.append((code(t), ("**" + lab + "**") if depth == 0 else ("— " * depth) + lab))
        for c in sorted(children.get(t, []), key=code):
            walk(c, depth + 1)

    for top in sorted(children.get(None, []), key=code):
        walk(top, 0)
    half = (len(lines) + 1) // 2
    for i in range(half):
        a = lines[i]
        b = lines[half + i] if half + i < len(lines) else ("", "")
        o.append(f"| {a[0]} | {a[1]} | {b[0]} | {b[1]} |")
    o += ["", ': Třídy deliktů podle kategorií (tučně kategorie, pomlčkou podtřídy) {tbl-colwidths="[6,44,6,44]"}', ""]
    return o


# --------------------------------------------------------------------------- rules
def rules(ctx) -> tuple[list[str], list[str]]:
    S = ctx.shapes
    must, should = [], []
    shapes = sorted(S.subjects(SH.targetClass, KRIM.OffenceRecord), key=str)
    for shape in shapes:
        node_warning = S.value(shape, SH.severity) == SH.Warning
        for ps in sorted(S.objects(shape, SH.property), key=lambda p: float(S.value(p, SH.order) or 99)):
            text = cs(S, ps, SH.description)
            if text:
                (should if (S.value(ps, SH.severity) == SH.Warning or node_warning) else must).append(text)
        for sp in S.objects(shape, SH.sparql):
            text = cs(S, sp, SH.message)
            if text:
                (should if (S.value(sp, SH.severity) == SH.Warning or node_warning) else must).append(text)
    return must, should


# ------------------------------------------------------------------------ examples
def examples(ctx) -> list[str]:
    g = load_graph(*model_files(), TESTS / "sample-data.ttl")
    recs = sorted(g.subjects(RDF.type, KRIM.OffenceRecord), key=lambda r: int(g.value(r, DCTERMS.identifier)))
    label = lambda c: lang_value(g, c, SKOS.prefLabel, "cs")

    def top(t):
        while g.value(t, SKOS.broader) is not None:
            t = g.value(t, SKOS.broader)
        return t

    picked, seen = [], set()
    for r in recs:
        types = set(g.objects(r, KRIM.hasOffenceType))
        tops = {top(t) for t in types}
        st, rel = g.value(r, KRIM.hasClearanceState), g.value(r, KRIM.hasLocationRelevance)
        features = []
        if len(tops) > 1:
            features.append("multi")
        if int(g.value(st, SKOS.notation)) in (3, 4):
            features.append("state")
        if int(g.value(rel, SKOS.notation)) in (5, 6):
            features.append("place")
        if not features and not picked:
            features.append("plain")
        new = [f for f in features if f not in seen]
        if new:
            seen |= set(new)
            picked.append((r, types, tops, st, rel, features))
    o = []
    for r, types, tops, st, rel, features in picked:
        specific = [t for t in types if not any((n, SKOS.broader, t) in g for n in types)]
        named = sorted(label(t) if top(t) == t else f"{label(top(t))}: {lower_first(label(t))}" for t in specific)
        o.append(f"**Záznam {g.value(r, DCTERMS.identifier)}.** "
                 f"{'; '.join(named)}; oznámeno {cs_date(g.value(r, KRIM.reportDateTime))}; "
                 f"stav objasnění: {lower_first(label(st))}; místo: {lower_first(label(rel))}; "
                 f"stav ke dni {cs_date(g.value(r, KRIM.stateAsOf), False)}.")
        notes = []
        if "multi" in features:
            notes.append("Záznam spadá do více kategorií (" + ", ".join(sorted(label(t) for t in tops))
                         + "); v počtech za kategorie se objeví v každé z nich, v celkovém počtu jen jednou.")
        if "state" in features:
            notes.append("Záznam v datech zůstává, přestože policie dospěla k závěru, že se skutek nestal "
                         "nebo není trestným činem; "
                         "zda se má započítat do míry objasněnosti, je rozhodnutí (CQ03).")
        if "place" in features:
            notes.append("Zveřejněné místo není místem spáchání a poloha může ležet i mimo Českou republiku; "
                         "kontrola proto vydá jen varování, nikoli chybu.")
        if "plain" in features:
            notes.append("Běžný případ: záznam nese podtřídu i její kategorii.")
        o.append(" ".join(notes))
        o.append("")
    return o


# ---------------------------------------------------------------------------- doc
def to_qmd(ctx) -> str:
    must, should = rules(ctx)
    o = [
        "---",
        'title: "Slovník pojmů"',
        f'subtitle: "Kriminalita: obchodní pojmy, ontologie verze {ctx.version} ({ctx.modified})"',
        "lang: cs",
        "format:",
        "  pdf:",
        "    documentclass: scrartcl",
        "    papersize: a4",
        "    classoption: [landscape]",
        "    toc: true",
        "    toc-depth: 1",
        "    number-sections: true",
        "    colorlinks: true",
        '    mainfont: "Noto Serif"',
        '    sansfont: "Noto Sans"',
        '    monofont: "Noto Sans Mono"',
        "    fontsize: 9pt",
        "    geometry: [landscape, margin=1.6cm]",
        "---",
        "",
        "<!-- GENERATED by scripts/generate_glossary.py - do not edit. -->",
        "",
        "# O slovníku",
        "",
        "Slovník vysvětluje obchodní pojmy datové sady *Mapa kriminality* Policie ČR tak, jak je",
        "chápe ontologie projektu. Ontologie je vedena anglicky; české pojmy a definice jsou",
        "její obchodní překlad a jsou uloženy přímo u pojmů ontologie, odkud se tento dokument",
        "generuje. Technický popis tabulek a sloupců je v anglickém **datovém slovníku**",
        "(`docs/data-dictionary.pdf`); sloupec *V datovém slovníku* ukazuje, kde se pojem v datech",
        "nachází.",
        "",
        f"Stav: **pracovní verze** (ontologie {ctx.version}). Definice čekají na revizi; pojmy",
        "*přestupek*, *trestný čin*, *kategorie* a *míra objasněnosti* budou doplněny po",
        "rozhodnutí v kompetenčních otázkách.",
        "",
        "# Přehled pojmů",
        "",
        "![Hlavní pojmy a jejich vztahy (s násobností)](img/concepts.pdf){width=95%}",
        "",
        "\\newpage",
        "",
        "# Pojmy",
        "",
        *terms_table(ctx),
        "\\newpage",
        "",
        "# Obchodní pravidla",
        "",
        "Pravidla, která musí platit pro každý záznam (jejich porušení je chyba):",
        "",
        *[f"{i}. {esc(t)}" for i, t in enumerate(must, 1)],
        "",
        "Doporučení (jejich porušení je jen varování, protože jde o zvyklosti zdroje, nikoli o pravidla věci):",
        "",
        *[f"{i}. {esc(t)}" for i, t in enumerate(should, 1)],
        "",
        "# Příklady",
        "",
        "Příklady pocházejí z testovacích dat projektu (smyšlené záznamy se skutečnými kódy).",
        "",
        *examples(ctx),
        "\\newpage",
        "",
        "# Číselníky",
        "",
        *codelist_tables(ctx),
        "## Třídy deliktů",
        "",
        "Názvy tříd přebírá slovník od vydavatele (Číselník tříd). Záznam nese svou třídu spolu se",
        "všemi nadřazenými třídami.",
        "",
        *type_tree(ctx),
    ]
    return "\n".join(o)


def outputs():
    ctx = context()
    return ctx, {DOCS / "glossary.qmd": to_qmd(ctx), IMG / "concepts.dot": concept_dot(ctx)}


def main():
    ctx, texts = outputs()
    for path, text in texts.items():
        path.parent.mkdir(exist_ok=True)
        path.write_text(text, encoding="utf-8")
        print(f"wrote {path.relative_to(ROOT)}")
    subprocess.run(["dot", "-Tpdf", str(IMG / "concepts.dot"), "-o", str(IMG / "concepts.pdf")], check=True)
    print(f"wrote {(IMG / 'concepts.pdf').relative_to(ROOT)}")
    if "--pdf" in sys.argv:
        subprocess.run(["quarto", "render", str(DOCS / "glossary.qmd")], check=True)


if __name__ == "__main__":
    main()
