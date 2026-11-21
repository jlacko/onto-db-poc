SELECT COUNT(DISTINCT r.id) AS records
FROM offence_record r
JOIN offence_record_type rt ON rt.offence_record_id = r.id
JOIN offence_type_ancestor a ON a.code = rt.offence_type_code
WHERE a.ancestor_code = 18
  AND substr(r.report_datetime, 1, 10) BETWEEN '2025-02-01' AND '2025-02-28';
