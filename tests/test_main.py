import unittest
from unittest.mock import AsyncMock, patch

from streamvault.load import MovieId
from streamvault.main import run


class MainTests(unittest.IsolatedAsyncioTestCase):
    async def test_cached_movie_ids_do_not_trigger_a_fetch(self) -> None:
        with (
            patch(
                "streamvault.main.iter_movie_ids",
                return_value=[MovieId("155", 1)],
            ),
            patch(
                "streamvault.main.load_cached_records",
                return_value={"155": {"id": 155}},
            ),
            patch("streamvault.main.fetch_movies", new_callable=AsyncMock) as fetch,
            patch("streamvault.main.write_cached_records") as write_cache,
        ):
            await run()

        fetch.assert_not_awaited()
        write_cache.assert_called_once()


if __name__ == "__main__":
    unittest.main()
