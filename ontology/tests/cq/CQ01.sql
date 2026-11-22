SELECT substr(report_datetime, 1, 7) AS month, COUNT(*) AS records
FROM offence_record GROUP BY month;
