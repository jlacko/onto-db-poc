SELECT r.state_as_of AS record_as_of, (SELECT MAX(state_as_of) FROM offence_record) AS dataset_as_of
FROM offence_record r WHERE r.id = 1003;
