"""Legacy modules ported into ic-load for standalone operation.

This package contains salvaged business logic from the parent IC_Load repo,
adapted to use ic-load's context.db and context.algorithms modules.

Modules
-------
silver_normalise.py
    DuckDB-based silver normalization for company, contact, opportunity,
    and communication entities. Uses context.algorithms.company_siblings
    for domain-based sibling detection and context.algorithms.phone_normalise
    for E.164 phone formatting.

validate_silver.py
    Post-normalization data quality gate. Runs checks against
    staging.stg_*_normalised tables and produces JSON reports.
    Checks include row counts, void rates, duplicate detection,
    and reconciliation match rates against HubSpot Gold layer.

Key Changes from Parent Repo
----------------------------
- Removed sys.path manipulation and relative imports
- Changed `from db import get_connection` to `from context.db import get_connection`
- Uses PROJECT_ROOT from context.config for artifact paths
- Integrated with ic-load's algorithm modules in context.algorithms/
"""
