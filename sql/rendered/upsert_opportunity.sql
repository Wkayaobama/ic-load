-- Rendered SQL upsert pattern
-- Entity: Opportunity
-- Run ID: 20260327_120000
-- Boundary: SQL upserts only. Validation and dbt stay outside this template.
-- bronze_file=bronze_layer/Bronze_Opportunity_20260327_120000.csv
-- previous_bronze_file=bronze_layer/Bronze_Opportunity_20260325_120000.csv

INSERT INTO hubspot.deals (
            icalps_deal_id, dealname, pipeline, dealstage, amount,
            icalps_dealforecast, icalps_dealcertainty, icalps_dealtype,
            icalps_dealnotes, icalps_netamount_k__, icalps_net_weighted_amount, closedate
        )
        SELECT
    stg.oppo_opportunityid::text,
    stg.oppo_description,
    stg.hubspot_pipeline_id,
    stg.hubspot_dealstage_id,
    stg.icalps_forecast::numeric,
    stg.icalps_forecast::numeric,
    stg.icalps_certainty::numeric,
    stg.oppo_type,
    stg.oppo_notes,
    icalps_forecast::numeric - icalps_icalps_cost::numeric,
    (icalps_forecast::numeric - icalps_icalps_cost::numeric) * (icalps_certainty::numeric / 100.0),
    stg.icalps_closedate::timestamp
FROM staging.stg_opportunity_normalised AS stg
WHERE stg._load_status IN ('NEW', 'MODIFIED')
        ON CONFLICT (icalps_deal_id) DO UPDATE
        SET
            dealname = EXCLUDED.dealname,
            pipeline = EXCLUDED.pipeline,
            dealstage = EXCLUDED.dealstage,
            amount = EXCLUDED.amount,
            icalps_dealforecast = EXCLUDED.icalps_dealforecast,
            icalps_dealcertainty = EXCLUDED.icalps_dealcertainty,
            icalps_dealtype = EXCLUDED.icalps_dealtype,
            icalps_dealnotes = EXCLUDED.icalps_dealnotes,
            icalps_netamount_k__ = EXCLUDED.icalps_netamount_k__,
            icalps_net_weighted_amount = EXCLUDED.icalps_net_weighted_amount,
            closedate = EXCLUDED.closedate;
