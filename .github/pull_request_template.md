## Why

<!-- The failure or requirement that motivated this change. Not what the diff shows —
     the reviewer can read the diff. See CONTRIBUTING.md "Commits". -->

## What changed

<!-- One line per behaviour change. Say which layer: router / service / repository /
     model / prompt. A prompt change is a behaviour change (backend/ai/prompts.py). -->

## How it was verified

<!-- Which tests cover it, and anything you checked by hand that tests cannot. -->

- [ ] `ruff check backend/ tests/ eval/`
- [ ] `ruff format --check backend/ tests/ eval/`
- [ ] `mypy backend/`
- [ ] `pytest tests/ -q` (with `--cov=backend --cov-fail-under=70` if this PR moves coverage)

## Risk surface

Tick anything this PR touches — these are the paths CONTRIBUTING.md flags as needing
care, and a tick tells the reviewer where to spend their attention.

- [ ] **HITL gate** — a path that can put an answer in front of a customer
- [ ] **RBAC in retrieval** — Qdrant payload filters / visibility
- [ ] **Semantic cache** — anything question-specific must not be cached
- [ ] **Prompts** (`backend/ai/prompts.py`) — what a Sale reads out to a customer
- [ ] **Migrations** — a new revision under `migrations/versions/`
- [ ] None of the above
