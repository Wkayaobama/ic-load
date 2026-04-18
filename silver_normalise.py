#!/usr/bin/env python3
"""
silver_normalise.py
====================
DuckDB-based Silver normalisation layer.

Reads raw ``staging.stg_*`` tables from PostgreSQL into DuckDB (in-memory),
applies all data-quality rules from ``validation/icalps_import_flags.md``,
and writes normalised results back to PostgreSQL as ``staging.stg_*_normalised``.

These normalised tables are what dbt and the upsert scripts consume —
never the raw ``stg_*`` tables directly.

Run order (enforced by run_silver_pipeline.py):
    bronze_loader  →  silver_normalise  →  validate_silver  →  dbt  →  upsert

Usage:
    from ic_load_pipeline.python.silver_normalise import SilverNormaliser
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

from context.db import get_connection


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


# ---------------------------------------------------------------------------
# Core helper: read table from PostgreSQL → pandas → DuckDB
# ---------------------------------------------------------------------------

def _pg_to_duckdb(con: duckdb.DuckDBPyConnection, table: str) -> int:
    """
    Load a PostgreSQL staging table into DuckDB in-memory.

    Returns the row count.
    """
    with get_connection() as pg_conn:
        df = pd.read_sql(f'SELECT * FROM {table}', pg_conn)
    table_name = table.replace(".", "_").replace("staging_", "")
    con.register(table_name, df)
    n = len(df)
    print(f"[silver_normalise] loaded {table} → duckdb '{table_name}' ({n:,} rows)")
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
    print(f"[silver_normalise] wrote {n:,} rows → {pg_table}")
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
        """Normalise staging.stg_company → staging.stg_company_normalised."""
        _pg_to_duckdb(self.con, "staging.stg_company")

        # Apply Python-side maps as DuckDB CASE expressions via SQL
        comp_status_sql  = self._case_expr("Comp_Status",  COMPANY_STATUS_MAP,  "Comp_Status")
        comp_type_sql    = self._case_expr("Comp_Type",    COMPANY_TYPE_MAP,    "Comp_Type")
        comp_lang_sql    = self._case_expr("Comp_Language", LANGUAGE_ISO_MAP,   "NULL")
        country_sql      = self._case_expr("Address_Country", COUNTRY_ISO_MAP,  "Address_Country")

        # LinkedIn_URL is only present when MC_socialnetworks view was joined at extraction.
        # Gracefully default to NULL when the column is absent from this Bronze extract.
        company_cols = {d[0] for d in self.con.execute("SELECT * FROM stg_company LIMIT 0").description}
        if "LinkedIn_URL" in company_cols:
            company_linkedin_sql = """CASE
                    WHEN LinkedIn_URL LIKE '%linkedin.com%' THEN LinkedIn_URL
                    ELSE NULL
                END"""
        else:
            company_linkedin_sql = "NULL"

        self.con.execute(f"""
            CREATE OR REPLACE VIEW stg_company_normalised AS
            SELECT
                Comp_CompanyId,
                Comp_Name,
                Comp_WebSite,
                Comp_Territory,
                Comp_Sector,
                Comp_Revenue,
                Comp_Employees,
                Comp_CreatedDate,
                Comp_UpdatedDate,
                Comp_Source,
                Comp_CurrencyId,

                -- Normalised enum fields
                {comp_status_sql}  AS icalps_companystatus,
                {comp_type_sql}    AS icalps_companytype,
                {comp_lang_sql}    AS icalps_language,

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
                )                                             AS icalps_full_address,
                Address_City,
                Address_State,
                Address_PostCode,
                Address_Country                               AS icalps_country_raw,
                {country_sql}                                 AS icalps_country,

                -- Contact info
                Company_Email                                 AS icalps_company_email,
                {company_linkedin_sql}                        AS icalps_linkedin_url,

                -- Owner raw (resolve to HubSpot owner ID in owner resolution step)
                Owner_Email                                   AS icalps_ownerid_raw,
                Owner_FirstName, Owner_LastName,

                -- Load-status watermark (set by bronze_loader, carried through unchanged)
                _load_status,
                _first_seen_at,
                _last_modified_at

            FROM stg_company
            WHERE Comp_CompanyId IS NOT NULL
        """)

        # Phone normalisation via pandas (E.164 regex not trivial in DuckDB)
        df = self.con.execute("SELECT * FROM stg_company_normalised").df()
        if "Company_Phone" in self.con.execute("SELECT * FROM stg_company LIMIT 0").df().columns:
            raw_phones = self.con.execute("SELECT Comp_CompanyId, Company_Phone FROM stg_company").df()
            raw_phones["icalps_companyphone"] = raw_phones["Company_Phone"].apply(_normalise_phone)
            phone_map: dict = raw_phones.set_index("Comp_CompanyId")["icalps_companyphone"].to_dict()
            df["icalps_companyphone"] = df["Comp_CompanyId"].map(phone_map)  # type: ignore[arg-type]
        else:
            df["icalps_companyphone"] = None

        self.con.register("stg_company_normalised_df", df)
        return _duckdb_to_pg(self.con, "stg_company_normalised_df", "staging.stg_company_normalised")

    # ------------------------------------------------------------------
    # Contact
    # ------------------------------------------------------------------

    def normalise_contact(self) -> int:
        """Normalise staging.stg_contact → staging.stg_contact_normalised."""
        _pg_to_duckdb(self.con, "staging.stg_contact")

        contact_status_sql = self._case_expr("Pers_Status", CONTACT_STATUS_MAP, "Pers_Status")
        country_sql        = self._case_expr("Address_Country", COUNTRY_ISO_MAP, "Address_Country")

        # LinkedIn_URL is optional — only present when MC_socialnetworks was joined at extraction.
        contact_cols = {d[0] for d in self.con.execute("SELECT * FROM stg_contact LIMIT 0").description}
        if "LinkedIn_URL" in contact_cols:
            contact_linkedin_sql = """CASE
                    WHEN LinkedIn_URL LIKE '%linkedin.com/in/%' THEN LinkedIn_URL
                    WHEN LinkedIn_URL LIKE '/in/%'
                        THEN 'https://www.linkedin.com' || LinkedIn_URL
                    ELSE NULL
                END"""
        else:
            contact_linkedin_sql = "NULL"

        self.con.execute(f"""
            CREATE OR REPLACE VIEW stg_contact_normalised_base AS
            SELECT
                Pers_PersonId,
                Pers_CompanyId,
                Pers_FirstName,
                Pers_LastName,
                Pers_MiddleName,
                Pers_Salutation,
                Pers_Gender,
                Pers_Suffix,
                -- Title: strip HTML, truncate 150 chars
                LEFT(
                    REGEXP_REPLACE(COALESCE(Pers_Title,''), '<[^>]+>', '', 'g'),
                    150
                )                                             AS icalps_title,
                Pers_Department,
                {contact_status_sql}                          AS icalps_pers_status,
                Pers_Source,
                Pers_Territory,
                Pers_WebSite,
                Pers_CreatedDate,
                Pers_UpdatedDate,
                Pers_CreatedBy,

                -- Company (denormalised)
                Company_Name,
                Company_WebSite,
                Company_Type,

                -- Email: validate format
                CASE
                    WHEN Person_Email LIKE '%@%' THEN Person_Email
                    ELSE NULL
                END                                           AS icalps_email,

                -- Address
                Address_Street1                               AS icalps_street_address,
                LEFT(
                    CONCAT_WS(', ',
                        NULLIF(Address_Street1,''),
                        NULLIF(Address_City,''),
                        NULLIF(Address_PostCode,''),
                        NULLIF(Address_Country,'')
                    ), 500
                )                                             AS icalps_full_address,
                Address_City,
                Address_State,
                Address_PostCode,
                {country_sql}                                 AS icalps_country,

                -- LinkedIn
                {contact_linkedin_sql}                        AS icalps_linkedin_url,

                -- Load-status watermark (set by bronze_loader, carried through unchanged)
                _load_status,
                _first_seen_at,
                _last_modified_at

            FROM stg_contact
            WHERE Pers_PersonId IS NOT NULL
        """)

        df = self.con.execute("SELECT * FROM stg_contact_normalised_base").df()

        # Phone normalisation
        raw = self.con.execute("""
            SELECT Pers_PersonId,
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
        """Normalise staging.stg_opportunity → staging.stg_opportunity_normalised."""
        _pg_to_duckdb(self.con, "staging.stg_opportunity")

        # Introspect available columns — gracefully NULL-pad any missing optional columns
        opp_cols = {d[0] for d in self.con.execute("SELECT * FROM stg_opportunity LIMIT 0").description}

        def _col_or_null(col: str, alias: str | None = None) -> str:
            alias = alias or col
            return f"{col}" if col in opp_cols else f"NULL AS {alias}"

        oppo_category_sql      = _col_or_null("Oppo_Category")
        oppo_notes_sql         = _col_or_null("Oppo_Notes")
        oppo_deleted_sql       = _col_or_null("Oppo_Deleted")
        oppo_opened_date_sql   = "TRY_CAST(Oppo_OpenedDate AS DATE)" if "Oppo_OpenedDate" in opp_cols else "TRY_CAST(Oppo_Opened AS DATE)" if "Oppo_Opened" in opp_cols else "NULL"
        hs_dealstage_sql       = _col_or_null("hubspot_dealstage_name")
        hs_pipeline_sql        = _col_or_null("hubspot_pipeline_id")
        company_language_sql   = _col_or_null("Company_Language")
        person_email_sql       = _col_or_null("Person_Email")
        user_fullname_sql      = _col_or_null("User_FullName")
        user_email_sql         = _col_or_null("User_Email")

        self.con.execute(f"""
            CREATE OR REPLACE VIEW stg_opportunity_normalised_base AS
            SELECT
                Oppo_OpportunityId,
                Oppo_Description,
                Oppo_Type,
                {oppo_category_sql},
                Oppo_Stage,
                Oppo_Status,
                Oppo_AssignedUserId,
                {oppo_notes_sql},
                {oppo_deleted_sql},
                Oppo_PrimaryCompanyId,
                Oppo_PrimaryPersonId,
                Oppo_CreatedDate,
                Oppo_UpdatedDate,

                -- Close date: normalise to DATE (strip time component)
                TRY_CAST(
                    CASE
                        WHEN Oppo_CloseDate LIKE '%T%'
                            THEN SPLIT_PART(Oppo_CloseDate, 'T', 1)
                        ELSE Oppo_CloseDate
                    END
                AS DATE)                                      AS icalps_closedate,

                {oppo_opened_date_sql}                        AS icalps_opendate,

                -- Cost: strip currency symbol, normalise decimal
                TRY_CAST(
                    REPLACE(
                        REPLACE(
                            REGEXP_REPLACE(COALESCE(Oppo_Cost::VARCHAR,''), '[€$£ ]', '', 'g'),
                            ',', '.'
                        ),
                        ' ', ''
                    )
                AS DOUBLE)                                    AS icalps_cost,

                -- Forecast (k€ assumed — validated in validate_silver.py)
                TRY_CAST(Oppo_Forecast AS DOUBLE)             AS icalps_forecast,
                TRY_CAST(Oppo_Certainty AS DOUBLE)            AS icalps_certainty,

                -- Computed columns (replicate HubSpot custom properties)
                TRY_CAST(Oppo_Forecast AS DOUBLE)
                    * TRY_CAST(Oppo_Certainty AS DOUBLE) / 100.0
                                                              AS cc_weighted,
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
                Company_Name, {company_language_sql},
                Person_FirstName, Person_LastName, {person_email_sql},
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

        # Add cc_net_weighted
        df["cc_net_weighted"] = df["cc_net"] * df["icalps_certainty"] / 100.0

        self.con.register("stg_opportunity_normalised_df", df)
        return _duckdb_to_pg(self.con, "stg_opportunity_normalised_df", "staging.stg_opportunity_normalised")

    # ------------------------------------------------------------------
    # Communication (light cleaning)
    # ------------------------------------------------------------------

    def normalise_communication(self) -> int:
        """Light-clean staging.stg_communication → staging.stg_communication_normalised."""
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
                -- Denormalised (may be absent from older Bronze extracts)
                {_c('Person_Email')},
                {_c('Person_Name')},
                {_c('Comp_CompanyId')},
                {_c('Comp_Name')},
                {_c('Comp_WebSite')},
                -- Owner email from denormalised Companies join (used for parent tiebreaker)
                {_c('"Companies.Owner_Email"')} AS icalps_owner_email,

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
        self.con.register("stg_communication_normalised_df", df)
        return _duckdb_to_pg(self.con, "stg_communication_normalised_df", "staging.stg_communication_normalised")

    # ------------------------------------------------------------------
    # Owner resolution
    # ------------------------------------------------------------------

    def build_owner_resolution(self) -> int:
        """
        Build staging.stg_owner_resolution from hubspot.owners.

        Maps Owner_Email (IC'ALPS user email) → hubspot_owner_id.
        Used by upsert scripts to populate icalps_ownerid.
        """
        with get_connection() as pg_conn:
            df = pd.read_sql("""
                SELECT
                    email         AS owner_email,
                    id            AS hubspot_owner_id,
                    first_name,
                    last_name,
                    archived
                FROM hubspot.owners
                WHERE archived IS DISTINCT FROM true
            """, pg_conn)

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
