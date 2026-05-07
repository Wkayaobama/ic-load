# jl-selective-changes ← main merge — resolution matrix

> Default rule: **main loses unless there's an explicit rationale that main is better for that specific block.**
> jl-selective-changes is the production design; main contributes additive utilities and bug fixes only.

## Strategy used

`git merge -X ours --no-commit origin/main` — auto-resolves content conflicts to HEAD (jl). Resolves all 10 UU + 6 AA conflict files to jl's content, while still absorbing main's *non-conflicting* additions (e.g. new SQL functions, archive folders, new hooks/ modules).

## Inventory of pending changes (after -X ours)

| Status | Count | Action |
|---|---|---|
| `AU _archive/dbt/...` | 44 | **Reject rename — move back to `dbt/...`** (mechanical, no decision) |
| `R  jl-path -> _archive/...` | 5 | **Per-file decision — see §1 below** |
| `A  ...` | 36 | **Keep** (additive — new SQL fns, archive folders, hooks modules) |
| `M  ...` | 13 | **Verify** -X ours produced sensible jl-priority output (§2 below) |
| `D  dbt/...` | 44 | Mirror of the AU — undone by §0 below |

---

## §0 — 44 AU dbt files (mechanical, no decision)

**Action:** for each of the 44 files, move from `_archive/dbt/...` back to `dbt/...` and stage at the jl location.

Sample paths affected:
```
_archive/dbt/.gitignore                                  → dbt/.gitignore
_archive/dbt/dbt_project.yml                             → dbt/dbt_project.yml
_archive/dbt/models/marts/fct_communication_calls.sql    → dbt/models/marts/fct_communication_calls.sql
_archive/dbt/models/marts/fct_communication_notes.sql    → dbt/models/marts/fct_communication_notes.sql
_archive/dbt/models/marts/fct_communication_tasks.sql    → dbt/models/marts/fct_communication_tasks.sql
_archive/dbt/models/marts/fct_communication_meetings.sql → dbt/models/marts/fct_communication_meetings.sql
... (40 more)
```

**Rationale:** dbt is part of jl's production design. The fct_communication_* layer is load-bearing. R4 owner cols and R5 calls→tasks UNION ALL live in these models. Keeping them at `dbt/` preserves both the architecture and the functionality.

**Note:** main's `_archive/dbt/README.md` (which is a NEW file main added — explaining the archive) was an `R` rename of jl's `dbt/README.md`. Conflict on whether dbt/README.md still exists. We keep dbt/ and our README.

---

## §1 — Renames to/from `_archive/` (per-file decision)

| Source | Target | Decision | Rationale |
|---|---|---|---|
| `dbt/README.md` | `_archive/dbt/README.md` | **Reject — keep at dbt/** | Same as §0 — dbt active. |
| `.devcontainer/devcontainer.env.template` | `_archive/.devcontainer/...` | **DECISION NEEDED** | Does jl use devcontainer? If yes → reject; if codespaces was abandoned → accept archive. |
| `.devcontainer/devcontainer.json` | `_archive/.devcontainer/...` | **DECISION NEEDED** | Same. |
| `.devcontainer/post-create.sh` | `_archive/.devcontainer/...` | **DECISION NEEDED** | Same. |
| `pipeline/staging_resolution_probe.py` | `_archive/staging_resolution_probe.py` | **DECISION NEEDED** | Is this script still live on jl? Check `pipeline/__init__.py` exports + any callers. |
| `salvation.md` | `docs/salvation.md` | **Accept relocation** | Just a docs reorganization — content preserved, location is more sensible. |

---

## §2 — `M` files — spot-check `-X ours` output (13 files)

These were modified on both sides and `-X ours` auto-merged. Each needs a quick eyeball to confirm jl's lines stayed where they should:

```
.gitignore
GomplateRepoMix/business_rules.yaml
GomplateRepoMix/repomix.config.json
context/__init__.py
context/config.py
context/db.py
docs/AD_HOC_TRANSFORM_CONTEXT.md
docs/RAW_CSV_TO_STAGING_SNIPPET.md
pipeline/bronze.py
pipeline/probe.py
pipeline/runner.py        ← biggest, 9 conflict blocks before -X ours auto-resolved
tests/test_orchestration_probe.py
tests/test_packaging_contract.py
```

**Checklist for each:**
- jl's intentional features (e.g. `--preview`, `--enable-post-gold`, `dbt_runner` field, `DBT_BUILD` enum, `gold_previewer`, `association_previewer`) are present?
- main's non-conflicting bug fixes (e.g. `pd.read_sql()` → cursor fetch, `NotImplementedError` cleanup) absorbed where they don't fight jl's design?
- File compiles / imports cleanly?

I will read each one and report. If main's auto-merged additions break jl's design (e.g. removed `dbt_runner` callable from `PipelineHooks`), I'll surgically restore the jl version for that block.

---

## §3 — `A` additions from main (36 files) — keep all

Most are pure archives or genuinely new content. Sample:

| Path | Reason to keep |
|---|---|
| `_archive/.vscode/*` | Main's archive of editor config — additive |
| `_archive/hubspot-client/*` | Main's archive of an old HubSpot client — additive |
| `_archive/skills/form-workflow/*` | Main's archived skill — additive |
| `docs/TRACEABILITY.md` | New doc — additive |
| `docs/diagnostic_queries.sql` | New ops aid — additive |
| `pipeline/hooks/associations.py` | New modular hook — **see §3a** |
| `pipeline/hooks/bronze.py` | Same |
| `pipeline/hooks/dedupe.py` | Same |
| `pipeline/hooks/entity_postprocess.py` | Same |
| `pipeline/hooks/gold.py` | Same |
| `pipeline/hooks/post_run_verify.py` | Same |
| `pipeline/hooks/silver_validator.py` | Same |
| `sql/functions/fn_map_language_iso.sql` | Useful additive utility |
| `sql/functions/fn_normalize_currency.sql` | Useful additive utility |
| `sql/functions/fn_resolve_association.sql` | Useful additive utility |
| `sql/functions/fn_map_country_iso.sql` | Useful additive utility |
| `sql/functions/fn_normalize_phone_e164.sql` | Useful additive utility |
| `sql/functions/fn_validate_linkedin_url.sql` | Useful additive utility |

### §3a — pipeline/hooks/* modular split

Main extracted hooks into individual modules. This is a **defensible "main wins" case**: the split is clean, single-responsibility, and additive (jl had inline hooks; main has the same callables in a more organised module structure).

**Catch:** main's `pipeline/hooks/__init__.py` has `PipelineHooks` shaped for the post-dbt-removal world (no `dbt_runner` field). With dbt restored on jl, the dataclass needs jl's `dbt_runner: Callable[[str, bool], bool]` field re-added.

**Proposal:**
- Keep main's modular `pipeline/hooks/*.py` files (clean structure)
- Re-add `dbt_runner` field to `PipelineHooks` to match jl's runner.py expectations
- This is the only place where I'll do a manual 3-way reconciliation (jl + main hybrid)

**Decision needed:** OK with this hybrid?

---

## §4 — Open decisions before I apply

1. **`.devcontainer/*` — keep active or accept main's archive?**
2. **`pipeline/staging_resolution_probe.py` — keep active or accept main's archive?**
3. **`pipeline/hooks/*` modular split — adopt main's structure with `dbt_runner` re-added (per §3a)?** (My recommendation: yes.)
4. **After applying:** is "library_files comes along on top" still the goal? (If yes, after merge clean we rebase library_files commits forward.)

---

## Execution sequence after approval

1. §0 — restore 44 dbt files from `_archive/` (mechanical loop)
2. §1 — restore the 4-5 active files based on your answers
3. §3a — apply hooks reconciliation if approved
4. §2 — verify the 13 M files; surgical fixes if any block-resolutions came out wrong
5. Run `pytest pipeline/library_files/tests` (since library_files isn't yet on this branch, test only what's here on jl-merge)
6. Show diff stat
7. Pause for your final review **before commit** and **before push**
