{{
    config(
        materialized='table',
        database='pg_hubspot',
        schema='staging'
    )
}}

/*
Silver Delta Opportunity Model
==============================
Transforms raw delta opportunity records with:
1. Computed columns (Weighted_Forecast, Net_Amount, Net_Weighted_Amount)
2. Deal stage mapping (IC'ALPS outcome → HubSpot dealstage)
3. Data type normalization

Source: staging.stg_delta_opportunity (loaded from bronze_delta_oppo050225.csv)
Output: staging.silver_delta_opportunity
*/

with source as (
    select * from {{ source('staging_delta', 'stg_delta_opportunity') }}
),

cleaned as (
    select
        -- Primary key
        "Oppo_OpportunityId"::integer as opportunity_id,

        -- Foreign keys (already NULL or numeric from PostgreSQL)
        "Oppo_PrimaryCompanyId"::integer as legacy_company_id,
        "Oppo_PrimaryPersonId"::integer as legacy_contact_id,
        "Oppo_AssignedUserId"::integer as assigned_user_id,

        -- Core deal properties
        "Oppo_Description" as deal_name,
        "Oppo_Type" as deal_type,
        "Oppo_Product" as deal_product,
        "Oppo_Source" as deal_source,
        "Oppo_Status" as deal_status,
        "Oppo_Stage" as deal_stage_raw,
        "Oppo_Priority" as deal_priority,
        "Oppo_CustomerRef" as customer_ref,
        "Oppo_Note" as deal_notes,

        -- Financial fields (already numeric from PostgreSQL, coalesce NULLs to 0)
        coalesce("Oppo_Forecast"::numeric, 0) as forecast_amount,
        coalesce("Oppo_Certainty"::numeric, 0) as certainty,
        coalesce("oppo_cout"::numeric, 0) as cost,

        -- Dates (already timestamp or NULL from PostgreSQL)
        -- Note: Delta file has Oppo_Opened/Oppo_Closed, not ActualClose
        "Oppo_TargetClose"::timestamp as target_close_date,
        "Oppo_Opened"::timestamp as opened_date,
        "Oppo_Closed"::timestamp as closed_date,
        "Oppo_CreatedDate"::timestamp as created_date,
        "Oppo_UpdatedDate"::timestamp as updated_date

    from source
    where "Oppo_OpportunityId" is not null
),

with_computed_columns as (
    select
        *,

        -- Computed Column 1: Weighted Forecast = Amount × Certainty
        -- Note: Certainty is stored as 0-100, so divide by 100 for decimal
        (forecast_amount * (certainty / 100.0)) as weighted_forecast,

        -- Computed Column 2: Net Amount = Forecast - Cost
        (forecast_amount - cost) as net_amount,

        -- Computed Column 3: Net Weighted Amount = Net Amount × Certainty
        ((forecast_amount - cost) * (certainty / 100.0)) as net_weighted_amount

    from cleaned
),

with_stage_mapping as (
    select
        *,

        -- Deal Stage Mapping: IC'ALPS outcome → HubSpot dealstage
        -- The Oppo_Stage field contains both stage number and outcome
        -- Outcomes: No-go, Abandonnée, Perdue → Closed Lost
        --           Gagnée → Closed Won
        --           En cours / Open → In Progress
        case
            when deal_stage_raw ilike '%No-go%' then 'Closed Lost'
            when deal_stage_raw ilike '%Abandonnée%' then 'Closed Lost'
            when deal_stage_raw ilike '%Abandonn%' then 'Closed Lost'
            when deal_stage_raw ilike '%Perdue%' then 'Closed Lost'
            when deal_stage_raw ilike '%Gagnée%' then 'Closed Won'
            when deal_stage_raw ilike '%Gagn%' then 'Closed Won'
            when deal_stage_raw ilike '%En cours%' then 'In Progress'
            when deal_status = 'Closed' and deal_stage_raw is not null then 'Closed Lost'
            when deal_status = 'Open' then 'In Progress'
            else 'In Progress'
        end as hubspot_dealstage

    from with_computed_columns
)

select
    -- Keys
    opportunity_id,
    legacy_company_id,
    legacy_contact_id,
    assigned_user_id,

    -- Core properties
    deal_name,
    deal_type,
    deal_product,
    deal_source,
    deal_status,
    deal_stage_raw,
    deal_priority,
    customer_ref,
    deal_notes,

    -- Financial (raw)
    forecast_amount,
    certainty,
    cost,

    -- Computed columns (Silver layer enrichment)
    weighted_forecast,
    net_amount,
    net_weighted_amount,

    -- Mapped stage (Silver layer business rule)
    hubspot_dealstage,

    -- Dates
    target_close_date,
    opened_date,
    closed_date,
    created_date,
    updated_date,

    -- Metadata
    current_timestamp as silver_processed_at,
    'delta_050225' as batch_id

from with_stage_mapping
