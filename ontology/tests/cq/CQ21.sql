SELECT municipality_code AS municipality, COUNT(*) AS areas
FROM anonymisation_area WHERE municipality_code IN (509736, 545422)
GROUP BY municipality_code;
