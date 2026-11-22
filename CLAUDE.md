# CLAUDE.md — onto-db-poc

Proof of concept of the ontology-first approach described in
`llm-readable-ontologies.pdf`. **Primary aim: validate the LLM ontology method**
(concepts and how they relate → competency questions → reuse → Turtle skeleton →
definitions → mechanical validation loop → CQ tests). The first step is our
addition; the PDF was an inspiration, not a template. The SQLite database built from Police CR crime data
is the secondary objective: it is the test that the ontology can drive a real
data model.

Python only (the R implementation in `~/Documents/mapa-kriminality` is a reference
for the API, not a template). Use the venv: `.venv/bin/python`.

## Layout

| Path | What | Edited by |
|------|------|-----------|
| `ontology/concepts.md` | How the key concepts relate: a few sentences in domain language (relationships only, both ends), the expert's verdict, the shape that enforces each. Change it first when structure changes. | hand |
| `ontology/competency-questions.md` | The spec. Change it first. The index at the top is generated (`scripts/cq_index.py`). | hand |
| `ontology/kriminalita.ttl` | Core OWL module: classes, properties, definitions | hand |
| `ontology/shapes.ttl` | SHACL shapes = closed-world data rules; drive the DDL | hand |
| `ontology/reference/codelist-texts.csv` | English labels and definitions, Czech business definitions for codelist items | hand |
| `ontology/reference/*.ttl` | SKOS concept schemes built from the publisher's codelists | **generated** (`scripts/build_reference.py`) |
| `ontology/tests/` | Sample individuals, invalid data, CQ tests (SPARQL + SQL) | hand |
| `db/schema.sql` | SQLite DDL incl. `meta_column` data dictionary | **generated** (`scripts/generate_ddl.py`) |
| `db/data-dictionary.{csv,xlsx}`, `docs/data-dictionary.{qmd,pdf}` | Data dictionary exports | **generated** (`scripts/generate_dictionary.py --pdf`) |
| `docs/glossary.qmd`, `docs/img/concepts.{dot,pdf}`, `docs/glossary.pdf` | Czech business glossary | **generated** (`scripts/generate_glossary.py --pdf`) |
| `docs/action-plan.qmd`, `docs/lessons-learned.qmd`, `docs/guide.qmd` | Write-ups, and the standalone guide to the method (render with `quarto render`) | hand |
| `build/` | Database, caches (git-ignored) | generated |

Never hand-edit generated files; change the source and regenerate.

## Namespaces

- `krim:` `https://example.org/kriminalita/ontology#`: classes and properties
  (placeholder base; replace before any publication, then never change).
- `krimc:` `https://example.org/kriminalita/code/`: codelist concepts,
  `krimc:type/8`, `krimc:state/2`, `krimc:relevance/4`.
- `kdb:` `https://example.org/kriminalita/db#`: database-mapping hints used in
  the shapes only.
- Reused: SKOS, DCTERMS, DCAT, PROV-O, WGS84 (`geo:`), VS (term status).

## Naming and definition style

- Classes UpperCamelCase, properties lowerCamelCase, readable English local names.
- Every class and property has `rdfs:label` in `@en` and `@cs`, a
  `skos:definition@en` in genus–differentia form ("An offence record is an
  information record that …"), and a `vs:term_status` (`draft` / `stable`).
  Add `skos:example` and `skos:scopeNote` (what it does not cover) where useful.
- Every SHACL property shape has `sh:description@en`: the rule as one plain
  sentence ("Every offence record has exactly one clearance state.").
- Every property shape that becomes a column has `sh:name` in `@en` and `@cs`
  (the data-element name). If its path is a reused generic property
  (`dcterms:identifier`, `skos:notation`, ...), it also needs a local
  `skos:definition@en` on the shape. validate.py enforces both.
- **English internals, Czech business translations.** Every class and datatype
  property also has `krim:businessDefinition@cs` (plain Czech, a second
  definition for business readers, not a translation of the formal one),
  `skos:example@cs` and `skos:scopeNote@cs` ("nezaměňovat s"); every record rule
  has `sh:description@cs`. Use the publisher's Czech terms where they exist
  (e.g. *třída*, not *typ*). The Czech text is reviewed by a native speaker.
- Codelist items are `skos:Concept`s typed with their krim class, with
  `skos:notation` (the publisher's code), `skos:prefLabel@cs`, `@en`, and
  `skos:exactMatch` to the publisher's IRI.

## Modelling rules

- Keep OWL lean. **No `rdfs:domain` / `rdfs:range`.** Expected subject and value
  types are SHACL constraints, not OWL inferences.
- Reference data (codelists) are SKOS concept schemes; operational data (offence
  records) live only in the database and in small test samples.
- Deprecate, never delete: `owl:deprecated true` + `dcterms:isReplacedBy`.
  Deprecated terms leave the Czech business glossary (current terms only); the
  data dictionary lists them in an appendix with their replacements.
- Bump `owl:versionInfo` / `owl:versionIRI` in `kriminalita.ttl` for every
  release (semver: major = shape tightened or meaning changed; minor = new term;
  patch = label or definition fix).

## Validation loop (run after every change)

```bash
.venv/bin/python scripts/validate.py
```

It runs: parsing, HermiT consistency, the concept statements against the shapes,
a lint report (labels, definitions,
duplicates, undeclared terms), SHACL on valid and invalid samples, the
competency-question SPARQL tests, and SPARQL/SQL parity on the sample data.
