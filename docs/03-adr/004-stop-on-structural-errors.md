# ADR-004: Stop on structural errors and report gaps by measure

**Status:** Accepted · **Date:** 2026-11-20 · **Deciders:** StreamVault lab analyst

## Context

A broken join or a repeated cache ID can corrupt the count of films. Other gaps affect only certain results. For example, a missing budget leaves a film's audience rating usable. Adjoa needs to see which evidence was withheld and why. [Findings](../02_findings.md) · [Question Q10](../03_questions.md)

## Decision

Stop on broken joins, repeated cache entries for a current candidate, or an uncached candidate with no recorded outcome. For film-level gaps, record the reason in the exclusions report and withhold the affected measure. Keep possible duplicates identified by title and year visible for review, and mark affected windows provisional. [Recommendation inputs](../../src/streamvault/recommendation_inputs.py) · [Financial checks](../../src/streamvault/movie_quality.py) · [Exclusions report guide](../../README.md#review-the-evidence-before-using-the-shortlists)

## Alternatives considered

- **Stop on any missing or suspicious field.** This would block sound results whenever an unrelated field is missing.
- **Fill gaps with zero or drop the films silently.** This would hide the lost evidence and could change either shortlist.

## Consequences

Adjoa can use the remaining evidence and see where it became thinner. Different measures may cover different numbers of films. A possible duplicate still needs human review, since matching title and year alone cannot establish that two records describe the same film.

## Revisit when

Recurring source problems create provisional results that Adjoa cannot resolve, or new measures depend on fields that are currently optional.
