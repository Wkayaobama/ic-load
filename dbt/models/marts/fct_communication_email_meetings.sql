-- Email and Meeting communications — cleaned pre-upsert mart
-- Source: staging.stg_communication (Bronze, 29,150 rows)
--
-- Pathway: StackSync-native
--   FK resolution via JOIN hubspot.contacts / hubspot.companies (icalps_*_id keys)
--   stacksync_record_id columns exposed for association bridge
--
-- Cleaning pipeline (mirrors Power Query StripHtml + NormalizeText):
--   1. Block HTML tags (br/p/div/li/tr/td) replaced with spaces
--   2. All remaining <...> tags stripped via regexp
--   3. HTML entities decoded (&nbsp; &amp; &quot; &#39; &#10; &#13; char(160))
--   4. Whitespace collapsed + trimmed
--
-- Dedup: DISTINCT ON (norm_subject, legacy_contact_id) — one row per thread per contact
-- Mass outreach filter: subjects appearing > 5 times across all contacts → excluded
-- Excluded subjects: "armed approved design partner", "semicon europa"

{{ config(materialized='table', schema='staging') }}

with base as (

    select
        "Comm_CommunicationId"                              as icalps_communication_id,
        "Comm_Action"                                       as comm_action,
        "Comm_Subject"                                      as comm_subject_raw,
        "Comm_Note"                                         as activity_body_raw,
        "Comm_Email"                                        as comm_email,
        coalesce(
            try_strptime(nullif("Comm_DateTime", ''),           '%Y-%m-%d %H:%M:%S'),
            try_strptime(nullif("Comm_DateTime", ''),           '%d/%m/%Y %H:%M:%S'),
            try_strptime(nullif("Comm_DateTime", ''),           '%d/%m/%Y'),
            try_strptime(nullif("Comm_DateTime", ''),           '%Y-%m-%d')
        )                                                   as activity_datetime,
        coalesce(
            try_strptime(nullif("Comm_OriginalDateTime", ''),   '%Y-%m-%d %H:%M:%S'),
            try_strptime(nullif("Comm_OriginalDateTime", ''),   '%d/%m/%Y %H:%M:%S'),
            try_strptime(nullif("Comm_OriginalDateTime", ''),   '%d/%m/%Y'),
            try_strptime(nullif("Comm_OriginalDateTime", ''),   '%Y-%m-%d')
        )                                                   as original_datetime,
        coalesce(
            try_strptime(nullif("Comm_OriginalToDateTime", ''), '%Y-%m-%d %H:%M:%S'),
            try_strptime(nullif("Comm_OriginalToDateTime", ''), '%d/%m/%Y %H:%M:%S'),
            try_strptime(nullif("Comm_OriginalToDateTime", ''), '%d/%m/%Y'),
            try_strptime(nullif("Comm_OriginalToDateTime", ''), '%Y-%m-%d')
        )                                                   as original_to_datetime,
        cast("Person_Id"  as bigint)                         as legacy_contact_id,
        "Person_FirstName"                                  as person_firstname,
        "Person_LastName"                                   as person_lastname,
        "Person_EmailAddress"                               as person_email_address,
        cast("Company_Id" as bigint)                        as legacy_company_id,
        "Company_Name"                                      as company_name,
        cast(nullif("Comm_OpportunityId", '') as bigint)    as legacy_deal_id,
        cast(nullif("Comm_CaseId", '')        as bigint)    as legacy_case_id

    from "pg_hubspot"."staging"."stg_communication"

    where "Comm_Action" in ('Meeting', 'EmailOut', 'EmailIn')
      and "Person_Id" is not null
      and "Person_Id" != ''

),

html_cleaned as (

    -- Mirrors Power Query StripHtml(NormalizeText(...))
    -- Step 1: block-level HTML tags → space
    -- Step 2: strip all remaining <...> tags
    -- Step 3: decode HTML entities + control chars
    -- Step 4: collapse whitespace

    select
        * exclude (activity_body_raw),

        trim(
            regexp_replace(
                -- Step 4: collapse runs of whitespace
                replace( replace( replace( replace( replace(
                replace( replace( replace( replace( replace(
                -- Step 3: HTML entities + non-breaking space (char 160)
                    regexp_replace(
                        -- Step 2: strip remaining tags
                        regexp_replace(
                            -- Step 1: block tags → space
                            regexp_replace(
                                regexp_replace(activity_body_raw,
                                    '<br\s*/?>', ' ', 'gi'),
                                '</(p|div|li|tr|td)>', ' ', 'gi'),
                            '<[^>]+>', '', 'g'),
                        -- entity decodes via regexp for numeric ones
                        '&#(10|13|160|9);', ' ', 'g'),
                    -- literal entity decodes
                    '&nbsp;',  ' '),   '&amp;',  '&'),
                    '&quot;',  '"'),   '&apos;', chr(39)),
                    '&#39;',   chr(39)),
                    chr(160),  ' '),   chr(9),   ' '),
                    chr(13),   ' '),   chr(10),  ' '),
                    chr(0),    ''),
                '\s+', ' ', 'g')
        ) as activity_body

    from base

),

normalised as (

    select
        *,
        trim(
            regexp_replace(
                lower(trim(coalesce(comm_subject_raw, ''))),
                '^((re|fw|fwd|tr|ref|réf|rép|rep)(\s*:\s*))+',
                '', 'gi'
            )
        ) as norm_subject

    from html_cleaned

),

-- ── Mass-outreach filter ──────────────────────────────────────────────────────
-- Subjects appearing > 5 times across all contacts = broadcast campaign.
-- Excluded entirely (not just deduped).
subject_freq as (
    select norm_subject, count(*) as subject_count
    from normalised
    group by norm_subject
),

filtered as (

    select n.*
    from normalised n
    join subject_freq sf on n.norm_subject = sf.norm_subject

    where sf.subject_count <= 5
      -- Explicitly excluded subjects (mass outreach / trade show campaigns)
      and n.norm_subject not ilike '%armed approved design partner%'
      and n.norm_subject not ilike '%semicon europa%'

),

-- ── Thread dedup ─────────────────────────────────────────────────────────────
-- One row per (contact, normalised subject) — earliest CommunicationId wins.
deduped as (

    select distinct on (norm_subject, legacy_contact_id)
        *
    from filtered
    order by norm_subject, legacy_contact_id, icalps_communication_id asc

),

-- ── StackSync FK resolution ───────────────────────────────────────────────────
-- Join hubspot.contacts + hubspot.companies via icalps_*_id keys.
-- Exposes stacksync_record_id columns needed by the association bridge.
with_hubspot_fks as (

    select
        d.*,
        hsc.id                          as hubspot_contact_id,
        hsc.stacksync_record_id_nd85zc  as hubspot_contact_record_id,
        hscomp.id                       as hubspot_company_id,
        hscomp.stacksync_record_id_9vpp8v as hubspot_company_record_id

    from deduped d
    left join "pg_hubspot"."hubspot"."contacts" hsc
        on d.legacy_contact_id = cast(hsc.icalps_contact_id as bigint)
    left join "pg_hubspot"."hubspot"."companies" hscomp
        on d.legacy_company_id = cast(hscomp.icalps_company_id as bigint)

)

select
    icalps_communication_id,
    comm_action,
    comm_subject_raw,
    norm_subject,
    activity_body,                  -- HTML-stripped, entity-decoded
    comm_email,
    activity_datetime,
    original_datetime,
    original_to_datetime,
    -- Contact
    legacy_contact_id,
    person_firstname,
    person_lastname,
    person_email_address,
    hubspot_contact_id,
    hubspot_contact_record_id,      -- for StackSync association bridge
    -- Company
    legacy_company_id,
    company_name,
    hubspot_company_id,
    hubspot_company_record_id,      -- for StackSync association bridge
    -- Deal / Case passthrough
    legacy_deal_id,
    legacy_case_id,
    current_timestamp               as dbt_loaded_at

from with_hubspot_fks
