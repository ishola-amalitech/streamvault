# ADR-001: Use one recommendation engine for the command, notebook, and app

**Status:** Accepted · **Date:** 2026-11-20 · **Deciders:** StreamVault lab analyst

## Context

Adjoa needs one command or browser upload to run the quarterly review. Notebook 04 needs to show how the recommendation was reached using saved evidence. The same inputs and settings should lead to the same decision in all three places. [Lab brief](../../lab_brief.md) · [Run instructions](../../README.md#run-the-pipeline)

## Decision

Put input checks, both release-window analyses, and report writing in the Python package. The command and app use the same pipeline runner, which acquires missing data before calling the recommendation engine. Notebook 04 calls the engine with local inputs and writes to its own report folder. Each entry point saves a run record with input and report fingerprints, settings, and results. [Pipeline runner](../../src/streamvault/main.py) · [Recommendation engine](../../src/streamvault/recommendation_run.py) · [Notebook 04](../../notebooks/04_recommendation.ipynb)

## Alternatives considered

- **Keep separate implementations.** Each interface could change independently, but a fix in one could leave the others giving different shortlists.
- **Make the notebook the pipeline.** Executing the notebook would reuse its cells, but running the quarterly job would then depend on notebook tools and cell order.

## Consequences

A scoring change applies everywhere through the package. The notebook can still show exploratory work. The run record identifies the inputs used. Reproducing a past run also requires keeping those inputs and the corresponding code.

## Revisit when

The quarterly review grows into several dependent jobs that need separate schedules, retries, or deployments.
