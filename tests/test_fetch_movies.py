import asyncio
import os
import unittest
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from streamvault.config import CONFIG
from streamvault.fetch_movies import _fetch_movies_with_client, fetch_movies
from streamvault.load import MovieId


class FetchMoviesTests(unittest.IsolatedAsyncioTestCase):
    async def test_workers_keep_input_order_and_account_for_empty_responses(self) -> None:
        faster_request_finished = asyncio.Event()

        async def respond(request: httpx.Request) -> httpx.Response:
            self.assertTrue(request.url.path.startswith("/3/films/"))
            movie_id = request.url.path.rsplit("/", 1)[-1]
            if movie_id == "1":
                # Make the first request finish after the second one.
                await faster_request_finished.wait()
                return httpx.Response(200, json={"id": 1})
            if movie_id == "2":
                faster_request_finished.set()
                return httpx.Response(200, json={"id": 2})
            return httpx.Response({"3": 204, "4": 200, "5": 401}[movie_id])

        settings = replace(
            CONFIG, movie_endpoint="/films", max_connections=2, requests_per_second=1000.0,
        )
        movie_ids = (MovieId(str(number), number + 1) for number in range(1, 6))
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(respond), base_url=CONFIG.api_base_url
        ) as client:
            records, missing, failures = await asyncio.wait_for(
                _fetch_movies_with_client(movie_ids, client, settings), timeout=5
            )

        self.assertEqual(records, [{"id": 1}, {"id": 2}])
        self.assertEqual(
            [item.reason for item in missing],
            ["TMDB returned HTTP 204 with no data.", "TMDB returned HTTP 200 with no data."],
        )
        self.assertEqual([(item.movie_id, item.message) for item in failures], [("5", "HTTP 401")])

    async def test_each_404_is_recorded_without_failing_the_batch(self) -> None:
        response = httpx.Response(
            404,
            request=httpx.Request("GET", "https://api.themoviedb.org/3/movie/1"),
        )
        client = AsyncMock()
        client.get.side_effect = [response, response]
        client_context = MagicMock()
        client_context.__aenter__ = AsyncMock(return_value=client)
        client_context.__aexit__ = AsyncMock(return_value=None)

        with (
            patch.dict(os.environ, {"TMDB_API_READ_ACCESS_TOKEN": "test-token"}),
            patch(
                "streamvault.fetch_movies.httpx.AsyncClient",
                return_value=client_context,
            ),
            patch("streamvault.fetch_movies.append_removals") as append_removals,
        ):
            records, missing, failures = await fetch_movies(
                [MovieId("155", 2), MovieId("165", 3)],
                config=replace(CONFIG, requests_per_second=100.0, source_file=CONFIG.source_file.with_name("upload.csv")),
            )

        self.assertEqual(records, [])
        self.assertEqual([item.movie_id for item in missing], ["155", "165"])
        self.assertEqual(failures, [])
        removals = list(append_removals.call_args.args[1])
        self.assertEqual([item.source_file for item in removals], ["upload.csv", "upload.csv"])
        self.assertEqual([item.source_line for item in removals], [2, 3])
        self.assertTrue(all("HTTP 404" in item.reason for item in removals))


if __name__ == "__main__":
    unittest.main()
