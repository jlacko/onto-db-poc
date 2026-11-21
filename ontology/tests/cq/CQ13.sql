WITH rc AS (
  SELECT DISTINCT rt.offence_record_id AS record, a.ancestor_code AS category
  FROM offence_record_type rt
  JOIN offence_type_ancestor a ON a.code = rt.offence_type_code
  JOIN offence_type c ON c.code = a.ancestor_code AND c.broader_code IS NULL
)
SELECT record, category FROM rc
WHERE record IN (SELECT record FROM rc GROUP BY record HAVING COUNT(*) > 1);
