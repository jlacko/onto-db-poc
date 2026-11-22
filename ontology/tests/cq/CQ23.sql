SELECT r.id AS record
FROM offence_record r LEFT JOIN anonymisation_area a ON a.id = r.area_id
WHERE a.id IS NULL;
