SELECT r.id AS record, m.code AS municipality, m.name_cs AS name
FROM offence_record r JOIN anonymisation_area a ON a.id = r.area_id JOIN municipality m ON m.code = a.municipality_code
WHERE r.id = 1001;
