SELECT o.kraj_code AS kraj,
       COUNT(r.id) AS records,
       SUM(r.clearance_state_code = 1) AS cleared,
       1.0 * SUM(r.clearance_state_code = 1) / COUNT(r.id) AS rate
FROM offence_record r
JOIN anonymisation_area a ON a.id = r.area_id
JOIN municipality m ON m.code = a.municipality_code
JOIN okres o ON o.code = m.okres_code
WHERE r.clearance_state_code NOT IN (3, 4)
GROUP BY o.kraj_code;
