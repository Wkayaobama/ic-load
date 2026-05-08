# operator-scaffold.md — entry point for the IC'ALPS operator

> Read this first. It tells you where things live and how to run them.
> The two phase-specific runbooks (`operator-library.md`, `operator-cleanup.md`)
> assume you have followed the setup here.

## TL;DR

Three sibling worktrees on disk, one shared `.env.icalps` at the Codebase root,
one shared HubSpot prod token, `uv run` as the only invocation pattern.

```
C:\Users\ayaobama\Documents\AnthonySalesOps\Codebase\
├── .env.icalps                       ← canonical secrets (NEVER commit)
├── ic-load-jl-selective-changes\     ← branch: library-files-cleanup-prod
├── ic-load-library-prod\             ← branch: library-files-rest-sandbox-prod
└── ic-load-jl-merge\                 ← branch: w/jl-merge-main (legacy)
```

Daily loop:
```powershell
cd <worktree>                                              # the only context-switch step
uv run python -m pipeline.<library_files|cleanup>.runner ...
```

That's it. No venv activation. No `pip install`. uv handles `.venv/` per
worktree transparently.

---

## One-time setup

### 1. Install uv (if missing)

```powershell
winget install --id=astral-sh.uv
```

### 2. Install Oh My Posh (visual layer for branch awareness)

```powershell
winget install JanDeDobbeleer.OhMyPosh --source winget
oh-my-posh font install CaskaydiaMono
```

In Windows Terminal → Settings → PowerShell profile → Appearance → Font face,
choose **CaskaydiaMono Nerd Font**.

Open `$PROFILE` in Notepad (`notepad $PROFILE`; create if it doesn't exist
with `New-Item -Path $PROFILE -Type File -Force`) and append:

```powershell
oh-my-posh init pwsh --config "$env:POSH_THEMES_PATH\jandedobbeleer.omp.json" | Invoke-Expression
```

Reload with `. $PROFILE`. From then on every prompt shows the directory and
the active git branch — visual answer to "where am I, which branch?"

### 3. Create the worktrees (if not already in place)

From any existing checkout:
```powershell
git worktree list   # shows what already exists
```

Expected three lines once setup is complete. If `ic-load-library-prod` is
missing, create it:
```powershell
git worktree add `
    "C:\Users\ayaobama\Documents\AnthonySalesOps\Codebase\ic-load-library-prod" `
    library-files-rest-sandbox-prod
```

### 4. Populate `.env.icalps` at the Codebase root

```powershell
copy .env.icalps.example `
    "C:\Users\ayaobama\Documents\AnthonySalesOps\Codebase\.env.icalps"
notepad "C:\Users\ayaobama\Documents\AnthonySalesOps\Codebase\.env.icalps"
```

Fill in the real values (sandbox token, prod token, postgres DSN, library
base dir). Save. The file is gitignored at every level — never commit it.

Verify env loads from any worktree:
```powershell
cd C:\Users\ayaobama\Documents\AnthonySalesOps\Codebase\ic-load-library-prod
uv run python -c "from pipeline.library_files.config import Settings; s = Settings.from_env(); print('dsn=', s.prod_postgres_dsn[:40], '...'); print('token len=', len(s.hubspot_token))"
```

Expected: truncated DSN + non-zero token length. If you get
`RuntimeError: HUBSPOT_SANDBOX_TOKEN is not set`, the file isn't where uv's
walk-up can find it — confirm it sits at the parent (Codebase) directory, not
inside a worktree.

---

## Which worktree do I use for what?

| Task | Worktree | Branch |
|---|---|---|
| Library files migration (Phase 7c → 11) | `ic-load-library-prod` | `library-files-rest-sandbox-prod` |
| Stale-record cleanup (Phase A → G) | `ic-load-jl-selective-changes` | `library-files-cleanup-prod` |

Both branches share the same `pipeline/library_files/` code; the cleanup
branch additionally has `pipeline/cleanup/`. The cleanup branch was forked
off the library branch, so commits to library-files-rest-sandbox-prod can
later merge into library-files-cleanup-prod cleanly.

To switch worktrees, just `cd`. Each worktree's `git status` is independent.
A branch can only be checked out in one worktree at a time, which is the
property that prevents accidental conflicts.

---

## Approval gates (session-level only)

Never put these in `.env.icalps` or any other durable file. They are toggles
you set right before each gated run, and unset after.

| Variable | Purpose | Phase |
|---|---|---|
| `ICALPS_APPROVE_FILES_UPLOAD` | library Phase 1 (file upload) | 7c step 5+, 9, 10 |
| `ICALPS_APPROVE_FILE_NOTES_POST` | library Phase 2 (note + assoc) | 7c step 6+, 9, 10 |
| `ICALPS_APPROVE_ARCHIVE` | cleanup Phase E (batch archive) | E |
| `ICALPS_APPROVE_GDPR_DELETE` | cleanup Phase E2 (irreversible contact purge) | E2 |
| `ICALPS_APPROVE_PROP_DELETE` | cleanup Phase F (irreversible schema deletion) | F |

Pattern:
```powershell
$env:ICALPS_APPROVE_ARCHIVE = "1"
uv run python -m pipeline.cleanup.runner archive --object deals
Remove-Item env:ICALPS_APPROVE_ARCHIVE
```

Default for every gate is unset = DRY-RUN. The runner prints a banner at the
top of each run showing exactly which gates are LIVE vs DRY.

---

## Pointers

- **`operator-library.md`** — library files migration runbook (Phase 7c
  through 11, including prod cutover at Phase 9). Read end-to-end before
  attempting Phase 9.
- **`operator-cleanup.md`** — stale-record cleanup runbook (Phase A snapshot
  through Phase F property deletion). Read the join-key guard section before
  Phase F.
- **`library_runner_plan.md`** — architectural decisions for library_files.
- **`cleanup_runner_plan.md`** — architectural decisions for cleanup.
- **`pyproject.toml`** — uv-managed deps. If a `uv run` invocation fails with
  a `ModuleNotFoundError`, check that the missing module is listed here.

---

## Common troubleshooting

**`uv run` complains about Python version:** the project pins `>=3.11,<3.14`
in `pyproject.toml`. Install Python 3.12 via winget if needed.

**`HUBSPOT_*_TOKEN is not set`:** `.env.icalps` not found by `find_dotenv`'s
walk-up. Confirm the file is at the Codebase root, not inside a worktree.
Worktree-local `.env` also works as override if you need to deviate.

**`psql: command not found`:** install postgres client tools. `winget install
PostgreSQL.psqltools` or any equivalent.

**Branch confusion:** `git worktree list` shows which branch is checked out
where. Oh My Posh shows it in the prompt. Never edit on the wrong branch —
your working tree changes are attached to whatever branch is currently checked
out in *this* worktree.

**Lost track of what's where:** `git status` in each worktree, `git log
--oneline --all --decorate --graph -20` for the full picture.
