# ADR-002: Cache raw TMDB responses by movie ID and analyze the current list

**Status:** Accepted · **Date:** 2026-11-20 · **Deciders:** StreamVault lab analyst

## Context

Adjoa's quarterly lists can overlap. Downloading every movie again adds time and API traffic, while analyzing the whole cache could include films that have left the list. [Findings F01 and F05](../02_findings.md) · [Lab brief](../../lab_brief.md)

## Decision

Keep one successful raw TMDB response per movie ID in a local JSON Lines file, with a UTC cache timestamp. Replace the file atomically when updating it. Match the current CSV to the cache by ID, reuse successful responses, and request uncached IDs. Record the outcome of each request and keep reasons for source rows the pipeline cannot use. The CLI can replay saved inputs without a token when every uncached ID already has a recorded outcome. [Cache](../../src/streamvault/cache.py) · [Pipeline runner](../../src/streamvault/main.py)

## Alternatives considered

- **Refresh the whole list on each run.** This would give fresher figures at the cost of more requests and a changing source snapshot.
- **Store only cleaned tables.** These would be ready for analysis, but changes to normalization could require a fresh download of fields the tables did not retain.

## Consequences

The pipeline and notebooks can reuse raw responses and limit results to today's candidates. Old candidates remain available for future lists. Ratings and popularity may be stale. New records from the same batch share a cache-write timestamp. A timestamp added to an older record shows when it was stamped. [Question Q05](../03_questions.md)

## Revisit when

The client needs a defined refresh schedule for ratings or several analysts need to write to the same cache.
