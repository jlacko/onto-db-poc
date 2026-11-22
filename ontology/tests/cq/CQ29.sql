SELECT orp_area_code AS orp, COUNT(DISTINCT okres_code) AS okresy
FROM municipality
GROUP BY orp_area_code HAVING COUNT(DISTINCT okres_code) > 1;
