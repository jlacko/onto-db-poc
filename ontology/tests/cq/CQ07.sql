SELECT r.id AS record FROM offence_record r JOIN anonymisation_area a ON a.id = r.area_id
WHERE a.centre_latitude BETWEEN 50.0 AND 50.2 AND a.centre_longitude BETWEEN 14.2 AND 14.7;
