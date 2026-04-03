        -- Rendered SQL engagement upsert
        -- Communication type: Notes
        -- Run ID: 20260327_120000
        -- Invariant: deterministic unique_id and NOT EXISTS idempotency guard.

        INSERT INTO hubspot.notes (
    note_body, activity_date, unique_id, engagement_source
)
SELECT
    COALESCE(hs_note_body, hs_note_subject, 'Note from IC''ALPS'),
    hs_timestamp,
    'icalps_' || icalps_communication_id::text,
    'IC_ALPS_MIGRATION'
FROM staging.fct_communication_notes
WHERE icalps_communication_id IS NOT NULL
  AND NOT EXISTS (
      SELECT 1 FROM hubspot.notes existing
      WHERE existing.unique_id = 'icalps_' || icalps_communication_id::text
  );
