"""Driving the diary-entry modal.

These used to live in test_post_review.py, reaching into ReviewPoster for
`open_review_form` and `set_tags`. Both are now DiaryForm's, which is what
the poster, the tagger and the de-duplicator all share.

The page fakes here model the modal *semantically* -- a mutable set of
visible button labels that changes on navigation -- rather than returning a
truthy Mock for every `evaluate`. That is why they constrain the label logic
at all.
"""

from unittest.mock import MagicMock

import pytest

from src.reviewing.diary_form import DiaryForm


class TestOpenReviewForm:
    """Letterboxd labels the diary button five different ways."""

    @staticmethod
    def _page(labels, url="https://letterboxd.com/film/test-film/", after_goto=None):
        """A page offering exactly `labels`, which may change on navigation."""
        page = MagicMock()
        page.url = url
        state = {"labels": set(labels)}

        def evaluate(js, arg=None):
            if arg is None:
                # The duplicate probe takes no argument: it matches any
                # button whose label contains the shared phrase.
                return next((lbl for lbl in state["labels"] if "log again" in lbl), None)
            return next((lbl for lbl in arg if lbl in state["labels"]), None)

        def goto(*_args, **_kwargs):
            if after_goto is not None:
                state["labels"] = set(after_goto)

        page.evaluate.side_effect = evaluate
        page.goto.side_effect = goto
        return page

    def test_unlogged_film_clicks_review_or_log(self):
        page = self._page({"review or log"})
        assert DiaryForm(page, "testuser").open("Test Film") is True
        page.goto.assert_not_called()

    def test_existing_review_is_edited_not_relogged(self):
        """ "Review or log again" contains "review or log" as a substring;
        matching loosely here would add a second diary entry every time a
        review is re-tagged."""
        page = self._page(
            {"review or log again", "edit or delete review"},
            url="https://letterboxd.com/testuser/film/test-film/",
        )
        assert DiaryForm(page, "testuser").open("Test Film") is True
        clicked = page.evaluate.call_args_list[0][0][1]
        assert clicked[0] == "edit or delete review"
        page.goto.assert_not_called()

    @pytest.mark.parametrize(
        "duplicate_label",
        [
            "log again / add review",
            "log again / edit review",
            "review or log again",
            "log again",
        ],
    )
    def test_any_log_again_variant_routes_to_the_entry_page(self, duplicate_label):
        """Letterboxd has shipped at least four wordings of this button.
        Enumerating them exactly missed "log again / edit review" and
        left 27 reviews untagged, so the rule is the shared phrase."""
        page = self._page({duplicate_label}, after_goto={"edit or delete review"})
        assert DiaryForm(page, "testuser").open("Test Film") is True
        page.goto.assert_called_once()
        assert page.goto.call_args[0][0] == "https://letterboxd.com/testuser/film/test-film/"

    def test_no_usable_button_is_failure(self):
        page = self._page(set())
        assert DiaryForm(page, "testuser").open("Test Film") is False


class TestSetTags:
    """The tag typeahead tokenizes as you type, and can race."""

    @staticmethod
    def _page(tokens_after_typing):
        page = MagicMock()
        page.locator.return_value.first.count.return_value = 1
        page.evaluate.side_effect = lambda js, *a: (
            tokens_after_typing if "name=tag]" in js or "name=tag'" in js else None
        )
        return page

    def test_returns_tokens_that_stuck(self):
        page = self._page(["minimal-dialogue", "mortality"])
        assert DiaryForm(page, "testuser").set_tags(["minimal-dialogue", "mortality"]) == [
            "minimal-dialogue",
            "mortality",
        ]

    def test_drops_a_truncated_token_from_a_typeahead_race(self):
        """A half-typed token like 'tearjer' once shipped to the account
        this way; anything not asked for is removed before saving."""
        page = self._page(["mortality", "minimal-dialog", "minimal-dialogue"])
        assert DiaryForm(page, "testuser").set_tags(["mortality", "minimal-dialogue"]) == [
            "mortality",
            "minimal-dialogue",
        ]

    def test_a_tag_outside_the_vocabulary_never_reaches_the_account(self):
        """The taxonomy guarantee used to hold on only one of the two paths
        that write tags: the tagger validated, the poster did not."""
        page = self._page(["grief"])
        assert DiaryForm(page, "testuser").set_tags(["not-a-real-tag"]) == []

    def test_an_alias_is_resolved_before_it_is_typed(self):
        page = self._page(["hilarious"])
        assert DiaryForm(page, "testuser").set_tags(["comedy"]) == ["hilarious"]

    def test_no_tags_is_a_noop(self):
        page = self._page([])
        assert DiaryForm(page, "testuser").set_tags([]) == []
        page.locator.assert_not_called()

    def test_missing_field_returns_empty(self):
        page = MagicMock()
        page.locator.return_value.first.count.return_value = 0
        assert DiaryForm(page, "testuser").set_tags(["grief"]) == []
