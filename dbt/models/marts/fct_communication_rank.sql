-- Communication Rank per Company
-- Weighted engagement score used for parent_likelihood computation on COMPANY records.
--
-- SCORING FORMULA (derived from IC'ALPS engagement priority):
--   email              = 3 points  (highest signal: deliberate written communication)
--   communication_obj  = 2 points  (notes/appointments: meaningful touchpoint)
--   task               = 1 point   (todo/followup: lowest signal)
--
--   parent_likelihood_score = (email_count * 3) + (comm_obj_count * 2) + (task_count * 1)
--
-- SOURCES:
--   Standard tasks  : fct_communication_tasks        (Comm_Action=ToDo, ~145 rows)
--   Custom obj tasks: fct_custom_object_tasks         (full export, ~6,654 tasks + notes + appts)
--   Notes/emails    : fct_communication_notes         (EmailOut/EmailIn, ~11,981 rows)
--
-- OUTPUT:
--   One row per legacy_company_id with engagement counts and weighted score.
--   This model is consumed by upsert_engagements.py --rank-only to PATCH
--   hubspot.companies.communication_rank and hubspot.companies.parent_likelihood.
--
-- NOTE: fct_custom_object_tasks must be materialised before this model runs.
{{ config(materialized='table', schema='staging') }}

with standard_tasks as (
    select
        legacy_company_id,
        count(*) as task_count
    from {{ ref('fct_communication_tasks') }}
    where legacy_company_id is not null
    group by 1
),

custom_tasks as (
    -- Tasks from the name_communications custom object export
    select
        legacy_company_id,
        count(*) filter (where engagement_type = 'task')       as custom_task_count,
        count(*) filter (where engagement_type = 'note')       as custom_note_count,
        count(*) filter (where engagement_type = 'appointment') as custom_appt_count
    from {{ ref('fct_custom_object_tasks') }}
    where legacy_company_id is not null
    group by 1
),

all_notes as (
    -- Notes from standard pipeline (EmailOut / EmailIn / PhoneOut classified as NOTE)
    select
        legacy_company_id,
        count(*)                                               as note_count,
        count(*) filter (where source_comm_action in ('EmailOut', 'EmailIn')) as email_count
    from {{ ref('fct_communication_notes') }}
    where legacy_company_id is not null
    group by 1
),

-- Merge all company IDs across sources with FULL OUTER JOIN
merged as (
    select
        coalesce(st.legacy_company_id,
                 ct.legacy_company_id,
                 n.legacy_company_id)                          as legacy_company_id,

        -- Task counts (standard + custom)
        coalesce(st.task_count, 0)                             as standard_task_count,
        coalesce(ct.custom_task_count, 0)                      as custom_task_count,
        coalesce(ct.custom_note_count, 0)                      as custom_note_count,
        coalesce(ct.custom_appt_count, 0)                      as custom_appt_count,

        -- Note/email counts from standard pipeline
        coalesce(n.note_count, 0)                              as standard_note_count,
        coalesce(n.email_count, 0)                             as email_count

    from standard_tasks st
    full outer join custom_tasks ct
        on st.legacy_company_id = ct.legacy_company_id
    full outer join all_notes n
        on coalesce(st.legacy_company_id, ct.legacy_company_id) = n.legacy_company_id
)

select
    legacy_company_id,

    -- Raw engagement counts
    standard_task_count,
    custom_task_count,
    standard_task_count + custom_task_count                    as total_task_count,
    custom_note_count,
    custom_appt_count,
    standard_note_count,
    custom_note_count + standard_note_count                    as total_note_count,
    email_count,

    -- Communication object count (notes + appointments from both sources)
    custom_note_count + custom_appt_count + standard_note_count as communication_object_count,

    -- Weighted parent likelihood score
    -- email(3) + comm_obj(2) + task(1)
    (email_count * 3)
    + ((custom_note_count + custom_appt_count + standard_note_count) * 2)
    + ((standard_task_count + custom_task_count) * 1)          as parent_likelihood_score,

    -- Simplified communication rank (same formula, no email premium)
    (custom_note_count + custom_appt_count + standard_note_count)
    + (standard_task_count + custom_task_count)                as communication_rank,

    current_timestamp                                          as dbt_loaded_at

from merged
where legacy_company_id is not null
order by parent_likelihood_score desc
