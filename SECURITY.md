# Security Policy

## Reporting a vulnerability

Please report security issues privately — open a [GitHub security advisory](https://github.com/AI20K-Build-Phase-Cohort-3/P-110/security/advisories/new)
rather than a public issue, so the problem can be fixed before it is described in
the open. Include what you did, what happened, and what you expected.

## Secrets

No credential belongs in the repository. `.env` is gitignored; `.env.example`
holds the variable names with empty values and must stay that way.

A key that has been committed is compromised the moment the branch is pushed —
deleting the file in a later commit does not help, because the value stays in
the history and in every clone. Rotate it at the provider, then remove the file.

Before pushing, check what you are actually about to send:

```bash
git diff --cached                     # read the staged diff
git log -p --all -S 'AIza' | head     # search history for a key prefix
```

## What this system protects

The threat model here is not only the usual web surface — the AI pipeline itself
carries risk that ordinary review misses:

- **Answers touching price or commitments** are gated behind human confirmation
  (`risk_service` + the HITL card). Any change that lets an answer reach a
  customer without that gate is a security change, not a UX one — including
  changes to the cache, which re-runs the gate on the way out.
- **Document visibility** is enforced twice: on the route and again in the Qdrant
  payload filter. Retrieval must never be able to return an `internal` document
  to a `public` asker, regardless of what the route allowed.
- **Uploaded documents are untrusted input.** They are scanned for prompt
  injection before they are chunked and embedded; inventory API fields are
  flattened before reaching a prompt.

## Supported versions

This is coursework built during the AI20K Build Phase (Cohort 3). Only `main`
receives fixes.
