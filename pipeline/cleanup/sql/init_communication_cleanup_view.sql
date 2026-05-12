-- Communication selection view (Phase B input -- selection only).
--
-- IMPORTANT: this view is selection-only. The cleanup runner does NOT
-- currently support archiving engagements -- selection.SUPPORTED_OBJECTS =
-- ('companies', 'contacts', 'deals'). The view exists so operators can
-- snapshot communications into a manifest for review before the engagement-
-- archive path is implemented.
--
-- HubSpot engagement tables do not carry an icalps_communication_id column.
-- The IC'ALPS legacy key is embedded in each engagement's unique_id property
-- with an 'icalps_' prefix (pattern documented in context/config.py:441).
-- This view filters to that namespace and strips the prefix to expose the
-- legacy id.
--
-- Pattern variants discovered in prod (2026-05-12 schema discovery):
--   hubspot.calls.unique_id     : 'icalps_<numeric>'     (5959 rows)
--   hubspot.notes.unique_id     : 'icalps_<numeric>'     (13916 rows; ~half empty bodies)
--   hubspot.tasks.unique_id     : 'icalps_co_<numeric>'  (7852 rows; 'co_' is a sub-type discriminator from migration)
--   hubspot.meetings.unique_id  : Outlook GUIDs only     (0 rows with icalps_ prefix)
--
-- Meetings are intentionally OMITTED from the UNION -- not migrated from
-- IC'ALPS. If meetings get migrated in the future, add a fourth branch here.
--
-- Tasks preserve the 'co_' discriminator in legacy_id (we strip only
-- '^icalps_', not 'co_'). Operators who need the underlying Comm_CommunicationId
-- numeric can strip 'co_' themselves.
--
-- Empty-note filter: the notes branch drops rows whose body strips to empty
-- after HTML tag removal. This is the cohort flagged as 'CRM-polluting'.
--
-- gdpr_deleted filter: already-deleted engagements are excluded so they don't
-- pollute the manifest with no-op archive attempts.

CREATE OR REPLACE VIEW {schema}.fct_cleanup_communication AS
SELECT * FROM (
    -- calls
    SELECT id::text AS hubspot_id,
           REGEXP_REPLACE(unique_id, '^icalps_', '') AS legacy_id,
           COALESCE(NULLIF(TRIM(call_title), ''), '(untitled call)') AS label
    FROM hubspot.calls
    WHERE unique_id LIKE 'icalps_%'
      AND gdpr_deleted IS NOT TRUE

    UNION ALL

    -- notes (with empty-body filter)
    SELECT id::text,
           REGEXP_REPLACE(unique_id, '^icalps_', ''),
           LEFT(REGEXP_REPLACE(note_body, '<[^>]+>', '', 'g'), 80)
    FROM hubspot.notes
    WHERE unique_id LIKE 'icalps_%'
      AND gdpr_deleted IS NOT TRUE
      AND COALESCE(TRIM(REGEXP_REPLACE(note_body, '<[^>]+>', '', 'g')), '') <> ''

    UNION ALL

    -- tasks (preserves 'co_' substring in legacy_id)
    SELECT id::text,
           REGEXP_REPLACE(unique_id, '^icalps_', ''),
           COALESCE(NULLIF(TRIM(task_title), ''), '(untitled task)')
    FROM hubspot.tasks
    WHERE unique_id LIKE 'icalps_%'
      AND gdpr_deleted IS NOT TRUE
) engagements;
