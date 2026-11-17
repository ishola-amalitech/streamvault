import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from streamvault.fetch_movies import fetch_movies
from streamvault.load import MovieId


class FetchMoviesTests(unittest.IsolatedAsyncioTestCase):
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
            patch("streamvault.fetch_movies.REQUESTS_PER_SECOND", 100.0),
        ):
            records, missing, failures = await fetch_movies(
                [MovieId("155", 2), MovieId("165", 3)]
            )

        self.assertEqual(records, [])
        self.assertEqual([item.movie_id for item in missing], ["155", "165"])
        self.assertEqual(failures, [])
        removals = list(append_removals.call_args.args[1])
        self.assertEqual([item.source_line for item in removals], [2, 3])
        self.assertTrue(all("HTTP 404" in item.reason for item in removals))


if __name__ == "__main__":
    unittest.main()
