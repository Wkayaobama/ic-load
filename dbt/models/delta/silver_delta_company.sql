{{
    config(
        materialized='table',
        database='pg_hubspot',
        schema='staging'
    )
}}

/*
Silver Delta Company Model
==========================
Transforms raw delta company records with:
1. Data type normalization
2. HubSpot-ready property mapping
3. Company type classification

Source: staging.stg_delta_company (loaded from bronze_delta_company050225.csv)
Output: staging.silver_delta_company
*/

with source as (
    select * from {{ source('staging_delta', 'stg_delta_company') }}
),

cleaned as (
    select
        -- Primary key
        "Comp_CompanyId"::integer as company_id,

        -- Foreign keys (already NULL or numeric from PostgreSQL, use :: cast syntax)
        "Comp_PrimaryPersonId"::integer as primary_person_id,
        "Comp_PrimaryAddressId"::integer as primary_address_id,
        "Comp_PrimaryUserId"::integer as primary_user_id,

        -- Core company properties
        trim("Comp_Name") as company_name,
        "Comp_Type" as company_type,
        "Comp_Status" as company_status,
        "Comp_Source" as lead_source,
        "Comp_Territory" as territory,
        "Comp_Sector" as industry_sector,
        "Comp_WebSite" as website,

        -- Size indicators
        "Comp_Revenue" as revenue_range,
        "Comp_Employees" as employee_range,

        -- Classification codes
        "Comp_IndCode" as industry_code,
        "comp_naf" as naf_code,
        "comp_siret" as siret_number,

        -- Dates (already timestamp or NULL from PostgreSQL)
        "Comp_CreatedDate"::timestamp as created_date,
        "Comp_UpdatedDate"::timestamp as updated_date,

        -- Additional properties for HubSpot
        "comp_description" as description,
        "comp_sousactivite" as sub_activity,
        "comp_sousactivite2" as sub_activity_2

    from source
    where "Comp_CompanyId" is not null
),

with_hubspot_mapping as (
    select
        *,

        -- Map company type to HubSpot lifecycle stage
        case
            when company_type = 'Customer' then 'customer'
            when company_type = 'Prospect' then 'lead'
            when company_type = 'Supplier' then 'other'
            else 'lead'
        end as hubspot_lifecyclestage,

        -- Map employee range to HubSpot numberofemployees
        case
            when employee_range = 'Upto20' then '1-20'
            when employee_range = '21-50' then '21-50'
            when employee_range = '51-100' then '51-100'
            when employee_range = '101-200' then '101-200'
            when employee_range = '201-500' then '201-500'
            when employee_range = '501+' then '501-1000'
            else null
        end as hubspot_numberofemployees,

        -- Extract domain from website
        case
            when website is not null and website != ''
            then regexp_replace(
                regexp_replace(website, '^https?://', ''),
                '^www\.', ''
            )
            else null
        end as domain

    from cleaned
)

select
    -- Keys
    company_id,
    primary_person_id,
    primary_address_id,
    primary_user_id,

    -- Core properties (HubSpot-ready)
    company_name as name,
    company_type,
    company_status,
    lead_source,
    territory,
    industry_sector as industry,
    website,
    domain,

    -- Size indicators
    revenue_range,
    employee_range,
    hubspot_numberofemployees,

    -- Classification
    industry_code,
    naf_code,
    siret_number,

    -- HubSpot mapping
    hubspot_lifecyclestage,

    -- Additional
    description,
    sub_activity,
    sub_activity_2,

    -- Dates
    created_date,
    updated_date,

    -- Metadata
    current_timestamp as silver_processed_at,
    'delta_050225' as batch_id

from with_hubspot_mapping
