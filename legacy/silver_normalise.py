#!/usr/bin/env python3
"""
silver_normalise.py (Standalone ic-load version)
=================================================
DuckDB-based Silver normalisation layer.

Reads raw ``staging.stg_*`` tables from PostgreSQL into DuckDB (in-memory),
applies all data-quality rules from ``validation/icalps_import_flags.md``,
and writes normalised results back to PostgreSQL as ``staging.stg_*_normalised``.

These normalised tables are what dbt and the upsert scripts consume —
never the raw ``stg_*`` tables directly.

Run order (enforced by pipeline.runner):
    bronze_loader  ->  silver_normalise  ->  validate_silver  ->  dbt  ->  upsert

Usage:
    from legacy.silver_normalise import SilverNormaliser
    normaliser = SilverNormaliser()
    normaliser.run_all()

    # Or single entity:
    normaliser.normalise_company()
"""

from __future__ import annotations

import re
from typing import Optional

import duckdb
import pandas as pd

# Use ic-load's context.db for PostgreSQL connection
from context.db import get_connection

# Financial unit conversion — single source of truth for euros -> k€.
from context.algorithms.financial_normalise import to_keuros

# Import sibling algorithms from ic-load's context.algorithms
try:
    from context.algorithms.company_siblings import (
        clean_domain,
        detect_all_sibling_groups,
        assign_sibling_indices,
    )
    _SIBLING_ALGORITHMS_AVAILABLE = True
except ImportError:
    _SIBLING_ALGORITHMS_AVAILABLE = False
    print("[silver_normalise] WARNING: company_siblings module unavailable - sibling index disabled")


# ---------------------------------------------------------------------------
# Reference tables
# ---------------------------------------------------------------------------

COMPANY_STATUS_MAP = {
    "Actif":   "Active",
    "Inactif": "Inactive",
    "Fermé":   "Closed",
    "Ferm\u00e9": "Closed",  # unicode variant
}

COMPANY_TYPE_MAP = {
    "Client":      "Customer",
    "Fournisseur": "Supplier",
    "Partenaire":  "Agent",
}

CONTACT_STATUS_MAP = {
    "Actif":     "Active",
    "Inactif":   "Inactive",
    "Parti":     "Left",
    "Retrait\u00e9": "Retired",
    "Retraité":  "Retired",
}

LANGUAGE_ISO_MAP = {
    "Fran\u00e7ais": "FR",
    "Français": "FR",
    "English":  "EN",
    "Deutsch":  "DE",
    "Espagnol": "ES",
    "Italian":  "IT",
    "Italiano": "IT",
}

ISO_TO_FULL_COUNTRY_MAP = {
    "FR": "France",
    "CH": "Switzerland",
    "DE": "Germany",
    "IT": "Italy",
    "BE": "Belgium",
    "NL": "Netherlands",
    "SE": "Sweden",
    "US": "United States",
    "NO": "Norway",
    "FI": "Finland",
    "AT": "Austria",
    "ES": "Spain",
    "IL": "Israel",
    "UK": "United Kingdom",
    "GB": "United Kingdom",
    "GR": "Greece",
    "DK": "Denmark",
    "IE": "Ireland",
    "IN": "India",
    "PL": "Poland",
    "CA": "Canada",
    "PT": "Portugal",
    "TR": "Turkey",
    "LU": "Luxembourg",
    "CZ": "Czech Republic",
    "CN": "China",
    "SG": "Singapore",
    "KR": "South Korea",
    "AU": "Australia",
    "EG": "Egypt",
    "BR": "Brazil",
    "RU": "Russia",
    "HK": "Hong Kong",
    "TW": "Taiwan",
    "UA": "Ukraine",
    "SA": "Saudi Arabia",
    "TN": "Tunisia",
    "LI": "Liechtenstein",
    "SI": "Slovenia",
    "ZA": "South Africa",
    "AE": "United Arab Emirates",
    "JP": "Japan",
    "VN": "Vietnam",
    "LV": "Latvia",
    "LT": "Lithuania",
    "RO": "Romania",
    "MX": "Mexico",
    "UY": "Uruguay",
}

COUNTRY_ISO_MAP = {
    "France":        "FR",
    "Allemagne":     "DE",
    "Suisse":        "CH",
    "Royaume-Uni":   "GB",
    "\u00c9tats-Unis": "US",
    "États-Unis":    "US",
    "Belgique":      "BE",
    "Italie":        "IT",
    "Espagne":       "ES",
    "Pays-Bas":      "NL",
    "Autriche":      "AT",
    "Danemark":      "DK",
    "Su\u00e8de":    "SE",
    "Suède":         "SE",
    "Finlande":      "FI",
    "Norv\u00e8ge":  "NO",
    "Norvège":       "NO",
    "Luxembourg":    "LU",
    "Portugal":      "PT",
    "Irlande":       "IE",
    "Pologne":       "PL",
    "Canada":        "CA",
    "Japon":         "JP",
    "Chine":         "CN",
    "Israel":        "IL",
    "Singapour":     "SG",
    # Lowercase variants (source data quality)
    "france":        "FR",
    "allemagne":     "DE",
    "suisse":        "CH",
    "royaume-uni":   "GB",
    "belgique":      "BE",
    "italie":        "IT",
    "espagne":       "ES",
    "pays-bas":      "NL",
    "autriche":      "AT",
    "danemark":      "DK",
    "finlande":      "FI",
    "luxembourg":    "LU",
    "portugal":      "PT",
    "irlande":       "IE",
    "pologne":       "PL",
    "canada":        "CA",
    "japon":         "JP",
    "chine":         "CN",
    "israel":        "IL",
    "singapour":     "SG",
    # Non-standard codes
    "UK":            "GB",
}


# ---------------------------------------------------------------------------
# Phone normalisation (E.164 helper — Python-side, applied via pandas)
# ---------------------------------------------------------------------------

def _normalise_phone(raw: Optional[str]) -> Optional[str]:
    """Normalise a French-origin phone number to E.164 (+33XXXXXXXXX)."""
    if not raw or not isinstance(raw, str):
        return None
    # Strip spaces, dots, dashes, parentheses
    digits = re.sub(r"[\s.\-()\/]", "", raw.strip())
    if not digits:
        return None
    # Already E.164
    if digits.startswith("+"):
        return digits if len(digits) >= 8 else None
    # French 0033... prefix
    if digits.startswith("0033"):
        return "+" + digits[2:]
    # French local 0X...
    if digits.startswith("0") and len(digits) == 10:
        return "+33" + digits[1:]
    # Bare 9-digit (dropped leading 0)
    if len(digits) == 9 and digits[0] in "123456789":
        return "+33" + digits
    return digits if len(digits) >= 7 else None


def _fetch_gold_companies() -> pd.DataFrame:
    """Fetch hubspot.companies for sibling parent resolution.

    Returns DataFrame with icalps_company_id, hubspot_id, and contact_count.
    Used by sibling detection to determine canonical parent (highest contact_count).
    """
    with get_connection() as pg_conn:
        try:
            return _pg_query_df(pg_conn, """
                SELECT
                    icalps_company_id::text AS icalps_company_id,
                    id AS hubspot_id,
                    COALESCE(num_associated_contacts, 0) AS contact_count
                FROM hubspot.companies
                WHERE icalps_company_id IS NOT NULL
            """)
        except Exception as e:
            print(f"[silver_normalise] WARNING: could not fetch gold companies — {e}")
            return pd.DataFrame(columns=["icalps_company_id", "hubspot_id", "contact_count"])


# ---------------------------------------------------------------------------
# Core helper: read table from PostgreSQL -> pandas -> DuckDB
# ---------------------------------------------------------------------------

def _pg_query_df(pg_conn, sql: str) -> pd.DataFrame:
    """Execute a query against a psycopg2 connection and return a DataFrame."""
    with pg_conn.cursor() as cur:
        cur.execute(sql)
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
    return pd.DataFrame(rows, columns=cols)


def _pg_to_duckdb(con: duckdb.DuckDBPyConnection, table: str) -> int:
    """
    Load a PostgreSQL staging table into DuckDB in-memory.

    Returns the row count.
    """
    with get_connection() as pg_conn:
        df = _pg_query_df(pg_conn, f'SELECT * FROM {table}')
    table_name = table.replace(".", "_").replace("staging_", "")
    # Convert pandas StringDtype columns to object for DuckDB compatibility
    # pandas 2.x uses StringDtype which DuckDB doesn't recognize
    for col in df.columns:
        if isinstance(df[col].dtype, pd.StringDtype) or df[col].dtype.name in ('str', 'string'):
            df[col] = df[col].astype(object)
    con.register(table_name, df)
    n = len(df)
    print(f"[silver_normalise] loaded {table} -> duckdb '{table_name}' ({n:,} rows)")
    return n


def _duckdb_to_pg(con: duckdb.DuckDBPyConnection, view_name: str, pg_table: str) -> int:
    """Write a DuckDB relation back to PostgreSQL via pandas COPY."""
    df = con.execute(f"SELECT * FROM {view_name}").df()
    # Lowercase all column names so PostgreSQL identifiers are case-insensitive friendly
    df.columns = [c.lower() for c in df.columns]
    cols = list(df.columns)
    with get_connection() as pg_conn:
        cur = pg_conn.cursor()
        # Drop + recreate so schema changes are picked up cleanly
        cur.execute(f"DROP TABLE IF EXISTS {pg_table} CASCADE")
        # Build CREATE from df dtypes
        _create_table_from_df(cur, df, pg_table)
        pg_conn.commit()
        # Bulk COPY via StringIO
        import io
        buf = io.StringIO()
        df.to_csv(buf, index=False, header=False, na_rep="")
        buf.seek(0)
        quoted_cols = [f'"{c}"' for c in cols]
        cur.copy_expert(
            f"COPY {pg_table} ({','.join(quoted_cols)}) FROM STDIN WITH CSV NULL ''",
            buf,
        )
        pg_conn.commit()
        cur.execute(f"SELECT COUNT(*) FROM {pg_table}")
        n = cur.fetchone()[0]
    print(f"[silver_normalise] wrote {n:,} rows -> {pg_table}")
    return n


def _create_table_from_df(cur, df: pd.DataFrame, table: str) -> None:
    """CREATE TABLE statement inferred from a pandas DataFrame."""
    dtype_map = {
        "int64":   "BIGINT",
        "Int64":   "BIGINT",
        "float64": "DOUBLE PRECISION",
        "object":  "TEXT",
        "bool":    "BOOLEAN",
        "datetime64[ns]": "TIMESTAMP",
    }
    cols_sql = []
    for col, dtype in df.dtypes.items():
        pg_type = dtype_map.get(str(dtype), "TEXT")
        cols_sql.append(f'"{col}" {pg_type}')
    cur.execute(f"CREATE TABLE {table} ({', '.join(cols_sql)})")


# ---------------------------------------------------------------------------
# SilverNormaliser
# ---------------------------------------------------------------------------

class SilverNormaliser:
    """
    Applies all data-quality normalisation rules to raw staging tables.

    Produces:
        staging.stg_company_normalised
        staging.stg_contact_normalised
        staging.stg_opportunity_normalised
        staging.stg_communication_normalised  (light cleaning only)
    """

    def __init__(self):
        self.con = duckdb.connect(":memory:")

    # ------------------------------------------------------------------
    # Company
    # ------------------------------------------------------------------

    def normalise_company(self) -> int:
        """Normalise staging.stg_company -> staging.stg_company_normalised."""
        _pg_to_duckdb(self.con, "staging.stg_company")

        # Apply Python-side maps as DuckDB CASE expressions via SQL
        comp_status_sql  = self._case_expr("Comp_Status",  COMPANY_STATUS_MAP,  "Comp_Status")
        comp_type_sql    = self._case_expr("Comp_Type",    COMPANY_TYPE_MAP,    "Comp_Type")
        comp_lang_sql    = (
            "CASE CAST(Comp_Language AS VARCHAR)"
            " WHEN '0' THEN 'French'"
            " WHEN '1' THEN 'Foreign'"
            " ELSE NULL END"
        )
        country_sql      = self._case_expr("Address_Country", COUNTRY_ISO_MAP,  "Address_Country")
        icalps_country_expr = f"CASE WHEN LENGTH({country_sql}) = 2 THEN UPPER({country_sql}) ELSE NULL END"
        full_country_sql = self._case_expr(f"({icalps_country_expr})", ISO_TO_FULL_COUNTRY_MAP, "NULL")

        # LinkedIn_URL is only present when MC_socialnetworks view was joined at extraction.
        # Gracefully default to NULL when the column is absent from this Bronze extract.
        company_cols = {d[0] for d in self.con.execute("SELECT * FROM stg_company LIMIT 0").description}
        if "LinkedIn_URL" in company_cols:
            company_linkedin_sql = """CASE
                    WHEN LinkedIn_URL LIKE '%linkedin.com%' THEN LinkedIn_URL
                    WHEN LinkedIn_URL LIKE 'in/%'
                        OR LinkedIn_URL LIKE 'company/%'
                        OR LinkedIn_URL LIKE 'pub/%'
                        OR LinkedIn_URL LIKE 'search/%'
                        OR LinkedIn_URL LIKE 'feed/%'
                        OR LinkedIn_URL LIKE 'showcase/%'
                        THEN 'https://www.linkedin.com/' || LinkedIn_URL
                    WHEN LinkedIn_URL LIKE '/in/%'
                        THEN 'https://www.linkedin.com' || LinkedIn_URL
                    ELSE NULL
                END"""
        else:
            company_linkedin_sql = "NULL"

        comp_deleted_sql = "Comp_Deleted" if "Comp_Deleted" in company_cols else "NULL"

        has_primary_first = "Comp_PrimaryPersonFirstName" in company_cols
        has_primary_last  = "Comp_PrimaryPersonLastName" in company_cols
        if has_primary_first or has_primary_last:
            first = "NULLIF(Comp_PrimaryPersonFirstName, '')" if has_primary_first else "NULL"
            last  = "NULLIF(Comp_PrimaryPersonLastName, '')"  if has_primary_last  else "NULL"
            primary_contact_sql = f"NULLIF(CONCAT_WS(' ', {first}, {last}), '')"
        else:
            primary_contact_sql = "NULL"

        self.con.execute(f"""
            CREATE OR REPLACE VIEW stg_company_normalised AS
            SELECT
                Comp_CompanyId AS icalps_company_id,
                Comp_Name,
                TRIM(Comp_WebSite)                            AS icalps_comp_website,
                Comp_Sector                                   AS icalps_company_sector,
                Comp_Sector                                   AS icalps_industry_drill_down,
                Comp_Employees                                AS icalps_comp_numemployees,
                Comp_CreatedDate,
                Comp_UpdatedDate,
                Comp_Source                                   AS icalps_compsource,
                Comp_CurrencyId,

                -- Normalised enum fields
                {comp_status_sql}                             AS icalps_companystatus,
                {comp_type_sql}                               AS icalps_companytype,
                {comp_lang_sql}                               AS icalps_comp_language,

                -- Address: street1 primary, concat full
                Address_Street1                               AS icalps_street_address,
                LEFT(
                    CONCAT_WS(', ',
                        NULLIF(Address_Street1,''),
                        NULLIF(Address_Street2,''),
                        NULLIF(Address_City,''),
                        NULLIF(Address_PostCode,''),
                        NULLIF(Address_Country,'')
                    ), 500
                )                                             AS icalps_companyaddress,
                Address_City                                  AS icalps_addresscity,
                Address_State                                 AS icalps_company_state,
                Address_PostCode                              AS icalps_address_postcode,
                Address_Country                               AS icalps_address_country,
                CASE WHEN LENGTH({country_sql}) = 2
                     THEN UPPER({country_sql})
                     ELSE NULL
                END                                           AS icalps_country,
                {full_country_sql}                            AS icalps_full_country,

                -- Contact info
                Company_Email                                 AS icalps_companyemail,
                {company_linkedin_sql}                        AS icalps_linkedin_url,

                -- Primary contact name (first + last concatenated)
                {primary_contact_sql}                         AS icalps_companyprimarycontact,

                -- Owner raw (resolve to HubSpot owner ID in owner resolution step)
                -- Legacy columns retained per Silver naming policy: do not rename owner fields.
                Owner_Email                                   AS icalps_ownerid_raw,
                Owner_FirstName, Owner_LastName,

                -- Additional owner columns (additive — render.py does not yet read these;
                -- available for future owner_resolution lookups via icalps_owner_email).
                Owner_Email                                   AS icalps_owner_email,
                {"User_FullName" if "User_FullName" in company_cols else "NULL"} AS icalps_owner_fullname,

                -- Soft-delete flag (carried through unchanged)
                {comp_deleted_sql}                            AS comp_deleted,

                -- Load-status watermark (set by bronze_loader, carried through unchanged)
                _load_status,
                _first_seen_at,
                _last_modified_at

            FROM stg_company
            WHERE Comp_CompanyId IS NOT NULL
        """)

        # Phone normalisation via pandas (E.164 regex not trivial in DuckDB)
        df = self.con.execute("SELECT * FROM stg_company_normalised").df()
        df["icalps_comp_website"]   = df["icalps_comp_website"].str.strip()
        df["icalps_comp_website"]   = df["icalps_comp_website"].str.replace(r'^http://\s+', '', regex=True)
        df["icalps_comp_website"]   = df["icalps_comp_website"].str.replace(r'^ttps://', 'https://', regex=True)
        df["icalps_linkedin_url"]   = df["icalps_linkedin_url"].str.strip()
        df["icalps_companyemail"]   = df["icalps_companyemail"].str.strip()
        df["icalps_owner_email"]    = df["icalps_owner_email"].str.strip().replace(r'^\s*$', pd.NA, regex=True).fillna("thierry.villard@icalps.com")
        df["icalps_owner_fullname"] = df["icalps_owner_fullname"].replace(r'^\s*$', pd.NA, regex=True).fillna("Thierry VILLARD")
        if "Company_Phone" in self.con.execute("SELECT * FROM stg_company LIMIT 0").df().columns:
            raw_phones = self.con.execute("SELECT Comp_CompanyId, Company_Phone FROM stg_company").df()
            raw_phones["icalps_companyphone"] = raw_phones["Company_Phone"].apply(_normalise_phone)
            phone_map: dict = raw_phones.set_index("Comp_CompanyId")["icalps_companyphone"].to_dict()
            df["icalps_companyphone"] = df["icalps_company_id"].map(phone_map)  # type: ignore[arg-type]
        else:
            df["icalps_companyphone"] = None

        # ── Canonical domain & sibling index ────────────────────────────────
        # 1. Apply clean_domain() to ALL companies (not just siblings)
        if _SIBLING_ALGORITHMS_AVAILABLE:
            df["icalps_canonical_domain"] = df["icalps_comp_website"].apply(clean_domain) if "icalps_comp_website" in df.columns else None

            # 2. Sibling index: only for plural-domain groups with Gold matches
            try:
                gold_df = _fetch_gold_companies()
                staging_df = self.con.execute(
                    "SELECT Comp_CompanyId, Comp_WebSite, Comp_Name FROM stg_company"
                ).df()
                staging_df.columns = [c.lower() for c in staging_df.columns]

                resolved_groups, unresolved = detect_all_sibling_groups(
                    staging_df,
                    gold_df,
                    domain_col="comp_website",
                    id_col="comp_companyid",
                    gold_id_col="icalps_company_id",
                )

                # Build lookup: comp_companyid → sibling_index
                sibling_map: dict = {}
                for group in resolved_groups:
                    for row_dict in assign_sibling_indices(group):
                        sibling_map[row_dict["comp_companyid"]] = row_dict["icalps_sibling_index"]

                df["icalps_sibling_index"] = df["icalps_company_id"].map(sibling_map)
                print(f"[silver_normalise] sibling index: {len(resolved_groups)} groups resolved, "
                      f"{sum(len(g.children) + 1 for g in resolved_groups)} companies indexed, "
                      f"{len(unresolved)} domains unresolved")
            except Exception as e:
                print(f"[silver_normalise] WARNING: sibling index failed — {e}")
                df["icalps_sibling_index"] = None
        else:
            df["icalps_canonical_domain"] = None
            df["icalps_sibling_index"] = None

        # Convert pandas StringDtype columns to object for DuckDB compatibility
        for col in df.columns:
            if isinstance(df[col].dtype, pd.StringDtype) or df[col].dtype.name in ('str', 'string'):
                df[col] = df[col].astype(object)
        self.con.register("stg_company_normalised_df", df)
        return _duckdb_to_pg(self.con, "stg_company_normalised_df", "staging.stg_company_normalised")

    # ------------------------------------------------------------------
    # Contact
    # ------------------------------------------------------------------

    def normalise_contact(self) -> int:
        """Normalise staging.stg_contact -> staging.stg_contact_normalised."""
        _pg_to_duckdb(self.con, "staging.stg_contact")

        # Introspect available columns — gracefully NULL-pad missing optional columns
        contact_cols = {d[0] for d in self.con.execute("SELECT * FROM stg_contact LIMIT 0").description}

        def _col_or_null(col: str, alias: str | None = None) -> str:
            """Return 'col AS alias' if col exists, else 'NULL AS alias'."""
            alias = alias or col
            return f"{col} AS {alias}" if col in contact_cols else f"NULL AS {alias}"

        contact_status_sql   = self._case_expr("Pers_Status", CONTACT_STATUS_MAP, "Pers_Status") if "Pers_Status" in contact_cols else "NULL"
        country_sql          = self._case_expr("Address_Country", COUNTRY_ISO_MAP, "Address_Country") if "Address_Country" in contact_cols else "NULL"
        pers_lang_sql        = self._case_expr("Pers_Language", LANGUAGE_ISO_MAP, "NULL") if "Pers_Language" in contact_cols else "NULL"
        company_lang_contact_sql = (
            "CASE CAST(Company_Language AS VARCHAR)"
            " WHEN '0' THEN 'French'"
            " WHEN '1' THEN 'Foreign'"
            " ELSE NULL END"
        ) if "Company_Language" in contact_cols else "NULL"
        full_country_sql     = self._case_expr(f"({country_sql})", ISO_TO_FULL_COUNTRY_MAP, "NULL") if "Address_Country" in contact_cols else "NULL"

        # LinkedIn_URL is optional — only present when MC_socialnetworks was joined at extraction.
        if "LinkedIn_URL" in contact_cols:
            contact_linkedin_sql = """CASE
                    WHEN LinkedIn_URL LIKE '%linkedin.com%' THEN LinkedIn_URL
                    WHEN LinkedIn_URL LIKE 'in/%'
                        OR LinkedIn_URL LIKE 'company/%'
                        OR LinkedIn_URL LIKE 'pub/%'
                        OR LinkedIn_URL LIKE 'search/%'
                        OR LinkedIn_URL LIKE 'feed/%'
                        OR LinkedIn_URL LIKE 'showcase/%'
                        THEN 'https://www.linkedin.com/' || LinkedIn_URL
                    WHEN LinkedIn_URL LIKE '/in/%'
                        THEN 'https://www.linkedin.com' || LinkedIn_URL
                    ELSE NULL
                END"""
        else:
            contact_linkedin_sql = "NULL"

        self.con.execute(f"""
            CREATE OR REPLACE VIEW stg_contact_normalised_base AS
            SELECT
                Pers_PersonId AS icalps_contact_id,
                {_col_or_null("Pers_CompanyId", "icalps_company_id")},
                {_col_or_null("Pers_FirstName")},
                {_col_or_null("Pers_LastName")},
                {_col_or_null("Pers_MiddleName")},
                {_col_or_null("Pers_Salutation", "icalps_salutations")},
                {_col_or_null("Pers_Gender")},
                {_col_or_null("Pers_Suffix")},
                -- Title: strip HTML, truncate 150 chars
                {"LEFT(REGEXP_REPLACE(COALESCE(Pers_Title,''), '<[^>]+>', '', 'g'), 150) AS icalps_perstitle" if "Pers_Title" in contact_cols else "NULL AS icalps_perstitle"},
                {_col_or_null("Pers_Department", "icalps_department")},
                {contact_status_sql}                          AS icalps_contactstatus,
                {company_lang_contact_sql}                    AS icalps_language,
                {_col_or_null("Pers_Source")},
                {_col_or_null("Pers_Territory")},
                {_col_or_null("Pers_WebSite")},
                {_col_or_null("Pers_CreatedDate")},
                {_col_or_null("Pers_UpdatedDate")},
                {_col_or_null("Pers_CreatedBy")},

                -- Soft-delete flag (carried through unchanged)
                {_col_or_null("Pers_Deleted", "pers_deleted")},

                -- Company (denormalised)
                {_col_or_null("Company_Name")},
                {_col_or_null("Company_WebSite")},
                {_col_or_null("Company_Type")},

                -- Email: validate format
                {"CASE WHEN Person_Email LIKE '%@%' THEN Person_Email ELSE NULL END AS icalps_email" if "Person_Email" in contact_cols else "NULL AS icalps_email"},

                -- Address
                {_col_or_null("Address_Street1", "icalps_street_address")},
                {"LEFT(CONCAT_WS(', ', NULLIF(Address_Street1,''), NULLIF(Address_City,''), NULLIF(Address_PostCode,''), NULLIF(Address_Country,'')), 500) AS icalps_full_address" if "Address_Street1" in contact_cols else "NULL AS icalps_full_address"},
                {_col_or_null("Address_City", "icalps_addresscity")},
                {_col_or_null("Address_State")},
                {_col_or_null("Address_PostCode")},
                {country_sql}                                 AS icalps_address_country,
                {full_country_sql}                            AS icalps_full_country,

                -- LinkedIn
                {contact_linkedin_sql}                        AS icalps_linkedin_url,

                -- Owner (additive — render.py does not yet read these for contact)
                {_col_or_null("User_FullName", "icalps_owner_fullname")},
                {_col_or_null("User_Email", "icalps_owner_email")},

                -- Load-status watermark (set by bronze_loader, carried through unchanged)
                _load_status,
                _first_seen_at,
                _last_modified_at

            FROM stg_contact
            WHERE Pers_PersonId IS NOT NULL
        """)

        df = self.con.execute("SELECT * FROM stg_contact_normalised_base").df()
        df["Company_WebSite"]       = df["Company_WebSite"].str.strip()
        df["Company_WebSite"]       = df["Company_WebSite"].str.replace(r'^http://\s+', '', regex=True)
        df["Company_WebSite"]       = df["Company_WebSite"].str.replace(r'^ttps://', 'https://', regex=True)
        df["icalps_email"]          = df["icalps_email"].str.strip()
        df["icalps_linkedin_url"]   = df["icalps_linkedin_url"].str.strip()
        df["icalps_owner_email"]    = df["icalps_owner_email"].str.strip().replace(r'^\s*$', pd.NA, regex=True).fillna("thierry.villard@icalps.com")
        df["icalps_owner_fullname"] = df["icalps_owner_fullname"].replace(r'^\s*$', pd.NA, regex=True).fillna("Thierry VILLARD")

        # Phone normalisation - join on icalps_contact_id
        raw = self.con.execute("""
            SELECT Pers_PersonId AS icalps_contact_id,
                   Person_Phone_Business,
                   Person_Phone_Mobile
            FROM stg_contact
        """).df()
        df["icalps_businessphone"] = raw["Person_Phone_Business"].apply(_normalise_phone)
        df["icalps_mobilephone"]   = raw["Person_Phone_Mobile"].apply(_normalise_phone)

        self.con.register("stg_contact_normalised_df", df)
        return _duckdb_to_pg(self.con, "stg_contact_normalised_df", "staging.stg_contact_normalised")

    # ------------------------------------------------------------------
    # Opportunity
    # ------------------------------------------------------------------

    def normalise_opportunity(self) -> int:
        """Normalise staging.stg_opportunity -> staging.stg_opportunity_normalised."""
        _pg_to_duckdb(self.con, "staging.stg_opportunity")

        # Introspect available columns — gracefully NULL-pad any missing optional columns
        opp_cols = {d[0] for d in self.con.execute("SELECT * FROM stg_opportunity LIMIT 0").description}

        def _col_or_null(col: str, alias: str | None = None) -> str:
            """Return 'col AS alias' if col exists, else 'NULL AS alias'."""
            alias = alias or col
            return f"{col} AS {alias}" if col in opp_cols else f"NULL AS {alias}"

        oppo_category_sql      = _col_or_null("Oppo_Category", "oppo_category")
        oppo_notes_sql         = _col_or_null("Oppo_Note", "icalps_dealnotes")
        oppo_deleted_sql       = _col_or_null("Oppo_Deleted", "oppo_deleted")
        oppo_opened_date_sql   = "TRY_CAST(Oppo_OpenedDate AS DATE)" if "Oppo_OpenedDate" in opp_cols else "TRY_CAST(Oppo_Opened AS DATE)" if "Oppo_Opened" in opp_cols else "NULL"
        oppo_targetclose_sql   = (
            "TRY_CAST(CASE WHEN Oppo_TargetCloseDate LIKE '%T%'"
            " THEN SPLIT_PART(Oppo_TargetCloseDate, 'T', 1)"
            " ELSE Oppo_TargetCloseDate END AS DATE)"
        ) if "Oppo_TargetCloseDate" in opp_cols else "NULL"
        # Effective close date: actual close (when deal was won/lost), fallback to target close
        oppo_actual_close_sql  = _col_or_null("Oppo_ActualClose", "icalps_effectiveclosedate")
        oppo_closed_sql        = _col_or_null("Oppo_Closed", "oppo_closed")
        # HubSpot stage mapping: Bronze has HubSpot_Pipeline_ID and HubSpot_Dealstage_ID
        # Map these to canonical silver column names (pipeline/dealstage coexist with icalps_stage/icalps_dealstatus)
        # Note: explicitly use AS alias since _col_or_null doesn't alias when column exists
        hs_pipeline_sql        = "COALESCE(\"HubSpot_Pipeline_ID\", '766126206') AS pipeline" if "HubSpot_Pipeline_ID" in opp_cols else "'766126206' AS pipeline"
        hs_dealstage_sql       = "\"HubSpot_Dealstage_ID\" AS dealstage" if "HubSpot_Dealstage_ID" in opp_cols else "NULL AS dealstage"
        company_language_sql   = (
            "CASE CAST(Company_Language AS VARCHAR)"
            " WHEN '0' THEN 'French'"
            " WHEN '1' THEN 'Foreign'"
            " ELSE NULL END AS company_language"
        ) if "Company_Language" in opp_cols else "NULL AS company_language"
        company_phone_sql      = _col_or_null("Company_Phone", "icalps_companyphone")
        person_email_sql       = _col_or_null("Person_Email", "person_email")
        user_fullname_sql      = _col_or_null("User_FullName", "user_fullname")
        user_email_sql         = _col_or_null("User_Email", "user_email")

        self.con.execute(f"""
            CREATE OR REPLACE VIEW stg_opportunity_normalised_base AS
            SELECT
                Oppo_OpportunityId AS icalps_deal_id,
                Oppo_Description AS oppo_description,
                CASE Oppo_Type
                    WHEN 'Desogn_Service' THEN 'Design_Service'
                    ELSE Oppo_Type
                END                                           AS icalps_dealtype,
                {oppo_category_sql},
                Oppo_Stage AS icalps_stage,
                Oppo_Status AS icalps_dealstatus,
                Oppo_AssignedUserId AS oppo_assigneduserid,
                {oppo_notes_sql},
                {oppo_deleted_sql},
                Oppo_PrimaryCompanyId AS icalps_company_id,
                Oppo_PrimaryPersonId AS icalps_contact_id,
                Oppo_CreatedDate AS oppo_createddate,
                Oppo_UpdatedDate AS oppo_updateddate,

                -- Close date: normalise to DATE (strip time component)
                TRY_CAST(
                    CASE
                        WHEN Oppo_CloseDate LIKE '%T%'
                            THEN SPLIT_PART(Oppo_CloseDate, 'T', 1)
                        ELSE Oppo_CloseDate
                    END
                AS DATE)                                      AS icalps_closedate,

                {oppo_opened_date_sql}                        AS icalps_opendate,
                {oppo_targetclose_sql}                        AS icalps_targetclose,

                -- Effective close date (actual close when deal won/lost)
                COALESCE(
                    TRY_CAST(
                        CASE
                            WHEN {oppo_actual_close_sql.split(' AS ')[0] if ' AS ' in oppo_actual_close_sql else 'NULL'} LIKE '%T%'
                                THEN SPLIT_PART({oppo_actual_close_sql.split(' AS ')[0] if ' AS ' in oppo_actual_close_sql else 'NULL'}, 'T', 1)
                            ELSE {oppo_actual_close_sql.split(' AS ')[0] if ' AS ' in oppo_actual_close_sql else 'NULL'}
                        END
                    AS DATE),
                    TRY_CAST(
                        CASE
                            WHEN {oppo_closed_sql.split(' AS ')[0] if ' AS ' in oppo_closed_sql else 'NULL'} LIKE '%T%'
                                THEN SPLIT_PART({oppo_closed_sql.split(' AS ')[0] if ' AS ' in oppo_closed_sql else 'NULL'}, 'T', 1)
                            ELSE {oppo_closed_sql.split(' AS ')[0] if ' AS ' in oppo_closed_sql else 'NULL'}
                        END
                    AS DATE)
                )                                             AS icalps_effectiveclosedate,

                -- Cost: strip currency symbol, normalise decimal.
                -- Values are in absolute euros here; converted to k€ post-view via to_keuros().
                TRY_CAST(
                    REPLACE(
                        REPLACE(
                            REGEXP_REPLACE(COALESCE(Oppo_Cost::VARCHAR,''), '[€$£ ]', '', 'g'),
                            ',', '.'
                        ),
                        ' ', ''
                    )
                AS DOUBLE)                                    AS ic_alps_cost,

                -- Forecast: absolute euros here; converted to k€ post-view via to_keuros().
                TRY_CAST(Oppo_Forecast AS DOUBLE)             AS icalps_forecast,
                TRY_CAST(Oppo_Certainty AS DOUBLE)            AS icalps_oppocertainty,

                -- Net amount in absolute euros; converted to k€ post-view via to_keuros().
                -- (cc_weighted intentionally removed — HubSpot computes weighted_amount as a
                -- calculated property; no Silver-side import needed.)
                TRY_CAST(Oppo_Forecast AS DOUBLE)
                    - COALESCE(TRY_CAST(
                        REPLACE(
                            REPLACE(
                                REGEXP_REPLACE(COALESCE(Oppo_Cost::VARCHAR,''), '[€$£ ]', '', 'g'),
                                ',', '.'
                            ), ' ', ''
                        )
                    AS DOUBLE), 0.0)                          AS cc_net,

                -- Deduplication rank (keep latest by UpdatedDate)
                ROW_NUMBER() OVER (
                    PARTITION BY Oppo_OpportunityId
                    ORDER BY Oppo_UpdatedDate DESC NULLS LAST
                )                                             AS _dedup_rank,

                -- HubSpot stage mapping (pre-computed at Bronze extraction; NULL if not extracted)
                {hs_dealstage_sql},
                {hs_pipeline_sql},

                -- Denormalised
                Company_Name AS icalps_primarydealcompany, {company_language_sql},
                {company_phone_sql},
                NULLIF(CONCAT_WS(' ', NULLIF(Person_FirstName,''), NULLIF(Person_LastName,'')), '') AS icalps_primaryoppocontact,
                Person_FirstName AS icalps_dealprimarycontactfirstname, Person_LastName AS icalps_primarycontactlastname, {person_email_sql},
                {user_fullname_sql}, {user_email_sql},

                -- Load-status watermark (set by bronze_loader, carried through unchanged)
                _load_status,
                _first_seen_at,
                _last_modified_at

            FROM stg_opportunity
            WHERE Oppo_OpportunityId IS NOT NULL
        """)

        # Keep only the latest record per opportunity
        self.con.execute("""
            CREATE OR REPLACE VIEW stg_opportunity_deduped AS
            SELECT * EXCLUDE (_dedup_rank)
            FROM stg_opportunity_normalised_base
            WHERE _dedup_rank = 1
        """)

        df = self.con.execute("SELECT * FROM stg_opportunity_deduped").df()
        df["person_email"]          = df["person_email"].str.strip()

        # Convert forecast / cost / cc_net from absolute euros to k€.
        # to_keuros is linear (k(a-b) == ka - kb), so applying it to all three
        # keeps them unit-consistent. icalps_oppocertainty is a percent and
        # stays unchanged.
        df["icalps_forecast"] = df["icalps_forecast"].apply(to_keuros)
        df["ic_alps_cost"]    = df["ic_alps_cost"].apply(to_keuros)
        df["cc_net"]          = df["cc_net"].apply(to_keuros)

        # cc_net_weighted derives from already-converted (k€) cc_net.
        df["cc_net_weighted"] = df["cc_net"] * df["icalps_oppocertainty"] / 100.0

        # Phone normalisation (E.164) — same logic as stg_company_normalised
        if "icalps_companyphone" in df.columns:
            df["icalps_companyphone"] = df["icalps_companyphone"].apply(_normalise_phone)

        self.con.register("stg_opportunity_normalised_df", df)
        return _duckdb_to_pg(self.con, "stg_opportunity_normalised_df", "staging.stg_opportunity_normalised")

    # ------------------------------------------------------------------
    # Communication (light cleaning)
    # ------------------------------------------------------------------

    def normalise_communication(self) -> int:
        """Light-clean staging.stg_communication -> staging.stg_communication_normalised."""
        _pg_to_duckdb(self.con, "staging.stg_communication")

        # Introspect available columns — gracefully NULL-pad missing optional columns
        comm_cols = {d[0] for d in self.con.execute("SELECT * FROM stg_communication LIMIT 0").description}

        def _c(col: str) -> str:
            return col if col in comm_cols else f"NULL AS {col}"

        self.con.execute(f"""
            CREATE OR REPLACE VIEW stg_communication_normalised_view AS
            SELECT
                Comm_CommunicationId,
                Comm_Action,
                Comm_Type,
                Comm_Status,
                Comm_Priority,
                {_c('Comm_Channel')},
                -- Subject: strip HTML
                REGEXP_REPLACE(COALESCE(Comm_Subject,''), '<[^>]+>', '', 'g') AS Comm_Subject,
                -- Note: strip HTML
                REGEXP_REPLACE(COALESCE(Comm_Note,''), '<[^>]+>', '', 'g')    AS Comm_Note,
                Comm_Email,
                -- Timestamps (kept as-is; UTC conversion is a Gold-layer concern)
                Comm_DateTime,
                Comm_OriginalDateTime,
                Comm_OriginalToDateTime,
                -- Linkage
                Person_Id,
                Company_Id,
                Comm_OpportunityId,
                Comm_CaseId,
                -- Soft-delete flag (carried through unchanged)
                {_c('Comm_Deleted')},
                -- Denormalised (may be absent from older Bronze extracts)
                {_c('Person_Email')},
                {_c('Person_Name')},
                {_c('Comp_CompanyId')},
                {_c('Comp_Name')},
                -- Owner email: prefer direct Comm_OwnerEmail, fall back to denormalised Companies join
                COALESCE(
                    {"Comm_OwnerEmail" if "Comm_OwnerEmail" in comm_cols else "NULL"},
                    {"\"Companies.Owner_Email\"" if '"Companies.Owner_Email"' in comm_cols else "NULL"}
                ) AS icalps_owner_email,
                {_c('Comm_OwnerFullName')} AS icalps_owner_fullname,

                -- Load-status watermark (set by bronze_loader, carried through unchanged)
                _load_status,
                _first_seen_at,
                _last_modified_at

            FROM stg_communication
            WHERE Comm_CommunicationId IS NOT NULL
              -- Silver orphan gate: exclude communications with no CRM link
              AND (Company_Id IS NOT NULL OR Person_Id IS NOT NULL)
        """)

        df = self.con.execute("SELECT * FROM stg_communication_normalised_view").df()

        # Strip HTML from Comm_Email using bs4 (values are sometimes raw HTML bodies)
        try:
            from bs4 import BeautifulSoup

            def _strip_html(val):
                if not val or not isinstance(val, str):
                    return val
                return BeautifulSoup(val, "html.parser").get_text(separator=" ", strip=True) or None

            df["Comm_Email"] = df["Comm_Email"].apply(_strip_html)
        except ImportError:
            print("[silver_normalise] WARNING: beautifulsoup4 not installed — Comm_Email HTML not stripped")

        self.con.register("stg_communication_normalised_df", df)
        return _duckdb_to_pg(self.con, "stg_communication_normalised_df", "staging.stg_communication_normalised")

    # ------------------------------------------------------------------
    # Owner resolution
    # ------------------------------------------------------------------

    def build_owner_resolution(self) -> int:
        """
        Build staging.stg_owner_resolution from hubspot.owners.

        Maps Owner_Email (IC'ALPS user email) -> hubspot_owner_id.
        Used by upsert scripts to populate icalps_ownerid.
        """
        with get_connection() as pg_conn:
            df = _pg_query_df(pg_conn, """
                SELECT
                    email         AS owner_email,
                    id            AS hubspot_owner_id,
                    first_name,
                    last_name,
                    archived
                FROM hubspot.owners
                WHERE archived IS DISTINCT FROM true
            """)

        if df.empty:
            print("[silver_normalise] WARNING: hubspot.owners returned 0 rows — skipping owner resolution")
            return 0

        self.con.register("stg_owner_resolution_df", df)
        return _duckdb_to_pg(self.con, "stg_owner_resolution_df", "staging.stg_owner_resolution")

    # ------------------------------------------------------------------
    # run_all
    # ------------------------------------------------------------------

    def run_all(self) -> dict[str, int]:
        """Run normalisation for all entities. Returns row counts per entity."""
        results: dict[str, int] = {}
        print("\n[silver_normalise] ── Company ──────────────────────────────────")
        results["company"]       = self.normalise_company()
        print("\n[silver_normalise] ── Contact ──────────────────────────────────")
        results["contact"]       = self.normalise_contact()
        print("\n[silver_normalise] ── Opportunity ──────────────────────────────")
        results["opportunity"]   = self.normalise_opportunity()
        print("\n[silver_normalise] ── Communication ────────────────────────────")
        results["communication"] = self.normalise_communication()
        print("\n[silver_normalise] ── Owner Resolution ─────────────────────────")
        try:
            results["owner_resolution"] = self.build_owner_resolution()
        except Exception as exc:
            print(f"[silver_normalise] WARNING: owner resolution failed — {exc}")
            results["owner_resolution"] = 0
        print(f"\n[silver_normalise] Done. Row counts: {results}")
        return results

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _case_expr(col: str, mapping: dict, default: str) -> str:
        """Build a DuckDB CASE WHEN expression from a Python dict."""
        clauses = "\n                ".join(
            f"WHEN {col} = '{k}' THEN '{v}'" for k, v in mapping.items()
        )
        return f"CASE\n                {clauses}\n                ELSE {default}\n            END"


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    normaliser = SilverNormaliser()
    normaliser.run_all()
