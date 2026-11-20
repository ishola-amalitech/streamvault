import asyncio
import math
import os
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from itertools import chain
from typing import cast

import httpx

from streamvault.config import CONFIG, AppConfig
from streamvault.load import MovieId
from streamvault.removals import Removal, append_removals


@dataclass(frozen=True)
class FetchFailure:
    movie_id: str
    message: str


@dataclass(frozen=True)
class FetchMissing:
    movie_id: str
    source_line: int
    reason: str


class RequestRateLimiter:
    def __init__(self, requests_per_second: float) -> None:
        self._interval = 1 / requests_per_second
        self._lock = asyncio.Lock()
        self._next_request_at = 0.0

    async def wait(self) -> None:
        loop = asyncio.get_running_loop()
        # Reserve one start time per request, then let other workers reserve theirs.
        async with self._lock:
            now = loop.time()
            scheduled_at = max(now, self._next_request_at)
            self._next_request_at = scheduled_at + self._interval

        delay = scheduled_at - now
        if delay > 0:
            await asyncio.sleep(delay)


def _retry_after_seconds(value: str | None) -> float | None:
    if value is None:
        return None

    try:
        delay = float(value)
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return None

        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=timezone.utc)
        return max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds())

    return max(0.0, delay) if math.isfinite(delay) else None


def _backoff_seconds(attempt: int, config: AppConfig) -> float:
    return config.retry_base_delay_seconds * (
        config.retry_backoff_multiplier**attempt
    )


async def fetch_movie(
    client: httpx.AsyncClient,
    movie: MovieId,
    rate_limiter: RequestRateLimiter,
    *,
    config: AppConfig = CONFIG,
) -> dict[str, object] | FetchMissing:
    """Request one title and retry temporary failures."""
    movie_id = movie.value
    for attempt in range(config.max_retries + 1):
        await rate_limiter.wait()

        try:
            response = await client.get(
                f"/movie/{movie_id}",
                params={"append_to_response": config.append_to_response},
            )
        except httpx.RequestError:
            if attempt == config.max_retries:
                raise
            await asyncio.sleep(_backoff_seconds(attempt, config))
            continue

        if response.status_code == 404:
            return FetchMissing(
                movie_id, movie.source_line, "TMDB returned HTTP 404."
            )

        if response.status_code == 429 or response.is_server_error:
            if attempt == config.max_retries:
                response.raise_for_status()

            # Use TMDB's requested wait when it supplies one.
            delay = _retry_after_seconds(response.headers.get("Retry-After"))
            await asyncio.sleep(
                delay if delay is not None else _backoff_seconds(attempt, config)
            )
            continue

        response.raise_for_status()
        if response.status_code == 204 or not response.content.strip():
            return FetchMissing(
                movie_id,
                movie.source_line,
                f"TMDB returned HTTP {response.status_code} with no data.",
            )

        payload: object = response.json()
        if not payload:
            return FetchMissing(
                movie_id, movie.source_line, "TMDB returned an empty movie payload."
            )
        if not isinstance(payload, dict):
            raise ValueError("Expected the movie response to be a JSON object.")

        payload_dict = cast(dict[object, object], payload)
        if any(not isinstance(key, str) for key in payload_dict):
            raise ValueError("Movie response object keys must be strings.")
        return cast(dict[str, object], payload_dict)

    raise RuntimeError("Movie request retry loop exited unexpectedly.")


async def _fetch_movies_with_client(
    movie_ids: Iterable[MovieId],
    client: httpx.AsyncClient,
    config: AppConfig,
) -> tuple[list[dict[str, object]], list[FetchMissing], list[FetchFailure]]:
    rate_limiter = RequestRateLimiter(config.requests_per_second)
    # Limit how many requests are queued while the workers are busy.
    queue: asyncio.Queue[tuple[int, MovieId] | None] = asyncio.Queue(
        maxsize=config.max_connections * 2
    )
    outcomes: list[
        dict[str, object] | FetchMissing | FetchFailure | None
    ] = []

    async def worker() -> None:
        while True:
            item = await queue.get()
            if item is None:
                return

            # Use the input position so the output order stays stable.
            index, movie = item
            try:
                outcomes[index] = await fetch_movie(client, movie, rate_limiter, config=config)
            except httpx.HTTPStatusError as error:
                outcomes[index] = FetchFailure(
                    movie.value, f"HTTP {error.response.status_code}"
                )
            except httpx.RequestError as error:
                outcomes[index] = FetchFailure(
                    movie.value, f"Network error ({type(error).__name__})"
                )
            except ValueError as error:
                outcomes[index] = FetchFailure(
                    movie.value, f"Invalid movie response: {error}"
                )

    async with asyncio.TaskGroup() as task_group:
        for _ in range(config.max_connections):
            task_group.create_task(worker())

        for index, movie_id in enumerate(movie_ids):
            outcomes.append(None)
            await queue.put((index, movie_id))

        # One stop message per worker. The task group waits for them all to finish.
        for _ in range(config.max_connections):
            await queue.put(None)

    records: list[dict[str, object]] = []
    missing: list[FetchMissing] = []
    failures: list[FetchFailure] = []

    for outcome in outcomes:
        if isinstance(outcome, FetchMissing):
            missing.append(outcome)
        elif isinstance(outcome, FetchFailure):
            failures.append(outcome)
        elif outcome is None:
            raise RuntimeError("A movie request did not produce a result.")
        else:
            records.append(outcome)

    return records, missing, failures


class MissingTokenError(OSError):
    """A download requires a TMDB read access token."""


async def fetch_movies(
    movie_ids: Iterable[MovieId],
    *,
    config: AppConfig = CONFIG,
) -> tuple[list[dict[str, object]], list[FetchMissing], list[FetchFailure]]:
    """Fetch a batch and return movies, lookup misses, and request failures."""
    # Check for an empty input without consuming the whole iterable.
    movie_iterator = iter(movie_ids)
    first_movie_id = next(movie_iterator, None)
    if first_movie_id is None:
        return [], [], []

    movie_ids = chain((first_movie_id,), movie_iterator)

    read_token = os.getenv(config.token_env_var)
    if not read_token:
        raise MissingTokenError(
            f"{config.token_env_var} environment variable is not set."
        )

    headers = {
        "Authorization": f"Bearer {read_token}",
        "accept": "application/json",
    }
    limits = httpx.Limits(
        max_connections=config.max_connections,
        max_keepalive_connections=config.max_connections,
    )

    # All workers share one client so they can reuse connections.
    async with httpx.AsyncClient(
        base_url=config.api_base_url,
        headers=headers,
        timeout=httpx.Timeout(
            config.request_timeout_seconds,
            connect=config.connect_timeout_seconds,
        ),
        limits=limits,
    ) as client:
        records, missing, failures = await _fetch_movies_with_client(
            movie_ids, client, config
        )

    # Log misses against this run's list, including lists uploaded through the app.
    append_removals(
        config.removals_file,
        (
            Removal(
                config.source_file.name,
                item.source_line,
                item.movie_id,
                f"TMDB lookup: {item.reason}",
            )
            for item in missing
        ),
    )
    return records, missing, failures
