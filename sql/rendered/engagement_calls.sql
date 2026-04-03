        -- Rendered SQL engagement upsert
        -- Communication type: Calls
        -- Run ID: 20260327_120000
        -- Invariant: deterministic unique_id and NOT EXISTS idempotency guard.

        INSERT INTO hubspot.calls (
    call_title, call_notes, activity_date, call_direction, call_status,
    call_duration, unique_id, engagement_source
)
SELECT
    hs_call_title,
    hs_call_body,
    hs_timestamp,
    hs_call_direction,
    hs_call_status,
    hs_call_duration,
    'icalps_' || icalps_communication_id::text,
    'IC_ALPS_MIGRATION'
FROM staging.fct_communication_calls
WHERE icalps_communication_id IS NOT NULL
  AND NOT EXISTS (
      SELECT 1 FROM hubspot.calls existing
      WHERE existing.unique_id = 'icalps_' || icalps_communication_id::text
  );
