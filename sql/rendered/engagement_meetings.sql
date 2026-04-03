        -- Rendered SQL engagement upsert
        -- Communication type: Meetings
        -- Run ID: 20260327_120000
        -- Invariant: deterministic unique_id and NOT EXISTS idempotency guard.

        INSERT INTO hubspot.meetings (
    meeting_title, meeting_body, meeting_start_time, meeting_end_time,
    meeting_outcome, meeting_source, meeting_duration, unique_id, engagement_source
)
SELECT
    hs_meeting_title,
    hs_meeting_body,
    hs_meeting_start_time,
    hs_meeting_end_time,
    hs_meeting_outcome,
    hs_meeting_source,
    hs_meeting_duration_minutes,
    'icalps_' || icalps_communication_id::text,
    'IC_ALPS_MIGRATION'
FROM staging.fct_communication_meetings
WHERE icalps_communication_id IS NOT NULL
  AND NOT EXISTS (
      SELECT 1 FROM hubspot.meetings existing
      WHERE existing.unique_id = 'icalps_' || icalps_communication_id::text
  );
