# Concepts and how they relate

Step 1 of the method, before the competency questions. Twelve sentences in
domain language, one per relationship between two concepts, each with both
ends: *how many of B for one A, and how many of A for one B*. Each takes
seconds to judge; no technical knowledge is needed.

Only relationships between concepts belong here. Attributes (identifier, dates,
flags, an area's centre) are stated as plain-language rules on the SHACL shapes
and reviewed there; data-quality findings go to the quality report, open domain
questions to section F of the competency questions. The file shows the current
model only, plus sentences awaiting a verdict; git keeps the history.

## How to work with this file

1. Read each sentence. Where it says **Verdict: TODO**, replace `TODO` with
   `true`, `false` or `depends` (for `depends`, add a line saying on what).
2. Ask of each sentence: is it true **in the world**, or only **in the source**
   (what the publisher chose to keep)? Where the two differ, the note says so.
3. Skip the `validator` blocks: they tell `scripts/validate.py` which rule in
   `ontology/shapes.ttl` enforces the sentence, and it checks that the rule
   says the same.

---

### S1: An offence record has one or more offence types; an offence type covers any number of records.

Verdict: true

A record carries its type together with all the broader types, so it usually
has several.

```validator
subject: krim:OffenceRecord
path:    krim:hasOffenceType
object:  krim:OffenceType
count:   1..*
inverse: 0..*
shape:   krim:OffenceRecordShape
```

### S2: An offence type falls under at most one broader type; a type can have several narrower ones.

Verdict: true

The types form a tree of up to three levels. A type with no broader type is a
category.

```validator
subject: krim:OffenceType
path:    skos:broader
object:  krim:OffenceType
count:   0..1
inverse: 0..*
shape:   krim:OffenceTypeShape
```

### S3: An offence record has exactly one clearance state at a time; a clearance state applies to any number of records.

Verdict: true

In the world the state develops; the database keeps the latest one published.

```validator
subject: krim:OffenceRecord
path:    krim:hasClearanceState
object:  krim:ClearanceState
count:   1..1
inverse: 0..*
shape:   krim:OffenceRecordShape
```

### S4: An offence record has exactly one published place, with one kind of place (reported, consequence, committed).

Verdict: true

In the world an offence can involve several places; the source keeps one per
record and says which kind it is. Checked on all 2025 files: no record has
more than one place.

```validator
subject: krim:OffenceRecord
path:    krim:hasLocationRelevance
object:  krim:LocationRelevance
count:   1..1
inverse: 0..*
shape:   krim:OffenceRecordShape
```

### S5: One occurrence is one record, however many downloads it appears in.

Verdict: true

An occurrence published as unsolved in one download and as cleared in a later
one is a single record, in its latest state.

```validator
subject: krim:OffenceRecord
path:    ^dcterms:identifier
object:  krim:OffenceRecord
count:   1..1
shape:   krim:OffenceRecordIdentityShape
reason:  uniqueness is a SPARQL rule (and the primary key in the database)
```

### S6: An offence record is placed in exactly one anonymisation area; an area holds any number of records.

Verdict: true

The publisher moves every place to the centre of a predefined area (a Voronoi
polygon; `data-raw/readme.txt`). Checked on 2025: every record's point is the
centre of exactly one of the 39,927 areas; 5,157 areas hold no record.

```validator
subject: krim:OffenceRecord
path:    krim:inAnonymisationArea
object:  krim:AnonymisationArea
count:   1..1
inverse: 0..*
shape:   krim:OffenceRecordShape
```

### S7: An anonymisation area lies in exactly one municipality; a municipality has one or more areas.

Verdict: true

Municipality means *obec*, as in the Czech Statistical Office's codelist of
municipalities (ČSÚ codelist 43, <https://apl2.czso.cz/iSMS/cisdet.jsp?kodcis=43>);
every area's municipality must exist in that codelist. Municipalities with few
offences were not split and are a single area. The four military training
areas in the codelist (Boletice, Březina, Hradiště, Libavá) count as
municipalities here, although they are not municipalities in law. Checked: the polygon list's
6,258 municipality codes match codelist 43 one to one (6,258 items, valid on
22 Nov 2026), so every municipality has at least one area.

```validator
subject: krim:AnonymisationArea
path:    krim:inMunicipality
object:  krim:Municipality
count:   1..1
inverse: 1..*
shape:   krim:AnonymisationAreaShape
```

### S8: A municipality lies in exactly one ORP; an ORP has one or more municipalities.

Verdict: true

ORP is the administrative district of a municipality with extended powers
(*správní obvod obce s rozšířenou působností*, ČSÚ codelist 65). Checked: every
one of the 6,258 municipalities is in exactly one of the 206 ORPs.

```validator
subject: krim:Municipality
path:    krim:inOrp
object:  krim:Orp
count:   1..1
inverse: 1..*
shape:   none
reason:  not modelled yet (iteration 3); names are provisional
```

### S9: A municipality lies in exactly one district; a district has one or more municipalities.

Verdict: true

District means *okres* (LAU 1, ČSÚ codelist 101). Checked: every municipality
is in exactly one of the 77 districts. ČSÚ maintains this link by hand; the
links to ORP and region are derived from it.

```validator
subject: krim:Municipality
path:    krim:inDistrict
object:  krim:District
count:   1..1
inverse: 1..*
shape:   none
reason:  not modelled yet (iteration 3); names are provisional
```

### S10: An ORP lies in exactly one region; a region has one or more ORPs.

Verdict: true

Region means *kraj* (NUTS 3, ČSÚ codelist 100). Checked: all 206 ORPs nest in
one of the 14 regions.

```validator
subject: krim:Orp
path:    krim:inRegion
object:  krim:Region
count:   1..1
inverse: 1..*
shape:   none
reason:  not modelled yet (iteration 3); names are provisional
```

### S11: A district lies in exactly one region; a region has one or more districts.

Verdict: true

Checked: all 77 districts nest in one region. ORP and district are two branches
that meet at the region: a municipality's region is the same whichever branch
is followed. Prague is one item in each codelist (ORP, district and region).

```validator
subject: krim:District
path:    krim:inRegion
object:  krim:Region
count:   1..1
inverse: 1..*
shape:   none
reason:  not modelled yet (iteration 3); names are provisional
```

### S12: An ORP lies within one district; a district has one or more ORPs.

Verdict: depends

True for 205 of the 206 ORPs. ORP Turnov (5109) is split across three districts
(Semily, Liberec, Jablonec nad Nisou). A soft rule: a warning that names Turnov
as the known exception, not a constraint.

```validator
subject: krim:Orp
path:    krim:inDistrict
object:  krim:District
count:   0..1
inverse: 1..*
shape:   none
reason:  holds except for ORP Turnov, split across three districts; a warning, not a constraint
```
