# ADR-003: Keep movie facts separate from links and credits

**Status:** Accepted · **Date:** 2026-11-20 · **Deciders:** StreamVault lab analyst

## Context

A TMDB movie response contains film facts plus lists of genres, companies, and credits. Putting them all in the same table would repeat the film's budget, gross, and votes. [Finding F09](../02_findings.md) · [Notebook 01](../../notebooks/01_validate_normalization.ipynb)

## Decision

Build the analytical tables in memory. Keep one row per movie ID for film facts, including its optional collection ID. Store entity details once per ID, film-to-entity links separately, and cast and crew at the credit level. Check join cardinality, which means checking how many records each key may match. Summarize links to one row per film before joining them into a film-level calculation. [Normalizer](../../src/streamvault/normalize.py) · [Diagnostics](../../src/streamvault/diagnostics.py)

## Alternatives considered

- **Flatten all repeating fields into one table.** This is easy to browse, but combining genres and credits can multiply rows and inflate totals.
- **Persist the normalized tables in a database.** This would support independent queries, but adds storage and refresh steps to a job that already runs within the measured laptop workload.

## Consequences

Film totals stay at one row per movie. Genre and talent analyses can still use their own levels of detail. The extra tables require explicit joins and checks. The pipeline keeps the original field types because compact types barely changed peak memory at 500 test titles. [Benchmarks](../05_benchmarks.md)

## Revisit when

The tables become too large for a laptop or other jobs need to query them without rebuilding them from the saved responses.
