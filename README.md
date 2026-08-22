# Vishwas AI — Phase 1 Compliance Engine

The coded version of the "Audit Checklist" spreadsheet's rule logic. Given
structured details about one post, it decides COMPLIANT / FLAGGED / PENDING
REVIEW against ASCI/CCPA disclosure rules, and — the whole point of this
project — explains *why*, in plain language, for every flag.

This is deliberately just the rule-checking core. It does not fetch posts
from Instagram/YouTube (that's FR1 from the PRD, still to build) and it
does not have a UI (FR5). It's the brain — the thing both of those will
eventually call.

## Quick start

```bash
python3 demo.py          # see it run on five sample posts
python3 -m pytest tests/ -v   # run the test suite (12 tests, all passing)
```

## How it works

```python
from vishwas_compliance import PostInput, audit_post

post = PostInput(
    platform="Instagram",
    content_type="static_post",       # static_post / reel_story / video / youtube_short / audio_podcast
    material_connection="paid",       # paid / gifted_barter / affiliate / family_business / none_genuine
    caption="#ad Loving this new serum!",
)

result = audit_post(post)
print(result.status)        # COMPLIANT / FLAGGED / PENDING REVIEW
print(result.summary())     # human-readable explanation of every issue
```

For video, Stories, virtual influencers, and health/finance claims, pass
the extra fields the check needs (see `PostInput` in `engine.py` — each
one is commented with what it's for). **Leave a field as `None` if it
hasn't been reviewed yet** — the engine marks that specific check PENDING
REVIEW rather than guessing. It only ever calls something FLAGGED when a
human has actually confirmed a problem.

## What each check means

Same rules as the spreadsheet's "Rules Reference" tab, now in
`vishwas_compliance/rules.py` as real constants instead of a table a human
reads. If ASCI updates its guidance, that file — plus `APPROVED_LABELS` /
`AMBIGUOUS_LABELS` in particular — is the one place to update it.

## Exporting to the spreadsheet

```python
result.to_checklist_row()
```

returns a dict with the exact same column names as the "Audit Checklist"
tab, so a batch of results can be dropped straight into that spreadsheet
(or turned into a CSV) without retyping anything.

## What's deliberately not here yet

- **Fetching real posts** (Instagram Graph API / YouTube Data API) — FR1.
  Right now you fill in `PostInput` by hand after watching the post, same
  as the spreadsheet.
- **A web form or report generator** — FR5. This is pure logic, callable
  from a script, a notebook, or eventually a web backend.
- **Reviewer Explanation / Recommended Fix** — still a human's job, on
  purpose. This engine tells you *what rule* was broken and *why it counts*
  as a violation; turning that into client-facing advice is a judgment
  call this phase deliberately leaves with you.

## A note on accuracy

The placement and label checks work by reading the actual caption text —
they're real automation, not a rubber stamp. But text parsing has edge
cases; a two-word caption with `#ad` at the very end but nothing else
before it, for instance, will pass the "first 8 words" check even though
a stricter reading might flag it. Treat `COMPLIANT` results the way you'd
treat a first-pass spell-checker: a strong signal, worth spot-checking
against a few real posts before you trust it fully with a paying client.
