SELECT m.code AS municipality
FROM municipality m
JOIN orp_area p ON p.code = m.orp_area_code
JOIN okres o ON o.code = m.okres_code
WHERE p.kraj_code <> o.kraj_code;
