-- Rendered SQL association bridge
-- Communication type: Notes
-- Association target: deal
-- Run ID: 20260327_120000
-- Invariant: shared StackSync instance, fixed association_type_id, unique_id prefix 'icalps_', two-pass resolution, NOT EXISTS idempotency guard.

INSERT INTO hubspot.associations_notes_deal (
    association_type_id,
    deal_id,
    notes_id
)
-- Pass A: StackSync UUID join
SELECT DISTINCT
    214,
    target.id,
    comm.id
FROM hubspot.notes AS comm
INNER JOIN staging.fct_communication_notes AS fct
    ON comm.unique_id = 'icalps_' || fct.icalps_communication_id::text
INNER JOIN hubspot.deals AS target
    ON fct.associated_deal_id::text = target.stacksync_record_id::text
WHERE comm.unique_id LIKE 'icalps_%'
  AND fct.associated_deal_id IS NOT NULL
  AND NOT EXISTS (
      SELECT 1
      FROM hubspot.associations_notes_deal AS assoc
      WHERE assoc.notes_id = comm.id
        AND assoc.deal_id = target.id
        AND assoc.association_type_id = 214
  )

UNION

-- Pass B: legacy ID fallback
SELECT DISTINCT
    214,
    target.id,
    comm.id
FROM hubspot.notes AS comm
INNER JOIN staging.fct_communication_notes AS fct
    ON comm.unique_id = 'icalps_' || fct.icalps_communication_id::text
INNER JOIN hubspot.deals AS target
    ON fct.legacy_deal_id::text = target.icalps_deal_id::text
WHERE comm.unique_id LIKE 'icalps_%'
  AND fct.associated_deal_id IS NULL
  AND fct.legacy_deal_id IS NOT NULL
  AND NOT EXISTS (
      SELECT 1
      FROM hubspot.associations_notes_deal AS assoc
      WHERE assoc.notes_id = comm.id
        AND assoc.deal_id = target.id
        AND assoc.association_type_id = 214
  );
