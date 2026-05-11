# operator-scaffold.md — IC'ALPS operator entry point

Reference for environment setup, worktree layout, invocation pattern, and
links to the two phase-specific runbooks (`operator-library.md`,
`operator-cleanup.md`).

## Layout

```
C:\Users\ayaobama\Documents\AnthonySalesOps\Codebase\
├── .env.icalps                       ← canonical secrets, gitignored
├── ic-load-jl-selective-changes\     ← branch: library-files-cleanup-prod
├── ic-load-library-prod\             ← branch: library-files-rest-sandbox-prod
└── ic-load-jl-merge\                 ← branch: w/jl-merge-main (legacy)
```

`.env.icalps` lives one level above every worktree. Every worktree reads it
via `find_dotenv(usecwd=True)` walk-up in `Settings.from_env()`. Worktree-local
`.env` overrides if present. Precedence: process env > worktree `.env` >
`.env.icalps`.

## Invocation pattern

```powershell
cd <worktree>
uv run python -m pipeline.<module>.runner <subcommand> ...
```

uv handles `.venv/` per worktree from `pyproject.toml`. First run in a
worktree creates the venv (~10s, hardlink cache); subsequent runs <1s
overhead. No manual `python -m venv`, no `pip install`, no activation.

## Setup — one-time

### uv

```powershell
winget install --id=astral-sh.uv
```

### Oh My Posh + Nerd Font (visual branch indicator)

```powershell
winget install JanDeDobbeleer.OhMyPosh --source winget
oh-my-posh font install CaskaydiaMono
```

Windows Terminal → Settings → PowerShell profile → Appearance → Font face →
**CaskaydiaMono Nerd Font**.

```powershell
notepad $PROFILE
# (if missing: New-Item -Path $PROFILE -Type File -Force, then notepad $PROFILE)
```

Append:

```powershell
oh-my-posh init pwsh --config "$env:POSH_THEMES_PATH\jandedobbeleer.omp.json" | Invoke-Expression
```

```powershell
. $PROFILE
```

Prompt now shows the directory and the active git branch. Disambiguates which
worktree the current shell is in.

### Worktrees

```powershell
git worktree list
```

If `ic-load-library-prod` is missing:

```powershell
git worktree add `
    "C:\Users\ayaobama\Documents\AnthonySalesOps\Codebase\ic-load-library-prod" `
    library-files-rest-sandbox-prod
```

### .env.icalps

```powershell
copy .env.icalps.example `
    "C:\Users\ayaobama\Documents\AnthonySalesOps\Codebase\.env.icalps"
notepad "C:\Users\ayaobama\Documents\AnthonySalesOps\Codebase\.env.icalps"
```

Verify env loads:

```powershell
cd C:\Users\ayaobama\Documents\AnthonySalesOps\Codebase\ic-load-library-prod
uv run python -c "from pipeline.library_files.config import Settings; s = Settings.from_env(); print('dsn=', s.prod_postgres_dsn[:40], '...'); print('token len=', len(s.hubspot_token))"
```

A `RuntimeError: HUBSPOT_SANDBOX_TOKEN is not set` means `.env.icalps` is not
at the Codebase root.

## Worktree-to-task mapping

| Task | Worktree | Branch |
|---|---|---|
| Library files migration (Phase 7c → 11) | `ic-load-library-prod` | `library-files-rest-sandbox-prod` |
| Stale-record cleanup (Phase A → G) | `ic-load-jl-selective-changes` | `library-files-cleanup-prod` |

The cleanup branch was forked off the library branch. Library commits merge
forward into cleanup cleanly.

A branch can only be checked out in one worktree at a time. `git switch` to
a branch already checked out elsewhere fails — that constraint is the safety
property.

## Approval gates

Session-level only. Never durable in `.env.icalps`.

| Variable | Phase |
|---|---|
| `ICALPS_APPROVE_FILES_UPLOAD` | library Phase 1 (file upload) |
| `ICALPS_APPROVE_FILE_NOTES_POST` | library Phase 2 (note + assoc) |
| `ICALPS_APPROVE_ARCHIVE` | cleanup Phase E (batch archive) |
| `ICALPS_APPROVE_GDPR_DELETE` | cleanup Phase E2 (irreversible contact purge) |
| `ICALPS_APPROVE_PROP_DELETE` | cleanup Phase F (irreversible schema deletion) |

```powershell
$env:ICALPS_APPROVE_ARCHIVE = "1"
uv run python -m pipeline.cleanup.runner archive --object deals
Remove-Item env:ICALPS_APPROVE_ARCHIVE
```

Default for every gate is unset = DRY-RUN. Each runner prints a banner
showing LIVE vs DRY for every gate at the top of every run.

## Sandbox probing

Cleanup has a sandbox-probe path (Phase D2 in `operator-cleanup.md`) that
exercises the full archive → ledger code path against the sandbox HubSpot
portal before any prod write. Pattern: seed sandbox companies, materialise
a temporary postgres view of those sandbox IDs, shadow `HUBSPOT_PROD_TOKEN`
with `HUBSPOT_SANDBOX_TOKEN` for the session, run archive, verify in sandbox
UI, drop the view + reset the env var. See operator-cleanup.md Phase D2 for
exact commands.

Library files has the same shape at Phase 7c (`operator-library.md`) — its
sandbox round-trip is the model the cleanup probe is patterned after.

## Pointers

- **`operator-library.md`** — library files migration runbook (Phase 7c → 11,
  prod cutover at Phase 9). Read end-to-end before Phase 9.
- **`operator-cleanup.md`** — cleanup runbook (Phase A → G). Phase D2 is the
  sandbox probe; Phase F has the join-key guard.
- **`library_runner_plan.md`** — architectural decisions for library_files.
- **`cleanup_runner_plan.md`** — architectural decisions for cleanup.
- **`pyproject.toml`** — uv-managed deps. ModuleNotFoundError on `uv run` →
  the missing module is not listed here.

## Troubleshooting

**`uv run` complains about Python version** → project pins `>=3.11,<3.14` in
`pyproject.toml`. Install Python 3.12 via winget.

**`HUBSPOT_*_TOKEN is not set`** → `.env.icalps` not found by `find_dotenv`'s
walk-up. Confirm it sits at the Codebase root, not inside a worktree.

**`psql: command not found`** → `winget install PostgreSQL.psqltools`.

**Branch confusion** → `git worktree list` shows the mapping. Oh My Posh
shows the active branch in the prompt.

**Lost track of state** → `git status` per worktree, or
`git log --oneline --all --decorate --graph -20` for the full picture.
