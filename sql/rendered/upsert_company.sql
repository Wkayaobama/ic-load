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
    stg.icalps_company_id::text,
    stg.name,
    stg.icalps_comp_website,
    stg.city,
    stg.icalps_address_country,
    stg.icalps_company_state,
    stg.icalps_address_postcode,
    stg.icalps_industry_drill_down,
    stg.icalps_companyphone,
    stg.icalps_companytype,
    stg.icalps_industry_drill_down
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
