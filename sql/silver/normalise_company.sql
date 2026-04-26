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
    "Comp_CompanyId"                                         AS icalps_company_id,
    staging.fn_clean_utf8("Comp_Name")                       AS name,
    "Comp_WebSite"                                           AS icalps_comp_website,
    "Comp_Sector"                                            AS icalps_industry_drill_down,
    "Comp_Employees"                                         AS icalps_comp_numemployees,
    "Comp_CreatedDate"                                       AS createdate,
    "Comp_UpdatedDate"                                       AS lastmodifieddate,
    "Comp_Source"                                            AS icalps_compsource,


    -- Enum mappings via UDFs
    staging.fn_map_company_status("Comp_Status")             AS icalps_companystatus,
    staging.fn_map_company_type("Comp_Type")                 AS icalps_companytype,
    CASE "Comp_Language"::text
        WHEN '0' THEN 'FR'
        WHEN '1' THEN 'INTER'
        ELSE NULL
    END                                                      AS icalps_comp_language,

    -- Address
    "Address_Street1"                                        AS icalps_companyaddress,
    LEFT(
        CONCAT_WS(', ',
            NULLIF("Address_Street1", ''),
            NULLIF("Address_Street2", ''),
            NULLIF("Address_City", ''),
            NULLIF("Address_PostCode", ''),
            NULLIF("Address_Country", '')
        ), 500
    )                                                        AS icalps_street_address,
    "Address_City"                                           AS city,
    "Address_State"                                          AS icalps_company_state,
    "Address_PostCode"                                       AS icalps_address_postcode,
    "Address_Country"                                        AS icalps_country_raw,
    staging.fn_map_country_iso("Address_Country")            AS icalps_address_country,

    -- Contact info
    "Company_Email"                                          AS icalps_companyemail,
    staging.fn_normalize_phone_e164("Company_Phone", 'FR')   AS icalps_companyphone,
    staging.fn_validate_linkedin_url(
        CASE WHEN "LinkedIn_URL" ~ '^company/'
             THEN 'https://www.linkedin.com/' || "LinkedIn_URL"
             ELSE "LinkedIn_URL"
        END
    )                                                        AS linkedin_company_page,

    -- Owner (resolved in a separate owner resolution step)
    COALESCE("Owner_Email", 'thierry.villard@icalps.com')    AS icalps_ownerid_raw,
    COALESCE("Owner_FirstName", 'Thierry')                   AS owner_firstname,
    COALESCE("Owner_LastName", 'VILLARD')                    AS owner_lastname,

    -- Load-status watermark — carried through unchanged
    _load_status,
    _first_seen_at,
    _last_modified_at

FROM staging.stg_company
WHERE "Comp_CompanyId" IS NOT NULL;
