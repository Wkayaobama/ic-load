-- Communication bridge: communication count per company
-- Used by create_company_hierarchy.py as a tiebreaker when contact_count = 0
-- across Gold-matched candidates sharing the same domain.
--
-- Simple aggregation over int_communication_reconciled — no new joins needed.
-- A NULL communication_count (company not found in reconciled) is treated as 0
-- by the Python caller and should be flagged as a data quality warning.
{{ config(materialized='table', schema='staging') }}

select
    legacy_company_id,
    count(communication_id)                         as communication_count,
    count(case when has_company_match then 1 end)   as reconciled_count,
    min(activity_datetime)                          as first_communication_at,
    max(activity_datetime)                          as last_communication_at

from {{ ref('int_communication_reconciled') }}
where legacy_company_id is not null

group by legacy_company_id
