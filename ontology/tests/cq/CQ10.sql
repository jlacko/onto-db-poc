SELECT COUNT(*) AS records, SUM(municipal_police) AS municipal, 1.0 * SUM(municipal_police) / COUNT(*) AS share
FROM offence_record;
