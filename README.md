# onto-db-poc

Proof of concept of the **ontology-first** approach to database creation, following
`llm-readable-ontologies.pdf`. The main aim is to validate the LLM ontology method
itself. The secondary aim is to prove it can drive a real database: SQLite,
populated with a continuous, duplicate-free history of Czech crime records from the Police CR API
(`kriminalita.policie.gov.cz`).

**Status:** first version merged to `main` and tagged `v0.1.0` (ontology 0.1.0),
the baseline for further iterations. From here on, terms are deprecated, not
renamed or removed.

## The sequence (adapted from PDF part I)

| Step | Here |
|---|---|
| Concepts and how they relate (*our addition, not in the PDF*) | [`ontology/concepts.md`](ontology/concepts.md): seven sentences in domain language, one per relationship, both ends ("a record has one or more offence types; a type covers any number of records"), judged by the domain expert and traced to the SHACL shape that enforces it |
| Competency questions | [`ontology/competency-questions.md`](ontology/competency-questions.md): an editable worksheet with executable `expected` answers. Some are left for the domain expert to answer by hand (✍). |
| Reuse survey | SKOS (codelists), DCTERMS, DCAT, PROV-O, W3C WGS84, VS term status; the publisher's own codelist IRIs linked with `skos:exactMatch` |
| Skeleton + definitions | [`ontology/kriminalita.ttl`](ontology/kriminalita.ttl): 6 classes, 12 own properties (2 deprecated), en/cs labels, genus–differentia definitions, scope notes, sources |
| Reference data | [`ontology/reference/`](ontology/reference/): SKOS schemes generated from the publisher's JSON-LD codelists plus hand-kept English labels |
| Closed-world rules | [`ontology/shapes.ttl`](ontology/shapes.ttl): SHACL, every rule also stated as a plain sentence |
| Validation loop | [`scripts/validate.py`](scripts/validate.py): parse, HermiT, concept statements vs shapes, lint, SHACL (+ negative tests), artifact drift, CQ tests |
| Test suite | [`ontology/tests/`](ontology/tests/): 13 sample records in 16 anonymisation areas, 10 invalid individuals, 23 CQs in SPARQL and SQL |
| Data model (part III) | [`db/schema.sql`](db/schema.sql), **generated** from the shapes |
| Data dictionary | **generated** from ontology + shapes: `meta_column` table, [`db/data-dictionary.csv`](db/data-dictionary.csv), [`db/data-dictionary.xlsx`](db/data-dictionary.xlsx) (for review), [`docs/data-dictionary.pdf`](docs/data-dictionary.pdf) |
| Business glossary (Czech) | **generated** from Czech annotations on the ontology: [`docs/glossary.pdf`](docs/glossary.pdf) ("Slovník pojmů"; English internals, Czech business translations) |
| Write-ups | [`docs/action-plan.pdf`](docs/action-plan.pdf), [`docs/lessons-learned.pdf`](docs/lessons-learned.pdf) |

## Run it

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

```bash
.venv/bin/python scripts/validate.py
```

```bash
.venv/bin/python scripts/load.py --year 2025
```

Downloads are cached in `build/cache/zips/`; a file is fetched again only if the
publisher has a newer version and the cached copy is older than `--max-age-days`
(default 7). `--offline` uses the cache only.

Regenerate the generated artifacts after changing their sources:

```bash
.venv/bin/python scripts/build_reference.py && .venv/bin/python scripts/generate_ddl.py && .venv/bin/python scripts/render_sample.py && .venv/bin/python scripts/cq_index.py && .venv/bin/python scripts/generate_dictionary.py --pdf && .venv/bin/python scripts/generate_glossary.py --pdf
```

Requires Java (HermiT runs through owlready2) and, for the PDFs, Quarto with a LaTeX engine and Graphviz.

## What the method caught (findings log)

The case for the method is what the mechanical loop found that a plausible-looking
ontology would have hidden:

1. **Not valid OWL 2 DL.** HermiT rejected `xsd:gYearMonth` (reference month) and
   then `xsd:date` (ontology header): neither is in the OWL 2 datatype map. Fixed:
   `xsd:string` plus a SHACL pattern, and `xsd:dateTime`.
2. **SHACL severity is per shape.** `sh:severity sh:Warning` on a node shape is not
   inherited by its property shapes, so a "should" rule fired as a hard violation.
   This was caught because the sample data deliberately contains one warning case.
3. **Silent zero results in SPARQL.** rdflib's SPARQL parser mishandles the escaped
   local name `krimc:type\/18`, so queries ran but matched nothing. Caught only by the
   SPARQL-vs-SQL parity check; a single query layer would have reported "0 burglaries".
4. **A loader bug.** The generic RDF→SQL loader read foreign-key codes from the wrong
   node; the NOT NULL constraint generated from `sh:minCount 1` stopped it.
5. **A wrong meaning, fixed before release.** The timestamp was first modelled as
   "incident date and time". The publisher's help pages show it is the date of
   report/registration, so the property became `krim:reportDateTime` (renaming is
   allowed only because 0.1.0 was not yet released).
6. **An undocumented field.** `mp` = municipal police, corroborated by the OpenAPI
   description; it carries an editorial note until the publisher confirms.
7. **A publisher documentation error.** The OpenAPI description labels `x` as
   latitude and `y` as longitude, which is the wrong way round. The explicit
   definitions plus the `kdb:sourceField` mapping keep the database correct.
8. **The source's packaging leaked into the model** (caught by the domain expert, not
   by any tool). Version 0.1.0 modelled the publisher's monthly download files as a
   domain concept, and four competency questions grouped by them. The files are
   pagination; the goal is a continuous history with one row per occurrence in its
   latest state. The extract concept was removed before release, replaced by
   `krim:stateAsOf`, a uniqueness rule and a tested "latest observation wins" merge.
9. **A legitimate limit of the RDF test layer.** SPARQL 1.1 has no weekday
   function, so CQ16 is tested in SQL only.
10. **Answering by hand finds what queries cannot.** The domain expert answered five
    questions by hand; reaching agreement took ten disagreements: three slips by the
    expert, five imprecise questions or data presentations, two validator faults.
    Each side was wrong at least once, so neither is treated as the oracle.

Iteration 2 (anonymisation areas and municipalities, after release 0.1.0):

11. **A domain fact found after release.** Every published location is the centre
    of one of 39,927 predefined areas (Voronoi polygons), each in one municipality;
    found by the domain expert on the publisher's website. The record's coordinates
    were deprecated, replaced by a link to its area; every 2025 point matches an
    area's centre.
12. **A name that fits, a definition that does not.** GeoSPARQL's `hasCentroid`
    (the arithmetic mean of a geometry) is not the publisher's centre (a K-means
    cluster centre), so it was not reused.
13. **A domain decision no file holds.** ČSÚ codelist 43 includes four military
    training areas, which are not municipalities in law; the expert decided they
    count as municipalities here.
14. **A correct schema, too slow at real volume.** The first quality check on the
    new foreign key ran for over ten minutes with no index; the generator now
    indexes every foreign-key column, plus `kdb:index` and `kdb:uniqueColumns`
    hints. A full rebuild takes under two minutes.

## Layout

See [`CLAUDE.md`](CLAUDE.md) for conventions, namespaces and what is generated vs.
hand-edited.

## Data source and licence

Police of the Czech Republic, *Mapa kriminality*, https://kriminalita.policie.gov.cz
(open data; cite the source when redistributing). Locations are anonymised to
Voronoi-polygon centres by the publisher.
