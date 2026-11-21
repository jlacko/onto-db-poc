-- Guaranteed by the primary key; kept as a test so the guarantee is visible.
SELECT id AS record, COUNT(*) AS occurrences FROM offence_record GROUP BY id HAVING COUNT(*) > 1;
