# Concepts and cardinality: the first check

This file is Step 1 of the method, before the competency questions. It states
the key concepts and how they relate, **one plain sentence per statement**, and
records the domain expert's verdict on each. The competency questions then test
meaning (do the answers come out right); this file tests structure (what exists,
and how many of each).

Every statement is a sentence a domain expert can judge in seconds:
*"Every offence record has exactly one clearance state."* True or false?

## How to work with this file

1. Read each statement. For those marked **✍ your verdict**, replace `TODO` in
   its `verdict:` line with `true`, `false` or `depends`. Pre-filled verdicts
   come from the reviewed model of release 0.1.0; change any you disagree with.
2. Ask two questions of each statement, and write the answer in its text when
   they differ:
   - **In the domain:** is it true of the world?
   - **In the source:** is it what the publisher chose to keep?
   Example: an offence can involve several places (reported, consequence,
   committed), but the publisher keeps one place per record and says which
   kind it is.
3. Run `.venv/bin/python scripts/validate.py`. Section 3 (*Concepts and
   cardinality*) checks that every statement marked `true` is enforced by the
   SHACL shape it names, with the same cardinality, and that no shape enforces
   a statement marked `false`.

Format of a `statement` block:

| Key | Meaning |
|---|---|
| `subject` | the class the sentence is about (`krim:` name) |
| `path` | the property, `^property` for the inverse direction, or `—` for a sentence about the domain that no property expresses |
| `object` | the class or datatype of the values |
| `count` | `min..max`, with `*` for no upper bound (`1..1` = exactly one, `0..1` = at most one, `1..*` = at least one, `0..*` = any number) |
| `verdict` | `true`, `false`, `depends`, or `TODO` (pending) |
| `shape` | the SHACL node shape that enforces it, or `none` |
| `reason` | required when `shape: none` or `verdict: depends`: why nothing enforces it, or what it depends on |
| `evidence` | optional: how the statement was checked against the source data |

What is not stated is not checked: a cardinality the validator can compare
(`sh:minCount`/`sh:maxCount` on a property shape) is compared; a rule expressed
in SPARQL (uniqueness) is checked for existence only.

---

## Concepts

| Concept | Kind | Status |
|---|---|---|
| Offence record | operational data, one per occurrence | in the model (`krim:OffenceRecord`) |
| Offence type | codelist, a hierarchy | in the model (`krim:OffenceType`) |
| Clearance state | codelist | in the model (`krim:ClearanceState`) |
| Location relevance | codelist | in the model (`krim:LocationRelevance`) |
| Monthly extract | **not a concept**: the publisher's pagination | removed before release 0.1.0 (S14) |
| Anonymisation area | reference data, about 40,000 Voronoi polygons | proposed for iteration 2 (S16–S21) |
| Municipality | reference data (RÚIAN) | proposed for iteration 2 (S18, S19) |

---

## A. The offence record

### S01: Every offence record has exactly one identifier.

The publisher's integer id, stable across download files and refreshes.

```statement
subject: krim:OffenceRecord
path:    dcterms:identifier
object:  xsd:integer
count:   1..1
verdict: true
shape:   krim:OffenceRecordShape
```

### S02: Every offence record has exactly one report date and time.

In the domain, an offence also has a time it was committed; the source
publishes only the time of report.

```statement
subject: krim:OffenceRecord
path:    krim:reportDateTime
object:  xsd:dateTime
count:   1..1
verdict: true
shape:   krim:OffenceRecordShape
```

### S03: Every offence record has exactly one anonymised latitude.

Iteration 2 questions this: the point belongs to an anonymisation area, not to
the record (see S16).

```statement
subject: krim:OffenceRecord
path:    krim:anonymisedLatitude
object:  xsd:decimal
count:   1..1
verdict: true
shape:   krim:OffenceRecordShape
```

### S04: Every offence record has exactly one anonymised longitude.

```statement
subject: krim:OffenceRecord
path:    krim:anonymisedLongitude
object:  xsd:decimal
count:   1..1
verdict: true
shape:   krim:OffenceRecordShape
```

### S05: Every offence record states whether the municipal police recorded it.

```statement
subject: krim:OffenceRecord
path:    krim:recordedByMunicipalPolice
object:  xsd:boolean
count:   1..1
verdict: true
shape:   krim:OffenceRecordShape
```

### S06: Every offence record has exactly one clearance state.

In the domain, the state changes over time; the record keeps only the latest
observed state (S08).

```statement
subject: krim:OffenceRecord
path:    krim:hasClearanceState
object:  krim:ClearanceState
count:   1..1
verdict: true
shape:   krim:OffenceRecordShape
```

### S07: Every offence record has exactly one location relevance.

The kind of place the published location is: of report, of consequence, of
commission.

```statement
subject: krim:OffenceRecord
path:    krim:hasLocationRelevance
object:  krim:LocationRelevance
count:   1..1
verdict: true
shape:   krim:OffenceRecordShape
```

### S08: Every offence record states exactly one moment as of which its state holds.

```statement
subject: krim:OffenceRecord
path:    krim:stateAsOf
object:  xsd:dateTime
count:   1..1
verdict: true
shape:   krim:OffenceRecordShape
```

### S09: Every offence record has one or more offence types.

A record is tagged with a type and all its broader types, so it typically
carries several.

```statement
subject:  krim:OffenceRecord
path:     krim:hasOffenceType
object:   krim:OffenceType
count:    1..*
verdict:  true
shape:    krim:OffenceRecordShape
evidence: 2025 load: 1,377,905 records, 4,007,126 type links, none without a type.
```

### S10: One occurrence is exactly one record, however many downloads it appears in.

An occurrence published as open in one file and as cleared in another is one
record in its latest state.

```statement
subject: krim:OffenceRecord
path:    ^dcterms:identifier
object:  krim:OffenceRecord
count:   1..1
verdict: true
shape:   krim:OffenceRecordIdentityShape
reason:  uniqueness across records is a SPARQL constraint (and the primary key in SQL)
```

## B. The codelists

### S11: An offence type has at most one broader offence type.

The hierarchy is a tree of up to three levels; a type without a broader type is
a category.

```statement
subject: krim:OffenceType
path:    skos:broader
object:  krim:OffenceType
count:   0..1
verdict: true
shape:   krim:OffenceTypeShape
```

### S12: A clearance state applies to any number of records.

```statement
subject: krim:ClearanceState
path:    ^krim:hasClearanceState
object:  krim:OffenceRecord
count:   0..*
verdict: true
shape:   none
reason:  an open inverse cardinality needs no rule; SHACL constrains the record side (S06)
```

### S13: An offence type is shared by any number of records.

```statement
subject: krim:OffenceType
path:    ^krim:hasOffenceType
object:  krim:OffenceRecord
count:   0..*
verdict: true
shape:   none
reason:  an open inverse cardinality needs no rule; SHACL constrains the record side (S09)
```

## C. Rejected statements

Kept on purpose: a rejected statement records a mistake the model must not
make again. The validator fails if a shape enforces one.

### S14: Every offence record belongs to exactly one monthly extract.

False in the domain: the monthly files are the publisher's pagination. The
statement was in the first draft and was removed before release 0.1.0.

```statement
subject: krim:OffenceRecord
path:    krim:publishedIn
object:  krim:MonthlyExtract
count:   1..1
verdict: false
shape:   none
reason:  pagination is not a domain concept
```

### S15: An offence happens at exactly one place.

False in the domain: an offence can be reported in one place and committed, or
have consequences, in another. The source keeps one place per record and labels
its kind (S07), which is a choice of the publisher, not a fact of the domain.

```statement
subject: krim:OffenceRecord
path:    —
object:  —
count:   1..1
verdict: false
shape:   none
reason:  no property expresses it; S07 records what the source kept instead
```

## D. Anonymisation areas (proposed for iteration 2)

The publisher anonymises every location by moving it to the centre of a
predefined Voronoi polygon (`data-raw/readme.txt`; polygon list
`voronoi.geojson.zip`, dated 2022). These statements are the proposal; nothing
in the model enforces them yet.

### S16: Every offence record is anonymised to exactly one area. ✍ your verdict

If true, the record's location is a reference to an area, and S03/S04 move from
the record to the area.

```statement
subject:  krim:OffenceRecord
path:     krim:inAnonymisationArea
object:   krim:AnonymisationArea
count:    1..1
verdict:  TODO
shape:    none
reason:   not modelled yet (iteration 2)
evidence: 2025 load: every record's point equals one area's defining point (99.98 % exactly at 6 decimals, the rest within 1e-6).
```

### S17: An anonymisation area is shared by any number of records. ✍ your verdict

```statement
subject:  krim:AnonymisationArea
path:     ^krim:inAnonymisationArea
object:   krim:OffenceRecord
count:    0..*
verdict:  TODO
shape:    none
reason:   not modelled yet (iteration 2)
evidence: 2025: 34,770 of 39,927 areas have at least one record; 5,157 have none.
```

### S18: Every anonymisation area lies in exactly one municipality. ✍ your verdict

Which level counts as the municipality is open: obec (`kod_obec`), basic
territorial unit (`kod_zuj`) or city district (`kod_momc`, only in statutory
cities).

```statement
subject:  krim:AnonymisationArea
path:     krim:inMunicipality
object:   krim:Municipality
count:    1..1
verdict:  TODO
shape:    none
reason:   not modelled yet (iteration 2)
evidence: polygon list: every area has kod_obec (6,258 distinct) and kod_zuj (6,392); kod_momc on 3,897 areas only.
```

### S19: A municipality contains one or more anonymisation areas. ✍ your verdict

Municipalities with fewer than 25 offences in 2018 were not split (2,682 of
them): they are a single area.

```statement
subject: krim:Municipality
path:    ^krim:inMunicipality
object:  krim:AnonymisationArea
count:   1..*
verdict: TODO
shape:   none
reason:  not modelled yet (iteration 2)
```

### S20: Every anonymisation area has exactly one centre, and no two areas share it. ✍ your verdict

The centre is the published (anonymised) point of every record in the area.

```statement
subject:  krim:AnonymisationArea
path:     krim:centre
object:   geo:Point
count:    1..1
verdict:  TODO
shape:    none
reason:   not modelled yet (iteration 2)
evidence: polygon list: 39,927 areas, 39,927 distinct defining points.
```

### S21: Every anonymisation area has exactly one polygon geometry. ✍ your verdict

True in the source. Whether the model needs it is another matter: no question
so far uses the shape of an area, only its centre and municipality.

```statement
subject:  krim:AnonymisationArea
path:     krim:hasGeometry
object:   geo:Geometry
count:    1..1
verdict:  TODO
shape:    none
reason:   not modelled yet (iteration 2)
evidence: polygon list: 39,924 polygons and 3 multipolygons.
```
