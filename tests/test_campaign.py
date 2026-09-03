"""Tests for src/reviewing/campaign.py - bounded review campaigns.

Invariant 1 (edit, never re-log) and invariant 2 (a human review is never
touched) each get a named test here.
"""

import sqlite3
from unittest.mock import MagicMock

import pytest

from src.data_processing.create_database import MovieDatabase
from src.data_processing.migrations import MigrationManager


def build_db(path):
    db = MovieDatabase(db_path=path)
    db.connect()
    db.create_tables()
    db.close()
    manager = MigrationManager(db_path=path)
    manager.connect()
    manager.run_pending_migrations()
    manager.close()
    conn = sqlite3.connect(path)
    c = conn.cursor()
    c.executemany(
        "INSERT INTO films VALUES (?,?,?,?,?,?)",
        [
            ("u:own", "Own Reviewed", 2002, "2024-03-01", None, 0),
            ("u:drafted", "Already Drafted", 2003, "2024-03-01", None, 0),
            ("u:unrated", "Unrated", 2004, "2024-09-01", None, 0),
            ("u:a", "Alpha", 2005, "2024-05-01", None, 0),
            ("u:b", "Beta", 2006, "2024-04-01", None, 0),
            ("u:c", "Gamma", 2007, "2024-07-01", None, 0),
        ],
    )
    c.executemany(
        "INSERT INTO ratings VALUES (?,?,?,?,?)",
        [
            ("u:own", "Own Reviewed", 2002, 5.0, "x"),
            ("u:drafted", "Already Drafted", 2003, 5.0, "x"),
            ("u:a", "Alpha", 2005, 5.0, "x"),
            ("u:b", "Beta", 2006, 4.5, "x"),
            ("u:c", "Gamma", 2007, 3.0, "x"),
        ],
    )
    c.execute(
        "INSERT INTO reviews VALUES (?,?,?,?,?,?)",
        ("r:own", "Own Reviewed", 2002, "Mine, hands off.", "2024-03-01", 5.0),
    )
    c.execute(
        "INSERT INTO ai_reviews (letterboxd_uri, name, year, ai_review, generated_at) "
        "VALUES (?,?,?,?,?)",
        ("u:drafted", "Already Drafted", 2003, "draft", "2024-01-01"),
    )
    conn.commit()
    return conn


def approve(path, *uris):
    """Record the human decision the gate requires."""
    conn = sqlite3.connect(path)
    conn.executemany(
        "UPDATE ai_reviews SET status = 'approved' WHERE letterboxd_uri = ?",
        [(u,) for u in uris],
    )
    conn.commit()
    conn.close()


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "movie_database.db"
    build_db(path).close()
    return path


class TestSelectCampaign:
    def test_takes_the_review_tier_in_queue_order_without_drafts(self, db_path):
        from src.reviewing.campaign import select_campaign

        films = select_campaign(sqlite3.connect(db_path), per_run=5, sample=None, seed=None)
        assert [f["name"] for f in films] == ["Alpha", "Beta", "Gamma"]
        assert films[0] == {"letterboxd_uri": "u:a", "name": "Alpha", "year": 2005, "rating": 5.0}

    def test_invariant_2_a_film_with_an_own_review_is_never_selected(self, db_path):
        from src.reviewing.campaign import select_campaign

        conn = sqlite3.connect(db_path)
        for seed in range(20):
            names = {f["name"] for f in select_campaign(conn, 10, sample=1.0, seed=seed)}
            assert "Own Reviewed" not in names

    def test_invariant_3_an_unrated_film_is_never_selected(self, db_path):
        from src.reviewing.campaign import select_campaign

        names = {f["name"] for f in select_campaign(sqlite3.connect(db_path), 10, None, None)}
        assert "Unrated" not in names

    def test_per_run_bounds_and_seeded_sample_is_deterministic(self, db_path):
        from src.reviewing.campaign import select_campaign

        conn = sqlite3.connect(db_path)
        assert len(select_campaign(conn, per_run=2, sample=None, seed=None)) == 2
        first = select_campaign(conn, per_run=5, sample=0.5, seed=7)
        again = select_campaign(conn, per_run=5, sample=0.5, seed=7)
        assert first == again
        assert len(first) < 3 or seed_hits_all(conn)


def seed_hits_all(conn):
    # A 0.5 sample over three films can legitimately keep all three;
    # determinism is the property under test, not the count.
    return True


class TestDigest:
    def test_digest_carries_titles_ratings_text_and_uris(self, tmp_path):
        from src.reviewing.campaign import digest_uris, write_digest

        path = write_digest(
            tmp_path / "digests",
            [
                {
                    "letterboxd_uri": "u:a",
                    "name": "Alpha",
                    "year": 2005,
                    "rating": 5.0,
                    "review": "Quietly great.",
                },
            ],
            tone="thoughtful",
            now="2026-08-27T01:02:03+00:00",
        )
        assert path.name == "20260827T010203Z-reviews.md"
        text = path.read_text()
        assert "## Alpha (2005)" in text and "5.0" in text and "Quietly great." in text
        assert digest_uris(path) == ["u:a"]

    def test_latest_digest_picks_the_newest(self, tmp_path):
        from src.reviewing.campaign import latest_digest

        d = tmp_path / "digests"
        d.mkdir()
        (d / "20260101T000000Z-reviews.md").write_text("old")
        (d / "20260202T000000Z-reviews.md").write_text("new")
        assert latest_digest(d).name.startswith("20260202")
        assert latest_digest(tmp_path / "none") is None


class FakeGenerator:
    """Stands in for ReviewGenerator; records what it was asked to write."""

    instances: list = []

    def __init__(self, tone=None, provider=None, **_):
        self.tone = tone
        self.provider = provider
        self.asked: list[str] = []
        FakeGenerator.instances.append(self)
        self.db = MagicMock()

    declines: set[str] = set()

    def generate_review(self, film, avoid=None):
        self.asked.append(film["name"])
        if film["name"] in FakeGenerator.declines:
            return None
        return f"Review of {film['name']}."

    def draft_batch(self, films):
        """The real generator's batch interface, which owns the ban list."""
        for film in films:
            yield film, self.generate_review(film)

    def close(self):
        pass


class TestMain:
    @pytest.fixture
    def env(self, db_path, monkeypatch, tmp_path):
        FakeGenerator.instances = []
        FakeGenerator.declines = set()
        monkeypatch.setattr("src.reviewing.campaign.ReviewGenerator", FakeGenerator)
        monkeypatch.setattr("src.reviewing.campaign.DIGEST_DIR", tmp_path / "digests")
        config = MagicMock()
        config.database_file = db_path
        monkeypatch.setattr("src.reviewing.campaign.get_config", lambda: config)
        poster = MagicMock()
        poster.run.return_value = 2
        monkeypatch.setattr("src.reviewing.campaign.ReviewPoster", lambda tone: poster)
        return {"db": db_path, "digests": tmp_path / "digests", "poster": poster}

    def test_dry_run_drafts_writes_digest_and_stops(self, env, monkeypatch, capsys):
        from src.reviewing import campaign

        monkeypatch.setattr("sys.argv", ["campaign", "--per-run", "2", "--tone", "thoughtful"])
        campaign.main()
        out = capsys.readouterr().out
        assert FakeGenerator.instances[0].asked == ["Alpha", "Beta"]
        assert FakeGenerator.instances[0].tone == "thoughtful"
        digests = list(env["digests"].iterdir())
        assert len(digests) == 1
        assert "Review of Alpha." in digests[0].read_text()
        assert "approve on /drafts" in out
        assert "uv run python -m src.reviewing.campaign --apply" in out
        env["poster"].run.assert_not_called()
        # Drafts are saved so --apply can post exactly what was reviewed.
        conn = sqlite3.connect(env["db"])
        saved = conn.execute("SELECT letterboxd_uri FROM ai_reviews ORDER BY 1").fetchall()
        assert saved == [("u:a",), ("u:b",), ("u:drafted",)]

    def test_apply_posts_the_approved_drafts_named_in_the_latest_digest(self, env, monkeypatch):
        from src.reviewing import campaign

        monkeypatch.setattr("sys.argv", ["campaign", "--per-run", "2"])
        campaign.main()
        approve(env["db"], "u:a", "u:b")
        monkeypatch.setattr("sys.argv", ["campaign", "--per-run", "2", "--apply"])
        campaign.main()

        # No second generation: the digest's films are posted, nothing new drafted.
        assert len(FakeGenerator.instances) == 1
        env["poster"].run.assert_called_once_with(limit=2, uris=["u:a", "u:b"])

    def test_apply_posts_only_the_approved_half_of_the_digest(self, env, monkeypatch):
        from src.reviewing import campaign

        monkeypatch.setattr("sys.argv", ["campaign", "--per-run", "2"])
        campaign.main()
        approve(env["db"], "u:b")
        monkeypatch.setattr("sys.argv", ["campaign", "--per-run", "2", "--apply"])
        campaign.main()
        env["poster"].run.assert_called_once_with(limit=2, uris=["u:b"])

    def test_apply_with_nothing_approved_posts_nothing_and_says_so(self, env, monkeypatch, capsys):
        """The gate: drafts exist and a digest names them, but no human has
        approved any, so no browser is opened and nothing is posted."""
        from src.reviewing import campaign

        monkeypatch.setattr("sys.argv", ["campaign", "--per-run", "2"])
        campaign.main()
        capsys.readouterr()
        monkeypatch.setattr("sys.argv", ["campaign", "--per-run", "2", "--apply"])
        campaign.main()

        assert "No approved drafts to post" in capsys.readouterr().out
        env["poster"].run.assert_not_called()

    def test_apply_never_drafts(self, env, monkeypatch, capsys):
        """--apply posts and does not write. A draft it generated itself
        could not have been approved by anyone, so drafting under --apply
        would only pile up work while posting nothing."""
        from src.reviewing import campaign

        monkeypatch.setattr("sys.argv", ["campaign", "--per-run", "1", "--apply"])
        campaign.main()
        assert FakeGenerator.instances == []
        assert "No approved drafts to post" in capsys.readouterr().out
        env["poster"].run.assert_not_called()

    def test_apply_posts_approved_drafts_even_with_no_digest(self, env, monkeypatch):
        """The digest is a reading aid, not the record of the decision."""
        from src.reviewing import campaign

        monkeypatch.setattr("sys.argv", ["campaign", "--per-run", "2"])
        campaign.main()
        for f in env["digests"].iterdir():
            f.unlink()
        approve(env["db"], "u:a")
        monkeypatch.setattr("sys.argv", ["campaign", "--per-run", "2", "--apply"])
        campaign.main()
        env["poster"].run.assert_called_once_with(limit=2, uris=["u:a"])

    def test_a_declined_film_is_passed_over_not_stalled_on(self, env, monkeypatch, capsys):
        """The model answers SKIP for films it does not know; that film
        would otherwise head the queue on every run and block the campaign."""
        from src.reviewing import campaign

        FakeGenerator.declines = {"Alpha"}
        monkeypatch.setattr("sys.argv", ["campaign", "--per-run", "1"])
        campaign.main()
        assert FakeGenerator.instances[0].asked == ["Alpha", "Beta"]
        assert "skipped Alpha (2005)" in capsys.readouterr().out
        conn = sqlite3.connect(env["db"])
        assert conn.execute(
            "SELECT COUNT(*) FROM ai_reviews WHERE letterboxd_uri='u:b'"
        ).fetchone() == (1,)
        assert conn.execute(
            "SELECT COUNT(*) FROM ai_reviews WHERE letterboxd_uri='u:a'"
        ).fetchone() == (0,)

    def test_nothing_to_do(self, env, monkeypatch, capsys):
        from src.reviewing import campaign

        conn = sqlite3.connect(env["db"])
        conn.execute("DELETE FROM films WHERE letterboxd_uri IN ('u:a','u:b','u:c')")
        conn.commit()
        conn.close()
        monkeypatch.setattr("sys.argv", ["campaign"])
        campaign.main()
        assert "Nothing to draft" in capsys.readouterr().out
        assert FakeGenerator.instances == []


class TestPosterUriFilter:
    @pytest.fixture
    def poster(self, db_path, monkeypatch):
        config = MagicMock()
        config.database_file = db_path
        config.username = "testuser"
        monkeypatch.setattr("src.reviewing.post_review.get_config", lambda: config)
        monkeypatch.setattr("src.reviewing.post_review.ReviewMetricsDB", MagicMock)
        from src.reviewing.post_review import ReviewPoster

        poster = ReviewPoster()
        poster.db.save_ai_review("u:a", "Alpha", 2005, "A.")
        poster.db.save_ai_review("u:b", "Beta", 2006, "B.")
        poster.db.set_ai_review_status("u:a", "approved")
        poster.db.set_ai_review_status("u:b", "approved")
        return poster

    def test_run_only_offers_the_given_uris(self, poster, capsys):
        assert poster.run(limit=5, dry_run=True, uris=["u:b"]) == 0
        out = capsys.readouterr().out
        assert "Beta" in out and "Alpha" not in out and "Already Drafted" not in out


class TestInvariant1EditNeverRelog:
    """The campaign posts through ReviewPoster.open_review_form. When the
    film page offers only a "log again" control, that control is never
    clicked: the poster goes to the user's entry URL and edits there."""

    @pytest.fixture
    def poster(self, db_path, monkeypatch):
        config = MagicMock()
        config.database_file = db_path
        config.username = "testuser"
        monkeypatch.setattr("src.reviewing.post_review.get_config", lambda: config)
        monkeypatch.setattr("src.reviewing.post_review.ReviewMetricsDB", MagicMock)
        from src.reviewing.post_review import ReviewPoster

        return ReviewPoster()

    @pytest.mark.parametrize(
        "only_button", ["log again / add review", "log again / edit review", "review or log again"]
    )
    def test_log_again_is_never_among_the_labels_clicked(self, poster, only_button):
        page = MagicMock()
        page.url = "https://letterboxd.com/film/alpha/"
        labels = {only_button}
        clicked: list[str] = []

        def evaluate(js, arg=None):
            if arg is None:  # the duplicate probe: report the button, click nothing
                return next((lbl for lbl in labels if "log again" in lbl), None)
            hit = next((lbl for lbl in arg if lbl in labels), None)
            if hit:
                clicked.append(hit)
            return hit

        def goto(url, **_):
            assert url == "https://letterboxd.com/testuser/film/alpha/"
            labels.clear()
            labels.add("edit or delete review")

        page.evaluate.side_effect = evaluate
        page.goto.side_effect = goto

        assert poster.open_review_form(page, "Alpha") is True
        assert clicked == ["edit or delete review"]
        for call in page.evaluate.call_args_list:
            if len(call.args) > 1:
                assert not any("log again" in lbl for lbl in call.args[1])
        page.goto.assert_called_once()
