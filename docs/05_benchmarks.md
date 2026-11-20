# Benchmarks

Adjoa expects about 500 candidate titles. Two benchmarks tested whether the saved-data analysis scales to that size and whether smaller field types reduce memory use enough to be worthwhile. The pipeline keeps the original types. [Data model ADR](03-adr/003-separate-films-links-and-credits.md)

## Cached runtime at 500 titles

| Measurement | Time |
| --- | ---: |
| Measured on the 112-film snapshot | 1.54 s |
| Projected for 500 titles at the same time per title | 6.89 s |
| Measured on 500 cached test titles | 3.55 s |

The script builds a 500-title test cache using the shapes of the 112 saved movie records, with distinct test IDs. It times reading the saved inputs through writing the reports and checking their file fingerprints. Fetching from TMDB, building the test cache, and writing the final run record are outside the timer. The output records the time for each stage as well as the total. A future list may have a different mix of collections, credits, and missing records. Treat the measured time as a test on this laptop. The brief gives a 500-title workload and a meeting-use scenario. It gives no numerical time limit, so the measured time describes the workload this laptop handled. [Runtime benchmark script](../scripts/benchmark_recommendation.py)

## Effect of smaller field types

| Measure at 500 cached test titles | Original types | Compact types |
| --- | ---: | ---: |
| Movie table memory | 571.7 KiB | 509.9 KiB |
| Peak memory for the analysis process | 395.7 MiB | 396.1 MiB |
| Cached analysis time | 3.57 s | 3.60 s |

Each value is the median of three runs in fresh processes per version. The compact version keeps the original movie and collection ID sizes. It uses smaller types for budget, gross, runtime and vote counts where the values fit, and stores repeated status and language labels more efficiently. An early version narrowed collection IDs too far. This mattered because the talent analysis uses movie IDs where a collection ID is missing, and a movie ID can exceed the smaller limit. Peak memory includes imports. The script checks that both versions preserve the movie values, joins, shortlists, and report contents. The compact version saved 61.8 KiB in the movie table, with little change in the whole process. The pipeline keeps the original types. [Memory benchmark script](../scripts/benchmark_movie_types.py) · [Finding F14](02_findings.md)

## Repeat check with the rankings workbook

After switching to the workbook, the cached analysis took 1.67 seconds for 112 films. That projected to 7.44 seconds for 500 films. The measured run for 500 test films took **3.75 seconds**. In the separate memory test, the compact movie table used 308.7 KiB versus 330.6 KiB for the original. Peak memory stayed near 479 MiB and both versions gave identical reports. [Pipeline outputs](../README.md#pipeline-outputs)

## Rerun the benchmarks

Run from the project root with a populated movie cache. The memory benchmark runs on Linux or macOS. Times and memory use can vary by machine and run.

```sh
uv run --locked python scripts/benchmark_recommendation.py
uv run --locked python scripts/benchmark_movie_types.py
```

The scripts save the pipeline's benchmark reports under `out/benchmarks/`. To run separate measurements for Notebook 04, add `--notebook` to either command.

```sh
uv run --locked python scripts/benchmark_recommendation.py --notebook
uv run --locked python scripts/benchmark_movie_types.py --notebook
```

These commands write `benchmark.json` and `movie_types_benchmark.json` under `data/recommendation-report/benchmark/`. The notebook uses the shared cached analysis and reads the saved runtime from that folder. Each ordinary run records its own timing in its `run.json`. For Docker, use the [README's test command](../README.md#test-the-pipeline) and replace `python -m unittest discover -s tests` with the corresponding `python scripts/...` command above.
