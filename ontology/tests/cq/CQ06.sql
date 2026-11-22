-- Per calendar month of report: misdemeanour only / other only / both (not exclusive).
WITH flags AS (
  SELECT r.id, substr(r.report_datetime, 1, 7) AS month,
         EXISTS (SELECT 1 FROM offence_record_type rt
                 JOIN offence_type_ancestor a ON a.code = rt.offence_type_code
                 WHERE rt.offence_record_id = r.id AND a.ancestor_code = 97) AS mis,
         EXISTS (SELECT 1 FROM offence_record_type rt
                 JOIN offence_type_ancestor a ON a.code = rt.offence_type_code
                 JOIN offence_type c ON c.code = a.ancestor_code AND c.broader_code IS NULL
                 WHERE rt.offence_record_id = r.id AND a.ancestor_code <> 97) AS oth
  FROM offence_record r
)
SELECT month,
       SUM(mis AND NOT oth) AS misdemeanours,
       SUM(oth AND NOT mis) AS other,
       SUM(mis AND oth) AS both
FROM flags GROUP BY month;
