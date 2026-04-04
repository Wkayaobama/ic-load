## Dedupe Guardrails

Apply the dedupe gate before:

- Gold upsert
- mirrored association writes

Use three outcomes:

- `safe`
- `review`
- `block`

## Entity Heuristics

### Company

Prioritize:

- exact canonical ID matches
- exact normalized domain matches
- normalized name similarity
- common-root or Levenshtein-style grouping after parent selection
- corroborating website, city, country, phone, and LinkedIn signals

### Contact

Prioritize:

- exact canonical ID matches
- exact normalized email matches
- normalized full-name similarity
- company linkage corroboration
- phone and LinkedIn corroboration when present

### Opportunity

Prioritize:

- exact canonical deal ID matches
- normalized deal-name similarity
- company/contact linkage corroboration
- stage and pipeline compatibility

### Case Or Ticket

Prioritize:

- exact external or legacy ticket ID matches
- normalized subject similarity
- company and contact corroboration
- status, stage, and date coherence

### Communication

Prefer deterministic unique ID first.
Treat fuzzy matching as secondary because communication objects already carry `icalps_<communication_id>` style idempotency keys.

## Association Rule

Only create an association when:

- the engagement record is `safe`
- the target entity record is `safe`
- the association row itself is not already present

If the target entity is `review` or `block`, stop the association write even if the reverse lookup technically resolves.

## Operational Warning

Mirrored association tables can bypass native CRM UX guardrails.

That means:

- entity dedupe and association safety are one decision chain
- idempotent SQL is necessary but insufficient
- reverse lookup by StackSync UUID must never be treated as proof that the entity choice was correct
