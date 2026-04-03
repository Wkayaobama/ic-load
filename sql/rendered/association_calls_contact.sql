-- Rendered SQL association bridge
-- Communication type: Calls
-- Association target: contact
-- Run ID: 20260327_120000
-- Invariant: shared StackSync instance, fixed association_type_id, unique_id prefix 'icalps_', two-pass resolution, NOT EXISTS idempotency guard.

INSERT INTO hubspot.associations_calls_contact (
    association_type_id,
    contact_id,
    calls_id
)
-- Pass A: StackSync UUID join
SELECT DISTINCT
    194,
    target.id,
    comm.id
FROM hubspot.calls AS comm
INNER JOIN staging.fct_communication_calls AS fct
    ON comm.unique_id = 'icalps_' || fct.icalps_communication_id::text
INNER JOIN hubspot.contacts AS target
    ON fct.associated_contact_id::text = target.stacksync_record_id_nd85zc::text
WHERE comm.unique_id LIKE 'icalps_%'
  AND fct.associated_contact_id IS NOT NULL
  AND NOT EXISTS (
      SELECT 1
      FROM hubspot.associations_calls_contact AS assoc
      WHERE assoc.calls_id = comm.id
        AND assoc.contact_id = target.id
        AND assoc.association_type_id = 194
  )

UNION

-- Pass B: legacy ID fallback
SELECT DISTINCT
    194,
    target.id,
    comm.id
FROM hubspot.calls AS comm
INNER JOIN staging.fct_communication_calls AS fct
    ON comm.unique_id = 'icalps_' || fct.icalps_communication_id::text
INNER JOIN hubspot.contacts AS target
    ON fct.legacy_contact_id::text = target.icalps_contact_id::text
WHERE comm.unique_id LIKE 'icalps_%'
  AND fct.associated_contact_id IS NULL
  AND fct.legacy_contact_id IS NOT NULL
  AND NOT EXISTS (
      SELECT 1
      FROM hubspot.associations_calls_contact AS assoc
      WHERE assoc.calls_id = comm.id
        AND assoc.contact_id = target.id
        AND assoc.association_type_id = 194
  );
