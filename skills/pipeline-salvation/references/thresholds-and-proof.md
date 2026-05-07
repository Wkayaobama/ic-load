## Thresholds And Proof

Do not say a rescue is "working" unless you can name the threshold it satisfies.

## Threshold Types

- functionality threshold: which business path works end to end
- safety threshold: what prevents contamination or accidental live writes
- portability threshold: what works on a second machine or in Codespaces
- context threshold: what another agent needs to continue the work without the legacy workspace

## Probe Order

1. unit or contract tests
2. rendered artifacts
3. staging-only execution
4. read-only live metadata probes
5. approved live execution

## Reassessment Rule

If a guardrail or abstraction:

- blocks too much of the rescued path
- relies on hardcoded entity assumptions
- only works on the original machine
- cannot be explained through config or contract

then do one of these:

- move it back to probe-only
- reduce the scope
- make it config-driven
- postpone it

Do not call it production-ready just because the idea is sound.

## Recommended Evidence

- test output
- generated CSV or SQL samples
- schema or metadata snapshots
- side-by-side mapping assessments
- runner history artifacts
- explicit counts for blocked, reviewed, matched, or unresolved rows
