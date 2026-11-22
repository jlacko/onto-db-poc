SELECT a.municipality_code AS municipality, COUNT(*) AS records
FROM offence_record r JOIN anonymisation_area a ON a.id = r.area_id
GROUP BY a.municipality_code;
