SELECT rt.offence_type_code AS type, COUNT(*) AS records
FROM offence_record r
JOIN offence_record_type rt ON rt.offence_record_id = r.id
WHERE substr(r.report_datetime, 1, 7) = '2025-02'
  AND NOT EXISTS (SELECT 1 FROM offence_record_type rt2
                  JOIN offence_type_ancestor a ON a.code = rt2.offence_type_code AND a.depth > 0
                  WHERE rt2.offence_record_id = r.id AND a.ancestor_code = rt.offence_type_code)
GROUP BY rt.offence_type_code;
