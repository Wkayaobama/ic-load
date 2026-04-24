        -- Rendered SQL upsert pattern
        -- Entity: Opportunity
        -- Run ID: 20260327_120000
        -- Boundary: SQL upserts only. Validation and dbt stay outside this template.
        -- bronze_file=bronze_layer/Bronze_Opportunity_20260327_120000.csv
        -- previous_bronze_file=bronze_layer/Bronze_Opportunity_20260325_120000.csv

        INSERT INTO hubspot.deals (
    icalps_deal_id, dealname, pipeline, dealstage, amount,
    icalps_oppocertainty, icalps_dealtype, icalps_dealnotes, icalps_closedate
)
SELECT
    stg.icalps_deal_id::text,
    stg.dealname,
    stg.pipeline,
    stg.dealstage,
    stg.amount::numeric,
    stg.icalps_oppocertainty::numeric,
    stg.icalps_dealtype,
    stg.icalps_dealnotes,
    stg.icalps_closedate
FROM staging.stg_opportunity_normalised AS stg
WHERE stg._load_status IN ('NEW', 'MODIFIED')
ON CONFLICT (icalps_deal_id) DO UPDATE
SET
    dealname = EXCLUDED.dealname,
    pipeline = EXCLUDED.pipeline,
    dealstage = EXCLUDED.dealstage,
    amount = EXCLUDED.amount,
    icalps_oppocertainty = EXCLUDED.icalps_oppocertainty,
    icalps_dealtype = EXCLUDED.icalps_dealtype,
    icalps_dealnotes = EXCLUDED.icalps_dealnotes,
    icalps_closedate = EXCLUDED.icalps_closedate;
