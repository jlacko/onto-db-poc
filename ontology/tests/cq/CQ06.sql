SELECT substr(r.report_datetime, 1, 7) AS month,
       SUM(m.is_mis) AS misdemeanours,
       SUM(1 - m.is_mis) AS other
FROM offence_record r
JOIN (SELECT r2.id,
             EXISTS (SELECT 1 FROM offence_record_type rt
                     JOIN offence_type_ancestor a ON a.code = rt.offence_type_code
                     WHERE rt.offence_record_id = r2.id AND a.ancestor_code = 97) AS is_mis
      FROM offence_record r2) m ON m.id = r.id
GROUP BY month;
