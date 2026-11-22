SELECT o.code AS okres, COUNT(r.id) AS records
FROM okres o
LEFT JOIN municipality m ON m.okres_code = o.code
LEFT JOIN anonymisation_area a ON a.municipality_code = m.code
LEFT JOIN offence_record r ON r.area_id = a.id
WHERE o.kraj_code = 3140
GROUP BY o.code;
