SELECT m.code AS municipality, COUNT(r.id) AS records
FROM municipality m
LEFT JOIN anonymisation_area a ON a.municipality_code = m.code
LEFT JOIN offence_record r ON r.area_id = a.id
GROUP BY m.code;
