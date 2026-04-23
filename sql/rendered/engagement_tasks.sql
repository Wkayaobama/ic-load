-- Rendered SQL engagement upsert
-- Communication type: Tasks
-- Run ID: 20260327_120000
-- Invariant: deterministic unique_id and NOT EXISTS idempotency guard.

INSERT INTO hubspot.tasks (
            task_title, task_notes, due_date, task_status, priority, task_type, unique_id, source
        )
        SELECT
    hs_task_subject,
    hs_task_body,
    hs_timestamp,
    hs_task_status,
    'MEDIUM',
    hs_task_type,
    'icalps_' || icalps_communication_id::text,
    'IC_ALPS_MIGRATION'
FROM staging.fct_communication_tasks
WHERE icalps_communication_id IS NOT NULL
  AND NOT EXISTS (
      SELECT 1 FROM hubspot.tasks existing
      WHERE existing.unique_id = 'icalps_' || icalps_communication_id::text
  );
