## Salvation Loop

Use this loop when the codebase is messy but the functionality is probably still there.

1. Define the first useful threshold.
   Example: "Can load, normalize, validate, and stage the core entities" or "Can reach Gold safely with explicit approval."

2. Freeze the execution path in plain language.
   Write it as a linear sequence first, even if the real code is sprawling.

3. Bucket the files.
   Keep, rewrite-minimal, defer, or drop.

4. Extract the smallest runnable spine that still proves the threshold.
   Move state, runner, config, and critical transforms first.

5. Preserve the critical context.
   Bundle schema, rules, mapping contracts, and non-negotiable algorithms before trimming the workspace.

6. Probe in ascending risk order.
   Local tests -> staging-only probes -> read-only live probes -> approved live steps.

7. Recalibrate guardrails when they block the rescue path.
   If a guardrail is logically sound but not yet portable or config-wide, downgrade it to probe-only.

8. Commit the checkpoint.
   Every stable threshold should be recoverable from version control and from the re-entry file.

Deliverables for each loop:

- one restated boundary
- one proven threshold
- one cleaned checkpoint
- one updated re-entry file
