# Tests

This directory will hold the minimal verification harness for `ic-load`.

First-wave coverage should focus on:
- state-machine transitions
- config and context validation
- SQL render sanity checks
- sync-before-association ordering

The test surface should stay smaller than the legacy repo while protecting the critical path.
