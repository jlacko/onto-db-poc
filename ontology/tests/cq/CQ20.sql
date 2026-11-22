SELECT a.id AS area, COUNT(r.id) AS records
FROM anonymisation_area a LEFT JOIN offence_record r ON r.area_id = a.id
WHERE a.municipality_code = 509736
GROUP BY a.id;
