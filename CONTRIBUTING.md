# Contributing

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # fill in GEMINI_API_KEY and SECRET_KEY
alembic upgrade head          # falls back to SQLite when DATABASE_URL is unset
```

`COHERE_API_KEY` and `REDIS_URL` are optional: without them reranking falls back
to a keyword ranker and long-term memory is skipped. Both degrade quietly, so if
you expect them to be live, check the logs rather than assuming.

On an Intel Mac, `cryptography >= 47` publishes no x86_64 macOS wheel and pip
falls back to a Rust build. Add `-c <(echo "cryptography<47")` to the install.

## Before opening a PR

CI runs these four, and so should you:

```bash
ruff check backend/ tests/ eval/
ruff format --check backend/ tests/ eval/
mypy backend/
pytest tests/ -q --cov=backend --cov-fail-under=70
```

`pytest tests/` needs no infrastructure — the suite is hermetic. A real
`COHERE_API_KEY` or `REDIS_URL` in your `.env` is neutralised by a fixture in
`tests/conftest.py`, so no test makes a billed API call, and `_no_live_qdrant`
does the same for the vector store. The exception is `tests/test_e2e`, which
skips itself unless a backend is live on port 8000.

The coverage gate is the same number CI enforces, and it is a floor rather than a
target: a PR that adds a service and no test for it will trip it. If you need to
see what is uncovered, `--cov-report=term-missing` prints the line numbers.

## Review

No branch is pushed to directly. Work happens on a `feature/*` branch, arrives as a PR
into `develop`, and reaches `main` only through a release PR.

Every PR needs one approving review from a maintainer who is not its author.
`.github/CODEOWNERS` requests that review automatically; branch protection on `main` and
`develop` is what makes it binding, together with the CI checks below as required status
checks:

- `lint-and-test / Lint with ruff`
- `lint-and-test / Type-check with mypy`
- `lint-and-test / Run tests` — includes the `--cov-fail-under` coverage gate
- `lint-and-test / Golden RAG regression gate`

The PR description follows `.github/pull_request_template.md`. Its risk-surface
checklist is the part reviewers read first: it says which of the paths under
[What needs care](#what-needs-care) the change touches, so review attention lands where
a mistake is expensive rather than being spread evenly over the diff.

As a reviewer, the questions worth asking are: does the *Why* describe a real failure or
requirement; is a behaviour change covered by a test that would have failed before it;
and does a ticked risk box have a test proving the guarantee still holds.

## Comments

This codebase comments the *why*, not the *what*. Many comments record a bug that
was actually hit and the reason the code is shaped the way it is — deleting one
invites the bug back. If you change the behaviour a comment explains, update the
comment in the same commit; if you find a comment that only restates its code,
that one is worth removing.

## What needs care

- **The HITL gate.** Any path that can put an answer in front of a customer must
  run `risk_service` on the text that is actually shown. See `SECURITY.md`.
- **RBAC in retrieval.** The Qdrant payload filter is the second of two layers,
  not a convenience. Tests assert no `internal` chunk reaches a `public` asker.
- **The semantic cache.** It matches on meaning, so anything question-specific —
  images, unit listings, a follow-up resolved against one session's history —
  must not be cached, or it will be replayed under a different question.
- **Prompts are production code.** `backend/ai/prompts.py` decides what a Sale
  reads out to a customer; treat a wording change as a reviewable behaviour change.

## Commits

Explain why the change is needed, not what the diff shows. Reference the failure
or requirement that motivated it.
