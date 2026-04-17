"""HubSpot client — separate package for CRM configuration operations.

This package handles one-time setup (form creation, property creation,
pipeline discovery). It calls HubSpot's API directly with Bearer token
auth. It has NO imports from context/, pipeline/, or sql/.

Data flow goes through managed Postgres + StackSync — not this package.
"""
