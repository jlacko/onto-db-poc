SELECT k.code AS kraj, COUNT(r.id) AS records
FROM kraj k
LEFT JOIN okres o ON o.kraj_code = k.code
LEFT JOIN municipality m ON m.okres_code = o.code
LEFT JOIN anonymisation_area a ON a.municipality_code = m.code
LEFT JOIN offence_record r ON r.area_id = a.id
GROUP BY k.code;
