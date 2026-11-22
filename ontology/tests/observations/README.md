# Observation fixtures (loader test)

Two downloads of the same month, in the publisher's CSV format, observed at
different times. They test the "one occurrence = one record, latest state wins"
rule (CQ18) through the real loader functions (`scripts/load.py: parse, merge`).

| file | observed (state as of) | content |
|---|---|---|
| `observation-1.csv` | 2026-01-10T00:00:00 | 5001 burglary of a flat, **unsolved**; 5002 bicycle theft, cleared; 6001 reported 2024-12-31 (outside the year, must be ignored); 5004 at a point that is no area's centre (must be skipped and counted) |
| `observation-2.csv` | 2026-06-10T00:00:00 | 5001 again, now **cleared** and reclassified as burglary of a family house; 5003 robbery, new; 5005 fraud at a point one micro-degree from an area's centre (must be matched to that area) |

The test gives the loader four areas whose centres are the points used here
(the real list has 39,927). Expected after loading both, in either order:
records 5001, 5002, 5003, 5005; record 5001 with state 1, types {18, 20}, state
as of 2026-06-10T00:00:00; 5005 in the area next to its point; no 6001, no 5004.
Loading `observation-2.csv` again changes nothing.
