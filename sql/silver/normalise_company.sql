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
    "Comp_CompanyId"                                         AS comp_companyid,
    staging.fn_clean_utf8("Comp_Name")                       AS comp_name,
    "Comp_WebSite"                                           AS comp_website,
    "Comp_Territory"                                         AS comp_territory,
    "Comp_Sector"                                            AS comp_sector,
    "Comp_Revenue"                                           AS comp_revenue,
    "Comp_Employees"                                         AS comp_employees,
    "Comp_CreatedDate"                                       AS comp_createddate,
    "Comp_UpdatedDate"                                       AS comp_updateddate,
    "Comp_Source"                                            AS comp_source,
    "Comp_CurrencyId"                                        AS comp_currencyid,

    -- Enum mappings via UDFs
    staging.fn_map_company_status("Comp_Status")             AS icalps_companystatus,
    staging.fn_map_company_type("Comp_Type")                 AS icalps_companytype,
    staging.fn_map_language_iso("Comp_Language")             AS icalps_language,

    -- Address
    "Address_Street1"                                        AS icalps_street_address,
    LEFT(
        CONCAT_WS(', ',
            NULLIF("Address_Street1", ''),
            NULLIF("Address_Street2", ''),
            NULLIF("Address_City", ''),
            NULLIF("Address_PostCode", ''),
            NULLIF("Address_Country", '')
        ), 500
    )                                                        AS icalps_full_address,
    "Address_City"                                           AS address_city,
    "Address_State"                                          AS address_state,
    "Address_PostCode"                                       AS address_postcode,
    "Address_Country"                                        AS icalps_country_raw,
    staging.fn_map_country_iso("Address_Country")            AS icalps_country,

    -- Contact info
    "Company_Email"                                          AS icalps_company_email,
    staging.fn_normalize_phone_e164("Company_Phone", 'FR')   AS icalps_companyphone,
    staging.fn_validate_linkedin_url("LinkedIn_URL")         AS icalps_linkedin_url,

    -- Owner (resolved in a separate owner resolution step)
    "Owner_Email"                                            AS icalps_ownerid_raw,
    "Owner_FirstName"                                        AS owner_firstname,
    "Owner_LastName"                                         AS owner_lastname,

    -- Load-status watermark — carried through unchanged
    _load_status,
    _first_seen_at,
    _last_modified_at

FROM staging.stg_company
WHERE "Comp_CompanyId" IS NOT NULL;
