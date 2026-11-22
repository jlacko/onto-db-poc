-- substr, not strftime: strftime would convert the +01:00 timestamp to UTC.
SELECT CAST(substr(r.report_datetime, 12, 2) AS INTEGER) AS hour, COUNT(*) AS records
FROM offence_record r JOIN offence_record_type rt ON rt.offence_record_id = r.id
WHERE rt.offence_type_code = 19
GROUP BY hour;
