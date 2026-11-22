SELECT m.code AS municipality, m.orp_area_code AS orp, m.okres_code AS okres, o.kraj_code AS kraj
FROM municipality m JOIN okres o ON o.code = m.okres_code
WHERE m.code = 545422;
