# Pipeline

This directory will hold the imperative runtime flow for `ic-load`.

Planned modules:
- state machine
- runner entrypoints
- Silver gate orchestration
- dedupe guardrail
- explicit Gold validation gate
- Gold write orchestration as the default terminal path
- optional explicit StackSync sync checkpoint
- optional association bridge trigger

The goal is thin orchestration over stable contracts and SQL assets.
