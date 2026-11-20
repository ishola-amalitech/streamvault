# Benchmarks

Adjoa expects about 500 candidate titles. Two benchmarks tested whether the saved-data analysis scales to that size and whether smaller field types(downcasting and encoding) reduce memory use enough to be worthwhile. The figures below come from the benchmark runs recorded in [decision D04](DECISIONS.md#d04--keep-the-canonical-types-and-measure-runtime-separately).

## Cached runtime at 500 titles

| Measurement | Time |
| --- | ---: |
| Measured on the 112-film snapshot | 1.54 s |
| Projected for 500 titles at the same time per title | 6.89 s |
| Measured on 500 cached test titles | 3.55 s |

The script builds a 500-title test cache using the shapes of the 112 saved movie records, with distinct test IDs. It times reading the saved inputs through writing the reports and checking their file fingerprints. Fetching from TMDB, building the test cache, and writing the final run record are outside the timer. The output records the time for each stage as well as the total. A future list may have a different mix of collections, credits, and missing records. Treat the measured time as a test on this laptop. [Runtime benchmark script](../scripts/benchmark_recommendation.py)

## Effect of smaller field types

| Measure at 500 cached test titles | Original types | Compact types |
| --- | ---: | ---: |
| Movie table memory | 571.7 KiB | 509.9 KiB |
| Peak memory for the analysis process | 395.7 MiB | 396.1 MiB |
| Cached analysis time | 3.57 s | 3.60 s |

Each value is the median of three runs in fresh processes per version. The compact version keeps the original movie and collection ID sizes. It uses smaller types for budget, gross, runtime and vote counts where the values fit, and stores repeated status and language labels more efficiently. Peak memory includes imports. The script checks that both versions preserve the movie values, joins, shortlists, and report contents. The compact version saved 61.8 KiB in the movie table, with little change in the whole process. The pipeline keeps the original types. [Memory benchmark script](../scripts/benchmark_movie_types.py) · [Finding F14](findings.md)

## Rerun the benchmarks

Run from the project root with a populated movie cache. The memory benchmark runs on Linux or macOS. Times and memory use can vary by machine and run.

```sh
uv run --locked python scripts/benchmark_recommendation.py
uv run --locked python scripts/benchmark_movie_types.py
```

The scripts save `out/benchmark.json` and `out/movie_types_benchmark.json` by default. For Docker, use the [README's test command](../README.md#test-the-pipeline) and replace `python -m unittest discover -s tests` with `python scripts/benchmark_recommendation.py` or `python scripts/benchmark_movie_types.py`.
