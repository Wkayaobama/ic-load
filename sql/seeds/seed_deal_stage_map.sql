-- seed_deal_stage_map — IC'ALPS pipeline/stage/outcome → HubSpot pipeline + stage IDs.
--
-- Source of truth: deal_stage_mapper.py (context/algorithms/deal_stage_mapper.py).
-- This table is DERIVED from the Python dict — it is not authoritative.
-- If the Python mapper is updated, re-export this table.
--
-- Usage by StackSync workflows:
--   The opportunity_intake_workflow.yaml JOINs this table to resolve the
--   HubSpot pipeline_id + dealstage_id from the form-submitted pipeline/stage/outcome.
--   NULL result on unmapped combination = row excluded from the UPDATE.
--
-- Usage by batch pipeline:
--   The batch pipeline does NOT read this table — it calls deal_stage_mapper.py
--   directly (which raises ValueError on unmapped, not NULL).
--
-- Re-generation:
--   python -c "
--     from context.algorithms.deal_stage_mapper import list_all_mappings
--     import json
--     print(json.dumps(list_all_mappings(), indent=2))
--   "
--   Then convert to INSERT statements below.
--
-- Idempotent: TRUNCATE + INSERT. Safe to re-run.
-- Deploy to: StackSync managed Postgres (staging schema).

CREATE TABLE IF NOT EXISTS staging.seed_deal_stage_map (
    icalps_pipeline         TEXT NOT NULL,
    icalps_stage            TEXT NOT NULL,
    icalps_outcome          TEXT NOT NULL,
    hubspot_pipeline_id     TEXT NOT NULL,
    hubspot_stage_id        TEXT NOT NULL,
    hubspot_stage_name      TEXT NOT NULL,
    PRIMARY KEY (icalps_pipeline, icalps_stage, icalps_outcome)
);

TRUNCATE staging.seed_deal_stage_map;

INSERT INTO staging.seed_deal_stage_map
    (icalps_pipeline, icalps_stage, icalps_outcome, hubspot_pipeline_id, hubspot_stage_id, hubspot_stage_name)
VALUES
    -- 01 - Identification
    ('Hardware', '01 - Identification', 'No-go',       '766126206', '85103758', 'Closed Lost'),
    ('Hardware', '01 - Identification', 'Abandonnée',  '766126206', '85103758', 'Closed Lost'),
    ('Hardware', '01 - Identification', 'En cours',    '766126206', '85103752', 'Identified'),
    ('Hardware', '01 - Identification', 'Perdue',      '766126206', '85103758', 'Closed Lost'),
    ('Hardware', '01 - Identification', 'Gagnée',      '766126206', '85103757', 'Closed Won'),

    -- 02 - Qualifiée
    ('Hardware', '02 - Qualifiée', 'No-go',       '766126206', '85103758', 'Closed Lost'),
    ('Hardware', '02 - Qualifiée', 'Abandonnée',  '766126206', '85103758', 'Closed Lost'),
    ('Hardware', '02 - Qualifiée', 'En cours',    '766126206', '85103753', 'Qualified'),
    ('Hardware', '02 - Qualifiée', 'Perdue',      '766126206', '85103758', 'Closed Lost'),
    ('Hardware', '02 - Qualifiée', 'Gagnée',      '766126206', '85103757', 'Closed Won'),

    -- 03 - Evaluation technique
    ('Hardware', '03 - Evaluation technique', 'No-go',       '766126206', '85103758', 'Closed Lost'),
    ('Hardware', '03 - Evaluation technique', 'Abandonnée',  '766126206', '85103758', 'Closed Lost'),
    ('Hardware', '03 - Evaluation technique', 'En cours',    '766126206', '85103754', 'Design In'),
    ('Hardware', '03 - Evaluation technique', 'Perdue',      '766126206', '85103758', 'Closed Lost'),
    ('Hardware', '03 - Evaluation technique', 'Gagnée',      '766126206', '85103757', 'Closed Won'),

    -- 04 - Construction propositions
    ('Hardware', '04 - Construction propositions', 'No-go',       '766126206', '85103758', 'Closed Lost'),
    ('Hardware', '04 - Construction propositions', 'Abandonnée',  '766126206', '85103758', 'Closed Lost'),
    ('Hardware', '04 - Construction propositions', 'En cours',    '766126206', '85103754', 'Design In'),
    ('Hardware', '04 - Construction propositions', 'Perdue',      '766126206', '85103758', 'Closed Lost'),
    ('Hardware', '04 - Construction propositions', 'Gagnée',      '766126206', '85103757', 'Closed Won'),

    -- 05 - Négociations
    ('Hardware', '05 - Négociations', 'No-go',       '766126206', '85103758', 'Closed Lost'),
    ('Hardware', '05 - Négociations', 'Abandonnée',  '766126206', '85103758', 'Closed Lost'),
    ('Hardware', '05 - Négociations', 'En cours',    '766126206', '85103756', 'Design Win'),
    ('Hardware', '05 - Négociations', 'Perdue',      '766126206', '85103758', 'Closed Lost'),
    ('Hardware', '05 - Négociations', 'Gagnée',      '766126206', '85103757', 'Closed Won');
