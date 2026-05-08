"""IcAlps stale-record cleanup pipeline.

Sibling to ``pipeline.library_files``. Reuses the same HubSpotClient,
PROD_POSTGRES_DSN, staging schema, and gate convention. Independent module:
cleanup imports from library_files; library_files never imports from cleanup.

Subcommands (see ``pipeline.cleanup.runner``):
    snapshot              — populate staging.fct_cleanup_manifest
    check-overlap         — abort if cleanup targets overlap with library_files notes
    archive               — batch-archive HubSpot records (100 ids/call), gated
    gdpr-delete-contacts  — irreversible purge; gated separately
    delete-properties     — drop schema definitions; gated separately
    status                — print ledger summary
"""
