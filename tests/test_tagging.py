"""Tests for src/tagging - the controlled tag vocabulary and suggester."""

from unittest.mock import MagicMock

import pytest

from src.tagging.taxonomy import (
    ALIASES,
    FACETS,
    MAX_TAGS,
    canonical_tags,
    describe_taxonomy,
    normalize_tag,
    validate_tags,
)


class TestTaxonomyShape:
    def test_every_tag_is_lowercase_hyphenated(self):
        for facet, tags in FACETS.items():
            for tag in tags:
                assert tag == tag.lower(), f"{facet}:{tag} is not lowercase"
                assert " " not in tag, f"{facet}:{tag} contains a space"
                assert tag.strip("-") == tag, f"{facet}:{tag} has a stray hyphen"

    def test_no_tag_appears_in_two_facets(self):
        seen: dict[str, str] = {}
        for facet, tags in FACETS.items():
            for tag in tags:
                assert tag not in seen, f"{tag} is in both {seen.get(tag)} and {facet}"
                seen[tag] = facet

    def test_aliases_all_resolve_to_canonical_tags(self):
        for alias, target in ALIASES.items():
            assert target in canonical_tags(), f"alias {alias} points at unknown tag {target}"
            assert alias not in canonical_tags(), f"alias {alias} is also a canonical tag"

    def test_describe_taxonomy_lists_every_tag(self):
        described = describe_taxonomy()
        for tag in canonical_tags():
            assert tag in described


class TestNormalizeTag:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("Cinematography", "cinematography"),
            ("  Slow Burn  ", "slow-burn"),
            ("minimal_dialogue", "minimal-dialogue"),
            ("Black and White", "black-and-white"),
            ("coming--of--age", "coming-of-age"),
            ("#animation", "animation"),
        ],
    )
    def test_normalizes(self, raw, expected):
        assert normalize_tag(raw) == expected

    def test_empty_input_is_empty(self):
        assert normalize_tag("   ") == ""


class TestValidateTags:
    def test_keeps_canonical_and_drops_invented(self):
        result = validate_tags(["cinematography", "kino", "vibes", "grief"])
        assert result == ["cinematography", "grief"]

    def test_resolves_aliases(self):
        assert validate_tags(["b&w", "sci fi"]) == ["black-and-white", "sci-fi"]

    def test_deduplicates_preserving_order(self):
        assert validate_tags(["grief", "Grief", "b&w", "black-and-white"]) == [
            "grief",
            "black-and-white",
        ]

    def test_caps_at_max_tags(self):
        many = list(canonical_tags())[: MAX_TAGS + 5]
        assert len(validate_tags(many)) == MAX_TAGS

    def test_empty_stays_empty(self):
        assert validate_tags([]) == []
        assert validate_tags(["", "   "]) == []


class TestSuggester:
    def _suggester(self, reply):
        from src.tagging.suggester import TagSuggester

        provider = MagicMock()
        provider.generate.return_value = reply
        return TagSuggester(provider=provider), provider

    def test_parses_comma_separated_reply(self):
        suggester, _ = self._suggester("cinematography, grief, slow-burn")
        assert suggester.suggest({"name": "Film", "year": 2000}, "some review") == [
            "cinematography",
            "grief",
            "slow-burn",
        ]

    def test_drops_tags_outside_the_taxonomy(self):
        """The model inventing tags is exactly how 40 junk tags got on a
        list before; anything off-vocabulary is discarded, not stored."""
        suggester, _ = self._suggester("cinematography, vibey, epic-masterpiece")
        assert suggester.suggest({"name": "Film", "year": 2000}, "review") == ["cinematography"]

    def test_prompt_carries_the_vocabulary_and_the_review(self):
        suggester, provider = self._suggester("grief")
        suggester.suggest({"name": "Ikiru", "year": 1952}, "a review about mortality")
        prompt = provider.generate.call_args.kwargs["prompt"]
        assert "Ikiru" in prompt
        assert "a review about mortality" in prompt
        assert "mortality" in prompt  # taxonomy included

    def test_provider_failure_yields_no_tags(self):
        suggester, provider = self._suggester(None)
        assert suggester.suggest({"name": "Film", "year": 2000}, "review") == []

    def test_handles_newline_and_bulleted_replies(self):
        suggester, _ = self._suggester("- grief\n- memory\n")
        assert suggester.suggest({"name": "F", "year": 1}, "r") == ["grief", "memory"]


class TestTagPersistence:
    """Applied tags are recorded so a re-run does not redo the work."""

    @pytest.fixture
    def db(self, tmp_path):
        from src.data_processing.create_database import MovieDatabase
        from src.data_processing.migrations import MigrationManager

        path = tmp_path / "movie_database.db"
        database = MovieDatabase(db_path=path)
        database.connect()
        database.create_tables()
        database.close()

        manager = MigrationManager(db_path=path)
        manager.connect()
        manager.run_pending_migrations()
        manager.close()

        database = MovieDatabase(db_path=path)
        database.connect()
        database.cursor.execute(
            """INSERT INTO ai_reviews (letterboxd_uri, name, year, ai_review, posted_at)
               VALUES ('u1', 'Film', 2000, 'text', '2026-01-01')"""
        )
        database.conn.commit()
        yield database
        database.close()

    def test_base_schema_has_the_tags_column(self, db):
        """Like posted_at before it, the column must exist in the base
        schema too: a re-import rebuilds the table while schema_version
        still records the migration as applied."""
        cols = [c[1] for c in db.cursor.execute("PRAGMA table_info(ai_reviews)")]
        assert "tags" in cols

    def test_save_and_read_back(self, db):
        db.save_ai_review_tags("u1", ["grief", "memory"])
        assert db.get_ai_review_tags("u1") == ["grief", "memory"]

    def test_unknown_uri_reads_empty(self, db):
        assert db.get_ai_review_tags("nope") == []

    def test_untagged_reviews_lists_only_untagged(self, db):
        db.cursor.execute(
            """INSERT INTO ai_reviews (letterboxd_uri, name, year, ai_review, posted_at)
               VALUES ('u2', 'Other', 2001, 'text2', '2026-01-02')"""
        )
        db.conn.commit()
        db.save_ai_review_tags("u1", ["grief"])

        pending = db.get_posted_reviews_without_tags()
        assert [p["letterboxd_uri"] for p in pending] == ["u2"]
        assert pending[0]["review"] == "text2"


class TestReviewTagger:
    """Tagging an existing review must never create a second entry."""

    def _tagger(self, monkeypatch, suggested=None, applied=None, form_opens=True):
        from src.tagging.apply import ReviewTagger

        form = MagicMock()
        form.open.return_value = form_opens
        form.set_tags.side_effect = lambda tags: applied if applied is not None else tags
        form.submit.return_value = True
        monkeypatch.setattr("src.tagging.apply.DiaryForm", lambda page, username: form)

        suggester = MagicMock()
        suggester.suggest.return_value = suggested if suggested is not None else []

        db = MagicMock()
        page = MagicMock()
        page.evaluate.return_value = True
        return ReviewTagger("testuser", suggester, db), form, db, page

    def _film(self):
        return {
            "letterboxd_uri": "https://boxd.it/abc",
            "name": "Ikiru",
            "year": 1952,
            "review": "a review",
        }

    def test_applies_and_records_suggested_tags(self, monkeypatch):
        tagger, form, db, page = self._tagger(monkeypatch, suggested=["mortality", "melancholy"])
        assert tagger.tag_film(page, self._film()) == ["mortality", "melancholy"]
        db.save_ai_review_tags.assert_called_once_with(
            "https://boxd.it/abc", ["mortality", "melancholy"]
        )
        form.open.assert_called_once()

    def test_explicit_tags_are_validated_not_trusted(self, monkeypatch):
        tagger, _, db, page = self._tagger(monkeypatch)
        assert tagger.tag_film(page, self._film(), tags=["grief", "made-up-tag"]) == ["grief"]
        db.save_ai_review_tags.assert_called_once_with("https://boxd.it/abc", ["grief"])

    def test_no_applicable_tags_touches_nothing(self, monkeypatch):
        tagger, form, db, page = self._tagger(monkeypatch, suggested=[])
        assert tagger.tag_film(page, self._film()) == []
        form.open.assert_not_called()
        db.save_ai_review_tags.assert_not_called()

    def test_unopenable_form_records_nothing(self, monkeypatch):
        tagger, _, db, page = self._tagger(monkeypatch, suggested=["grief"], form_opens=False)
        assert tagger.tag_film(page, self._film()) == []
        db.save_ai_review_tags.assert_not_called()

    def test_run_skips_already_tagged_and_counts_work(self, monkeypatch):
        tagger, _, db, page = self._tagger(monkeypatch, suggested=["grief"])
        db.get_posted_reviews_without_tags.return_value = [self._film(), self._film()]
        assert tagger.run(page) == 2

    def test_dry_run_writes_nothing(self, monkeypatch, capsys):
        tagger, form, db, page = self._tagger(monkeypatch, suggested=["grief"])
        db.get_posted_reviews_without_tags.return_value = [self._film()]
        assert tagger.run(page, dry_run=True) == 0
        form.open.assert_not_called()
        db.save_ai_review_tags.assert_not_called()
        assert "Ikiru" in capsys.readouterr().out


class TestTokenBudget:
    """Extended thinking shares the output budget with the answer."""

    def test_suggester_leaves_room_for_thinking(self):
        """At max_tokens=60 the thinking block consumed the entire
        budget, the response carried no text block, and the caller read
        that as 'no tags apply' for a quarter of the library."""
        from src.tagging.suggester import TagSuggester

        provider = MagicMock()
        provider.generate.return_value = "grief"
        TagSuggester(provider=provider).suggest({"name": "F", "year": 1}, "r")
        assert provider.generate.call_args.kwargs["max_tokens"] >= 400
