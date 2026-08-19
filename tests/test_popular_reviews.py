"""Tests for src/reviewing/popular_reviews.py."""

from unittest.mock import MagicMock, PropertyMock

from src.reviewing.popular_reviews import fetch_popular_reviews, parse_like_count


class TestParseLikeCount:
    def test_parses_comma_grouped_count(self):
        assert parse_like_count("Like review\n27,695 likes") == 27695

    def test_parses_singular(self):
        assert parse_like_count("1 like") == 1

    def test_no_count_is_zero(self):
        assert parse_like_count("Like review") == 0


class TestFetchPopularReviews:
    def _page(self, raw, url="https://letterboxd.com/film/test-film/"):
        page = MagicMock()
        type(page).url = PropertyMock(return_value=url)
        page.evaluate.return_value = raw
        return page

    def test_filters_short_meme_reviews(self):
        substantive = "x" * 200
        page = self._page(
            [
                {"text": "this movie INVENTED the color red", "likeLabel": "15,306 likes"},
                {"text": substantive, "likeLabel": "27,695 likes"},
            ]
        )
        result = fetch_popular_reviews(page, "https://boxd.it/abc")
        assert len(result) == 1
        assert result[0]["likes"] == 27695

    def test_skips_spoiler_shields_and_truncates(self):
        page = self._page(
            [
                {"text": "This review may contain spoilers. " + "y" * 300, "likeLabel": "9 likes"},
                {"text": "z" * 900, "likeLabel": "5 likes"},
            ]
        )
        result = fetch_popular_reviews(page, "https://boxd.it/abc")
        assert len(result) == 1
        assert len(result[0]["text"]) == 700

    def test_non_film_redirect_returns_empty(self):
        page = self._page([], url="https://letterboxd.com/some-other-page/")
        assert fetch_popular_reviews(page, "https://boxd.it/abc") == []

    def test_respects_count(self):
        page = self._page([{"text": "w" * 200, "likeLabel": f"{i} likes"} for i in range(6)])
        assert len(fetch_popular_reviews(page, "https://boxd.it/abc", count=2)) == 2
