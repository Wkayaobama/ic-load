-- normalise_contact.sql
-- Replaces silver_normalise.py::SilverNormaliser.normalise_contact()
--
-- Reads:  staging.stg_contact  (written by BRONZE_EXPORT)
-- Writes: staging.stg_contact_normalised
--
-- All transformation logic delegated to staging.fn_* UDFs installed by
-- PG_FUNCTIONS_INSTALL. Run order: PG_FUNCTIONS_INSTALL → BRONZE_EXPORT → this script.

DROP TABLE IF EXISTS staging.stg_contact_normalised CASCADE;

CREATE TABLE staging.stg_contact_normalised AS
SELECT
    pers_personid,
    pers_companyid,
    staging.fn_clean_utf8(pers_firstname)                       AS pers_firstname,
    staging.fn_clean_utf8(pers_lastname)                        AS pers_lastname,
    pers_middlename,
    pers_salutation,
    pers_gender,
    pers_suffix,

    -- Title: strip HTML, truncate 150 chars
    LEFT(staging.fn_clean_html(pers_title), 150)                AS icalps_title,

    pers_department,
    staging.fn_map_contact_status(pers_status)                  AS icalps_pers_status,
    pers_source,
    pers_territory,
    pers_website,
    pers_createddate,
    pers_updateddate,
    pers_createdby,

    -- Company (denormalised)
    company_name,
    company_website,
    company_type,

    -- Email: validate format
    CASE
        WHEN person_email LIKE '%@%' THEN person_email
        ELSE NULL
    END                                                         AS icalps_email,

    -- Phone
    staging.fn_normalize_phone_e164(person_phone_business, 'FR') AS icalps_businessphone,
    staging.fn_normalize_phone_e164(person_phone_mobile, 'FR')   AS icalps_mobilephone,

    -- Address
    address_street1                                             AS icalps_street_address,
    LEFT(
        CONCAT_WS(', ',
            NULLIF(address_street1, ''),
            NULLIF(address_city, ''),
            NULLIF(address_postcode, ''),
            NULLIF(address_country, '')
        ), 500
    )                                                           AS icalps_full_address,
    address_city,
    address_state,
    address_postcode,
    staging.fn_map_country_iso(address_country)                 AS icalps_country,

    -- LinkedIn
    staging.fn_validate_linkedin_url(linkedin_url)              AS icalps_linkedin_url,

    -- Load-status watermark — carried through unchanged
    _load_status,
    _first_seen_at,
    _last_modified_at

FROM staging.stg_contact
WHERE pers_personid IS NOT NULL;
