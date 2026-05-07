"""
silver_company.py — Native company silver normalisation for ic-load.

This module implements company-specific silver layer transformations without
delegating to the legacy module. It uses:
- context.algorithms.company_siblings for domain grouping and sibling detection
- context.algorithms.phone_normalise for E.164 phone normalization
- context.db for PostgreSQL connectivity

## What This Module Does

1. Reads raw company data from staging.stg_company
2. Applies domain canonicalization (clean_domain)
3. Detects sibling groups and assigns sibling indices
4. Normalizes phone numbers to E.164 format
5. Writes enriched data to staging.stg_company_normalised

## Usage

>>> from pipeline.silver_company import SilverCompanyNormaliser
>>> normaliser = SilverCompanyNormaliser()
>>> result = normaliser.normalise()
>>> print(result)  # {'entity': 'company', 'rows': 1234, ...}
"""
from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from context.db import get_connection
from context.algorithms.company_siblings import (
    clean_domain,
    detect_all_sibling_groups,
    assign_sibling_indices,
)
from context.algorithms.phone_normalise import normalise_phone_e164

_log = logging.getLogger(__name__)


class SilverCompanyNormaliser:
    """Native company silver normaliser using modular algorithms.

    This is the clean replacement for the legacy DuckDB-based normaliser.
    All logic runs in Python+pandas with PostgreSQL as the source/target.
    """

    def __init__(self):
        pass

    def _fetch_bronze_companies(self) -> pd.DataFrame:
        """Read raw company data from staging.stg_company."""
        with get_connection() as conn:
            df = pd.read_sql("""
                SELECT *
                FROM staging.stg_company
                ORDER BY "Comp_CompanyId"
            """, conn)
        _log.info("Fetched %d bronze company rows", len(df))
        return df

    def _fetch_gold_companies(self) -> pd.DataFrame:
        """Fetch hubspot.companies for sibling parent resolution.

        Returns DataFrame with icalps_company_id, hubspot_id, and contact_count.
        """
        with get_connection() as conn:
            try:
                df = pd.read_sql("""
                    SELECT
                        icalps_company_id::text AS icalps_company_id,
                        id AS hubspot_id,
                        COALESCE(num_associated_contacts, 0)::int AS contact_count
                    FROM hubspot.companies
                    WHERE icalps_company_id IS NOT NULL
                """, conn)
                _log.info("Fetched %d Gold company rows for parent resolution", len(df))
                return df
            except Exception as e:
                _log.warning("Could not fetch Gold companies: %s", e)
                return pd.DataFrame(columns=["icalps_company_id", "hubspot_id", "contact_count"])

    def _apply_sibling_indices(self, df: pd.DataFrame, gold_df: pd.DataFrame) -> pd.DataFrame:
        """Apply company sibling detection and assign indices.

        Adds columns:
        - icalps_canonical_domain: The cleaned domain for grouping
        - icalps_sibling_index: 0=parent, 1..N=children, NULL=singleton
        """
        # Add canonical domain column
        domain_col = None
        for candidate in ["Comp_WebSite", "comp_website", "Company_WebSite"]:
            if candidate in df.columns:
                domain_col = candidate
                break

        if domain_col is None:
            _log.warning("No domain column found, skipping sibling detection")
            df["icalps_canonical_domain"] = None
            df["icalps_sibling_index"] = None
            return df

        # Compute canonical domains
        df["icalps_canonical_domain"] = df[domain_col].apply(clean_domain)

        # Initialize sibling index as NULL (singletons stay NULL)
        df["icalps_sibling_index"] = None

        # Detect sibling groups
        id_col = "Comp_CompanyId"
        if id_col not in df.columns:
            for candidate in ["comp_companyid", "Company_Id"]:
                if candidate in df.columns:
                    id_col = candidate
                    break

        resolved_groups, unresolved_domains = detect_all_sibling_groups(
            staging_df=df,
            gold_df=gold_df,
            domain_col=domain_col,
            id_col=id_col,
            gold_id_col="icalps_company_id",
        )

        _log.info(
            "Sibling detection: %d resolved groups, %d unresolved domains",
            len(resolved_groups),
            len(unresolved_domains),
        )

        # Build sibling index map from resolved groups
        sibling_map: dict[int, int] = {}
        for group in resolved_groups:
            rows = assign_sibling_indices(group, id_col=id_col)
            for row in rows:
                comp_id = row.get("comp_companyid")
                sibling_idx = row.get("icalps_sibling_index")
                if comp_id is not None:
                    sibling_map[int(comp_id)] = sibling_idx

        # Apply sibling indices
        if sibling_map:
            df["icalps_sibling_index"] = df[id_col].map(sibling_map)
            _log.info("Assigned sibling indices to %d companies", len(sibling_map))

        return df

    def _apply_phone_normalisation(self, df: pd.DataFrame) -> pd.DataFrame:
        """Normalise phone columns to E.164 format.

        Looks for columns like Company_Phone, comp_phone, etc.
        """
        phone_cols = [
            ("Comp_Phone", "icalps_companyphone"),
            ("Company_Phone", "icalps_companyphone"),
            ("comp_phone", "icalps_companyphone"),
        ]

        for source_col, target_col in phone_cols:
            if source_col in df.columns:
                df[target_col] = df[source_col].apply(normalise_phone_e164)
                _log.info("Normalised phone column %s -> %s", source_col, target_col)
                break
        else:
            df["icalps_companyphone"] = None
            _log.info("No phone column found, setting icalps_companyphone to NULL")

        return df

    def _write_to_staging(self, df: pd.DataFrame) -> int:
        """Write normalised data to staging.stg_company_normalised.

        Uses DROP + CREATE AS SELECT pattern for clean refresh.
        This ensures column names match exactly.
        """
        import io

        with get_connection() as conn:
            with conn.cursor() as cur:
                # Drop existing table if it exists
                cur.execute("DROP TABLE IF EXISTS staging.stg_company_normalised CASCADE")

                # Create table with correct structure
                # Get column types from DataFrame
                col_defs = []
                for col in df.columns:
                    dtype = df[col].dtype
                    if dtype == 'object':
                        sql_type = 'TEXT'
                    elif dtype == 'int64':
                        sql_type = 'BIGINT'
                    elif dtype == 'float64':
                        sql_type = 'DOUBLE PRECISION'
                    elif 'datetime' in str(dtype):
                        sql_type = 'TIMESTAMP'
                    elif dtype == 'bool':
                        sql_type = 'BOOLEAN'
                    else:
                        sql_type = 'TEXT'
                    col_defs.append(f'"{col}" {sql_type}')

                create_sql = f"""
                    CREATE TABLE staging.stg_company_normalised (
                        {', '.join(col_defs)}
                    )
                """
                cur.execute(create_sql)

                # Use COPY for fast bulk insert
                buffer = io.StringIO()
                # Convert DataFrame to CSV in buffer
                df.to_csv(buffer, index=False, header=False, sep='\t', na_rep='\\N')
                buffer.seek(0)

                col_list = ', '.join([f'"{c}"' for c in df.columns])
                cur.copy_expert(
                    f"COPY staging.stg_company_normalised ({col_list}) FROM STDIN WITH (FORMAT csv, DELIMITER E'\\t', NULL '\\N')",
                    buffer
                )

                conn.commit()

                # Verify row count
                cur.execute("SELECT COUNT(*) FROM staging.stg_company_normalised")
                row_count = cur.fetchone()[0]
                _log.info("Wrote %d rows to staging.stg_company_normalised", row_count)
                return row_count

    def normalise(self) -> dict[str, Any]:
        """Run the full company normalisation pipeline.

        Returns:
            dict with entity, row count, and processing stats.
        """
        _log.info("Starting company silver normalisation")

        # Step 1: Read bronze data
        df = self._fetch_bronze_companies()
        if df.empty:
            _log.warning("No bronze company data found")
            return {"entity": "company", "rows": 0, "status": "no_data"}

        # Step 2: Fetch Gold companies for parent resolution
        gold_df = self._fetch_gold_companies()

        # Step 3: Apply sibling detection and indices
        df = self._apply_sibling_indices(df, gold_df)

        # Step 4: Apply phone normalisation
        df = self._apply_phone_normalisation(df)

        # Step 5: Write to staging table
        row_count = self._write_to_staging(df)

        return {
            "entity": "company",
            "rows": row_count,
            "sibling_groups_resolved": df["icalps_sibling_index"].notna().sum(),
            "phones_normalised": df["icalps_companyphone"].notna().sum(),
            "status": "success",
        }
