# onto-db-poc

**The chief output of this project is a guide: [*Building and Running Ontologies
with LLMs*](docs/guide.pdf)** (draft; source [`docs/guide.qmd`](docs/guide.qmd)).
It describes a method for building an ontology with a large language model and
keeping it useful to everyone who depends on it: the LLM that drafts it, the
domain expert who judges it, the business readers who use its terms, and the
database it drives.

| Part | Covers |
|---|---|
| I. Authoring | the sequence of steps and who does each (LLM drafts, expert decides, scripts repeat); seven practices, from stating how concepts relate to a mechanical validation loop |
| II. Sharing | business glossary and data dictionary generated from the ontology, in the format each reader's task needs |
| III. Ontology and data | concepts, terms and data elements; SHACL shapes as the bridge to a relational schema, physical design included; codelists versus datasets; continuous history |
| IV. Lifecycle | releases, deprecation, and iterating on a released model |
| Appendices | typical LLM errors; the technical stack |

A 16-slide summary of the process, in the JLA presentation layout:
[`docs/slides.pdf`](docs/slides.pdf) (source [`docs/slides.qmd`](docs/slides.qmd)).

Everything else in this repository exists to test and illustrate that guide.
The method started from `llm-readable-ontologies.pdf` (an inspiration, not a
template) and was revised by doing: every practice in the guide is drawn from
what happened here, including what went wrong.

## The worked example: a means to an end

To test the method on real data, it was applied end to end to the offence
records published by the Police of the Czech Republic
(`kriminalita.policie.gov.cz`): an ontology, its validation loop, a generated
SQLite database holding a continuous, duplicate-free history of 1.38 million
records for 2025, a data dictionary and a Czech business glossary. The database
proves that the ontology can drive a real data model; it is not the goal in
itself.

The example was built in three iterations, each a full pass through the method:

| Release | Iteration |
|---|---|
| `v0.1.0` | offence records, types, clearance states, location relevance |
| `v0.2.0` | anonymisation areas (39,927 predefined polygons) and municipalities (ČSÚ codelist 43); the record's coordinates deprecated |
| `v0.3.0` (current, on `main`) | ORP areas, okresy and kraje (ČSÚ codelists 65, 101, 100), two branches meeting at the kraj; all 29 competency questions pass |

Terms are deprecated, not renamed or removed. How each step went, and what it
taught, is written up in two companion documents:
[`docs/lessons-learned.pdf`](docs/lessons-learned.pdf) (the evidence behind the
guide) and [`docs/action-plan.pdf`](docs/action-plan.pdf) (step by step, all
three iterations).

## The method as applied here

| Step | Here |
|---|---|
| Concepts and how they relate | [`ontology/concepts.md`](ontology/concepts.md): twelve sentences in domain language, one per relationship, both ends ("a record has one or more offence types; a type covers any number of records"), judged by the domain expert and traced to the SHACL shape that enforces it |
| Competency questions | [`ontology/competency-questions.md`](ontology/competency-questions.md): an editable worksheet with executable `expected` answers. Where the answer depends on a design decision, the domain expert answers by hand (✍). |
| Reuse survey | SKOS (codelists), DCTERMS, DCAT, PROV-O, W3C WGS84, GeoSPARQL, VS term status; the publisher's codelist IRIs, the Czech government vocabulary and EU NUTS linked with `skos:exactMatch` / `closeMatch` |
| Skeleton + definitions | [`ontology/kriminalita.ttl`](ontology/kriminalita.ttl): 9 classes, 15 own properties (2 deprecated), en/cs labels, genus–differentia definitions, scope notes, sources |
| Reference data | [`ontology/reference/`](ontology/reference/): SKOS schemes generated from the publisher's JSON-LD codelists and ČSÚ's territorial codelists, plus hand-kept English labels |
| Closed-world rules | [`ontology/shapes.ttl`](ontology/shapes.ttl): SHACL, every rule also stated as a plain sentence |
| Validation loop | [`scripts/validate.py`](scripts/validate.py): parse, HermiT, concept statements vs shapes, lint, SHACL (+ negative tests), artifact drift, CQ tests, loader tests |
| Test suite | [`ontology/tests/`](ontology/tests/): 13 sample records in 16 anonymisation areas, 11 invalid individuals, 29 CQs in SQL, 27 of them also in SPARQL (SPARQL has no weekday function or calendar) |
| Data model | [`db/schema.sql`](db/schema.sql), **generated** from the shapes |
| Data dictionary | **generated** from ontology + shapes: `meta_column` table, [`db/data-dictionary.csv`](db/data-dictionary.csv), [`db/data-dictionary.xlsx`](db/data-dictionary.xlsx) (for review), [`docs/data-dictionary.pdf`](docs/data-dictionary.pdf) |
| Business glossary (Czech) | **generated** from Czech annotations on the ontology: [`docs/glossary.pdf`](docs/glossary.pdf) ("Slovník pojmů"; English internals, Czech business translations) |

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
(default 7). `--offline` uses the cache only. The publisher's list of
anonymisation areas (`voronoi.geojson.zip`, a fixed file from 2022) is downloaded
once into `build/cache/`; the ČSÚ codelists (43, 65, 101, 100) and their
relations are cached there by `build_reference.py` and refreshed after 30 days.

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

Iteration 3 (ORP areas, okresy and kraje, from ČSÚ codelists 65, 101, 100):

15. **A chain that is not a chain.** Municipality → ORP area → okres → kraj
    looked like a nesting; ČSÚ's own relations show ORP Turnov spans three
    okresy. The model has two branches that meet at the kraj, a hard rule that
    both give the same kraj, and a soft rule (a warning that fires for Turnov).
16. **Codebook facts versus design decisions.** Expected answers taken from the
    authoritative codebook may be pre-filled; how the codebook is applied
    (which units are listed, what is excluded) is a design decision and gets a
    hand answer. Pre-filling those hid the question of empty units, which the
    expert then settled as one rule: every territorial unit in scope gets a
    number, tested without thousands of zero rows (`rows: N; others: 0`).
17. **Three names that fit, three definitions that do not.** In the government
    vocabulary *kraj* also names the 1960 regions, the only *okres* term comes
    from a repealed act, and *ORP* strictly is the town, not its area.
18. **A rule that was right but slow.** Two SPARQL rules, checked once per focus
    node, added 90 seconds to every SHACL run; a SPARQL target that finds the
    suspects in one query brought it back to 6.
19. **The expert's slips, and the validator's.** Names written instead of codes,
    and rates rounded to two places where three are compared; the first exposed a
    validator hint that pointed the wrong way, now fixed.

## Layout

See [`CLAUDE.md`](CLAUDE.md) for conventions, namespaces and what is generated vs.
hand-edited.

## Data source and licence

Police of the Czech Republic, *Mapa kriminality*, https://kriminalita.policie.gov.cz
(open data; cite the source when redistributing). Locations are anonymised to
Voronoi-polygon centres by the publisher.
