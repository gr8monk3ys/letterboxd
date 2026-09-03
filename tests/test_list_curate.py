"""Tests for src/lists/curate.py - editing list tags and descriptions."""

import json
from unittest.mock import MagicMock

import pytest

from src.lists.curate import ListCurator, load_plan


class TestLoadPlan:
    def test_reads_slug_keyed_entries(self, tmp_path):
        path = tmp_path / "plan.json"
        path.write_text(json.dumps({"my-list": {"tags": ["grief"], "description": "hi"}}))
        plan = load_plan(path)
        assert plan["my-list"]["tags"] == ["grief"]

    def test_missing_file_is_an_error_not_an_empty_plan(self, tmp_path):
        """Silently curating nothing looks identical to success."""
        with pytest.raises(FileNotFoundError):
            load_plan(tmp_path / "nope.json")

    def test_rejects_tags_outside_the_vocabulary(self, tmp_path):
        """A junk tag in the plan is a typo, and shipping it would put a
        one-use tag on the account, which is the thing the vocabulary
        exists to prevent."""
        path = tmp_path / "plan.json"
        path.write_text(json.dumps({"my-list": {"tags": ["grief", "made-up"]}}))
        with pytest.raises(ValueError, match="made-up"):
            load_plan(path)

    def test_accepts_list_only_tags(self, tmp_path):
        path = tmp_path / "plan.json"
        path.write_text(json.dumps({"my-list": {"tags": ["ranked", "director-study"]}}))
        assert load_plan(path)["my-list"]["tags"] == ["ranked", "director-study"]


class TestListCurator:
    def _curator(self, current_tags=None, current_desc="", saved_tags=None, saved_desc=None):
        page = MagicMock()
        state = {
            "tags": list(current_tags or []),
            "desc": current_desc,
            "saved": False,
        }

        def evaluate(js, arg=None):
            if "requestSubmit" in js:
                state["saved"] = True
                if saved_tags is not None:
                    state["tags"] = list(saved_tags)
                if saved_desc is not None:
                    state["desc"] = saved_desc
                return True
            if "name=tag]" in js:
                return list(state["tags"])
            if "notes" in js and arg is None:
                return state["desc"]
            if arg is not None:
                # applying the new tags/description
                if isinstance(arg, list):
                    state["tags"] = list(arg)
                else:
                    state["desc"] = arg
                return True
            return None

        page.evaluate.side_effect = evaluate
        page.state = state
        return ListCurator(username="testuser"), page

    def test_sets_tags_and_description(self):
        curator, page = self._curator()
        result = curator.curate(page, "my-list", tags=["ranked"], description="A list.")
        assert result["tags"] == ["ranked"]
        assert result["description"] == "A list."
        assert page.state["saved"] is True

    def test_navigates_to_the_edit_page_for_the_slug(self):
        curator, page = self._curator()
        curator.curate(page, "my-list", tags=["ranked"])
        assert page.open.call_args[0][0] == "https://letterboxd.com/testuser/list/my-list/edit/"

    def test_leaves_an_existing_description_alone_when_none_is_given(self):
        """Curating tags must not blank a description that is already
        there; the field is submitted with the form either way."""
        curator, page = self._curator(current_desc="Already written.")
        curator.curate(page, "my-list", tags=["ranked"])
        assert page.state["desc"] == "Already written."

    def test_replaces_rather_than_appends_tags(self):
        """The point of the pass is to replace ad-hoc tags with
        vocabulary ones, so the old tokens have to go."""
        curator, page = self._curator(current_tags=["comedy", "tearjerker"])
        curator.curate(page, "my-list", tags=["hilarious", "devastating"])
        assert page.state["tags"] == ["hilarious", "devastating"]

    def test_reports_when_nothing_changed(self):
        curator, page = self._curator(current_tags=["ranked"], current_desc="Same.")
        result = curator.curate(page, "my-list", tags=["ranked"], description="Same.")
        assert result["changed"] is False
        page.evaluate.assert_any_call  # no assertion on save; just no crash

    def test_dry_run_touches_nothing(self):
        curator, page = self._curator(current_tags=["old"])
        result = curator.curate(page, "my-list", tags=["ranked"], dry_run=True)
        assert page.state["saved"] is False
        assert result["tags"] == ["ranked"]
