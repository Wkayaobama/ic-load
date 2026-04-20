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
    "Pers_PersonId"                                              AS pers_personid,
    "Pers_CompanyId"                                             AS pers_companyid,
    staging.fn_clean_utf8("Pers_FirstName")                      AS pers_firstname,
    staging.fn_clean_utf8("Pers_LastName")                       AS pers_lastname,
    "Pers_MiddleName"                                            AS pers_middlename,
    "Pers_Salutation"                                            AS pers_salutation,
    "Pers_Gender"                                                AS pers_gender,
    "Pers_Suffix"                                                AS pers_suffix,

    -- Title: strip HTML, truncate 150 chars
    LEFT(staging.fn_clean_html("Pers_Title"), 150)               AS icalps_title,

    "Pers_Department"                                            AS pers_department,
    staging.fn_map_contact_status("Pers_Status")                 AS icalps_pers_status,
    "Pers_Source"                                                AS pers_source,
    "Pers_Territory"                                             AS pers_territory,
    "Pers_WebSite"                                               AS pers_website,
    "Pers_CreatedDate"                                           AS pers_createddate,
    "Pers_UpdatedDate"                                           AS pers_updateddate,
    "Pers_CreatedBy"                                             AS pers_createdby,

    -- Company (denormalised)
    "Company_Name"                                               AS company_name,
    "Company_WebSite"                                            AS company_website,
    "Company_Type"                                               AS company_type,

    -- Email: validate format
    CASE
        WHEN "Person_Email" LIKE '%@%' THEN "Person_Email"
        ELSE NULL
    END                                                          AS icalps_email,

    -- Phone
    staging.fn_normalize_phone_e164("Person_Phone_Business", 'FR') AS icalps_businessphone,
    staging.fn_normalize_phone_e164("Person_Phone_Mobile", 'FR')   AS icalps_mobilephone,

    -- Address
    "Address_Street1"                                            AS icalps_street_address,
    LEFT(
        CONCAT_WS(', ',
            NULLIF("Address_Street1", ''),
            NULLIF("Address_City", ''),
            NULLIF("Address_PostCode", ''),
            NULLIF("Address_Country", '')
        ), 500
    )                                                            AS icalps_full_address,
    "Address_City"                                               AS address_city,
    "Address_State"                                              AS address_state,
    "Address_PostCode"                                           AS address_postcode,
    staging.fn_map_country_iso("Address_Country")                AS icalps_country,

    -- LinkedIn
    staging.fn_validate_linkedin_url("LinkedIn_URL")             AS icalps_linkedin_url,

    -- Load-status watermark — carried through unchanged
    _load_status,
    _first_seen_at,
    _last_modified_at

FROM staging.stg_contact
WHERE "Pers_PersonId" IS NOT NULL;
