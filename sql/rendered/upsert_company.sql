        -- Rendered SQL upsert pattern
        -- Entity: Company
        -- Run ID: 20260327_120000
        -- Boundary: SQL upserts only. Validation and dbt stay outside this template.
        -- bronze_file=bronze_layer/Bronze_Company_20260327_120000.csv
        -- previous_bronze_file=bronze_layer/Bronze_Company_20260325_120000.csv

        INSERT INTO hubspot.companies (
    icalps_company_id, name, icalps_comp_website, city, country, state,
    zip, industry, phone, comp_type, comp_sector
)
SELECT
    stg.comp_companyid::text,
    stg.comp_name,
    stg.comp_website,
    stg.address_city,
    stg.icalps_country,
    stg.address_state,
    stg.address_postcode,
    stg.comp_sector,
    stg.icalps_companyphone,
    stg.icalps_companytype,
    stg.comp_sector
FROM staging.stg_company_normalised AS stg
WHERE stg._load_status IN ('NEW', 'MODIFIED')
ON CONFLICT (icalps_company_id) DO UPDATE
SET
    name = EXCLUDED.name,
    icalps_comp_website = EXCLUDED.icalps_comp_website,
    city = EXCLUDED.city,
    country = EXCLUDED.country,
    state = EXCLUDED.state,
    zip = EXCLUDED.zip,
    industry = EXCLUDED.industry,
    phone = EXCLUDED.phone,
    comp_type = EXCLUDED.comp_type,
    comp_sector = EXCLUDED.comp_sector;
