-- SQL only: a calendar of the days in the range, minus the days with reports.
WITH RECURSIVE day(d) AS (
  SELECT '2025-01-01'
  UNION ALL SELECT date(d, '+1 day') FROM day WHERE d < '2025-01-07'
)
SELECT d AS day FROM day
WHERE d NOT IN (SELECT substr(report_datetime, 1, 10) FROM offence_record);
