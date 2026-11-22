-- SQL only: SPARQL 1.1 has no weekday function. Local date, so no strftime on the offset timestamp.
SELECT CAST(strftime('%u', substr(r.report_datetime, 1, 10)) AS INTEGER) AS weekday, COUNT(DISTINCT r.id) AS records
FROM offence_record r
JOIN offence_record_type rt ON rt.offence_record_id = r.id
JOIN offence_type_ancestor a ON a.code = rt.offence_type_code
WHERE a.ancestor_code = 18
GROUP BY weekday;
