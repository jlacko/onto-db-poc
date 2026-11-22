SELECT a.ancestor_code AS category,
       COUNT(DISTINCT r.id) AS records,
       COUNT(DISTINCT CASE WHEN r.clearance_state_code = 1 THEN r.id END) AS cleared,
       1.0 * COUNT(DISTINCT CASE WHEN r.clearance_state_code = 1 THEN r.id END) / COUNT(DISTINCT r.id) AS rate
FROM offence_record r
JOIN offence_record_type rt ON rt.offence_record_id = r.id
JOIN offence_type_ancestor a ON a.code = rt.offence_type_code
JOIN offence_type c ON c.code = a.ancestor_code AND c.broader_code IS NULL
WHERE r.clearance_state_code NOT IN (3, 4)
GROUP BY a.ancestor_code;
