# dbt

This directory is reserved for the dbt project boundary.

dbt remains responsible for:
- staging to intermediate transformations
- intermediate to mart models
- dbt tests on those models

`ic-load` should trigger dbt here, not reproduce dbt logic elsewhere.
