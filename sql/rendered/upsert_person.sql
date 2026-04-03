        -- Rendered SQL upsert pattern
        -- Entity: Person
        -- Run ID: 20260327_120000
        -- Boundary: SQL upserts only. Validation and dbt stay outside this template.
        -- bronze_file=bronze_layer/Bronze_Person_20260327_120000.csv
        -- previous_bronze_file=bronze_layer/Bronze_Person_20260325_120000.csv

        INSERT INTO hubspot.contacts (
    icalps_contact_id, email, firstname, lastname, jobtitle, phone,
    mobilephone, city, state, country, zip, lastmodifieddate
)
SELECT
    stg.pers_personid::text,
    stg.icalps_email,
    stg.pers_firstname,
    stg.pers_lastname,
    stg.icalps_title,
    stg.icalps_businessphone,
    stg.icalps_mobilephone,
    stg.address_city,
    stg.address_state,
    stg.icalps_country,
    stg.address_postcode,
    stg.pers_updateddate::timestamp
FROM staging.stg_contact_normalised AS stg
WHERE stg._load_status IN ('NEW', 'MODIFIED')
ON CONFLICT (icalps_contact_id) DO UPDATE
SET
    email = EXCLUDED.email,
    firstname = EXCLUDED.firstname,
    lastname = EXCLUDED.lastname,
    jobtitle = EXCLUDED.jobtitle,
    phone = EXCLUDED.phone,
    mobilephone = EXCLUDED.mobilephone,
    city = EXCLUDED.city,
    state = EXCLUDED.state,
    country = EXCLUDED.country,
    zip = EXCLUDED.zip,
    lastmodifieddate = EXCLUDED.lastmodifieddate;
