-- Rendered SQL association bridge
-- Communication type: Notes
-- Association target: company
-- Run ID: 20260327_120000
-- Invariant: shared StackSync instance, fixed association_type_id, unique_id prefix 'icalps_', two-pass resolution, NOT EXISTS idempotency guard.

INSERT INTO hubspot.associations_notes_company (
    association_type_id,
    company_id,
    notes_id
)
-- Pass A: StackSync UUID join
SELECT DISTINCT
    190,
    target.id,
    comm.id
FROM hubspot.notes AS comm
INNER JOIN staging.fct_communication_notes AS fct
    ON comm.unique_id = 'icalps_' || fct.icalps_communication_id::text
INNER JOIN hubspot.companies AS target
    ON fct.associated_company_id::text = target.stacksync_record_id_9vpp8v::text
WHERE comm.unique_id LIKE 'icalps_%'
  AND fct.associated_company_id IS NOT NULL
  AND NOT EXISTS (
      SELECT 1
      FROM hubspot.associations_notes_company AS assoc
      WHERE assoc.notes_id = comm.id
        AND assoc.company_id = target.id
        AND assoc.association_type_id = 190
  )

UNION

-- Pass B: legacy ID fallback
SELECT DISTINCT
    190,
    target.id,
    comm.id
FROM hubspot.notes AS comm
INNER JOIN staging.fct_communication_notes AS fct
    ON comm.unique_id = 'icalps_' || fct.icalps_communication_id::text
INNER JOIN hubspot.companies AS target
    ON fct.legacy_company_id::text = target.icalps_company_id::text
WHERE comm.unique_id LIKE 'icalps_%'
  AND fct.associated_company_id IS NULL
  AND fct.legacy_company_id IS NOT NULL
  AND NOT EXISTS (
      SELECT 1
      FROM hubspot.associations_notes_company AS assoc
      WHERE assoc.notes_id = comm.id
        AND assoc.company_id = target.id
        AND assoc.association_type_id = 190
  );
