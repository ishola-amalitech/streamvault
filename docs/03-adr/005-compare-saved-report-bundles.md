# ADR-005: Compare saved report bundles across quarters

**Status:** Accepted · **Date:** 2026-11-20 · **Deciders:** StreamVault lab analyst

## Context

Adjoa wants to see what changed between two reviews. Rerunning an older list against today's cache or scoring rules could change the old answer. The browser app already gives her a download to keep after each run. [Improvement beyond the brief](../06_beyond_the_brief.md)

## Decision

Compare the saved rankings workbook and run record from each app download. Check that the workbook fingerprint matches the run record and match films by movie ID and bundles by collection ID within each window. Show both saved conclusions and the candidates that entered, left, or moved on a shortlist. [App](../../app.py) · [Comparison instructions](../../README.md#compare-two-saved-reviews)

## Alternatives considered

- **Rerun both CSVs using the current cache and settings.** This answers how the lists would compare today, but can replace the evidence Adjoa actually used.
- **Compare the written summaries.** This is easy to start, but title changes and prose edits make it harder to track rank changes reliably.

## Consequences

Comparison needs no TMDB requests. Adjoa must keep both downloads. The workbook check catches mismatches between the two files. The saved rank changes show what moved, while explaining why may require checking the inputs and settings.

## Revisit when

Adjoa needs a central history of reviews, or a separate comparison that holds the data and scoring rules constant to explain what drove a change.
