-- normalise_company.sql
-- Replaces silver_normalise.py::SilverNormaliser.normalise_company()
--
-- Reads:  staging.stg_company  (written by BRONZE_EXPORT)
-- Writes: staging.stg_company_normalised
--
-- All transformation logic delegated to staging.fn_* UDFs installed by
-- PG_FUNCTIONS_INSTALL. Run order: PG_FUNCTIONS_INSTALL → BRONZE_EXPORT → this script.

DROP TABLE IF EXISTS staging.stg_company_normalised CASCADE;

CREATE TABLE staging.stg_company_normalised AS
SELECT
    comp_companyid,
    staging.fn_clean_utf8(comp_name)                        AS comp_name,
    comp_website,
    comp_territory,
    comp_sector,
    comp_revenue,
    comp_employees,
    comp_createddate,
    comp_updateddate,
    comp_source,
    comp_currencyid,

    -- Enum mappings via UDFs
    staging.fn_map_company_status(comp_status)              AS icalps_companystatus,
    staging.fn_map_company_type(comp_type)                  AS icalps_companytype,
    staging.fn_map_language_iso(comp_language)              AS icalps_language,

    -- Address
    address_street1                                         AS icalps_street_address,
    LEFT(
        CONCAT_WS(', ',
            NULLIF(address_street1, ''),
            NULLIF(address_street2, ''),
            NULLIF(address_city, ''),
            NULLIF(address_postcode, ''),
            NULLIF(address_country, '')
        ), 500
    )                                                       AS icalps_full_address,
    address_city,
    address_state,
    address_postcode,
    address_country                                         AS icalps_country_raw,
    staging.fn_map_country_iso(address_country)             AS icalps_country,

    -- Contact info
    company_email                                           AS icalps_company_email,
    staging.fn_normalize_phone_e164(company_phone, 'FR')    AS icalps_companyphone,
    staging.fn_validate_linkedin_url(linkedin_url)          AS icalps_linkedin_url,

    -- Owner (resolved in a separate owner resolution step)
    owner_email                                             AS icalps_ownerid_raw,
    owner_firstname,
    owner_lastname,

    -- Load-status watermark — carried through unchanged
    _load_status,
    _first_seen_at,
    _last_modified_at

FROM staging.stg_company
WHERE comp_companyid IS NOT NULL;
