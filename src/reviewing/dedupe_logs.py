"""Remove the duplicate diary entries the 2026-08-18 review batch created.

    uv run python -m src.reviewing.dedupe_logs            # list, from the database
    uv run python -m src.reviewing.dedupe_logs --inspect  # read the live entries, plan
    uv run python -m src.reviewing.dedupe_logs --apply    # asks once, then removes

Before ``#76`` the poster clicked "Review or log again…" on films that were
already logged, so four films got a second, *dateless* entry carrying the
AI review next to the user's own dated one. Detection is local: a film in
``posted_reviews`` with two or more ``diary`` rows where one has no date
(or two share one). Removal is live and conservative: the oldest entry
(lowest viewing id) always survives; an extra entry is removed only if its
review text is the text the tool posted; a film with any other extra entry
is skipped whole. If the survivor has no review the AI text is re-posted
onto it through ``ReviewPoster.post_review`` (the edit path); if the
survivor carries text, that text is the user's and is left alone
(invariant 2), even if it means the AI review is gone.

Live structure, recorded 2026-08-27 from ``/<user>/film/persona/``:

- ``/<user>/film/<slug>/activity/`` lists every entry as
  ``a.target[href="/<user>/film/<slug>/"]`` (first log) and
  ``a.target[href="/<user>/film/<slug>/<n>/"]`` (later logs).
- On an entry page ``.view-date`` reads "Watched 27 Apr 2026" for a dated
  entry and a bare "18 Aug 2026" for a dateless one; the review body is
  ``div.body-text.-prose``; the "Edit or delete review…" button carries
  ``data-diary-entry-form-options='{"mode":"edit","viewingId":N,...}'``.
- The edit modal is ``form.js-diary-entry-form`` (hidden ``viewingId``)
  with ``button#diary-entry-delete-button[data-js-trigger=delete]`` whose
  ``data-confirm`` is "Are you sure you want to delete this entry? …" and
  ``data-action`` is ``/s/viewing:N/delete``. The confirm is answered by a
  Playwright dialog handler installed before the click and removed after,
  so no native dialog is ever left open.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path

from playwright.sync_api import Dialog

from src.config import get_config
from src.data_processing.db import open_db
from src.film_identity import film_key
from src.reviewing.diary_form import DiaryForm
from src.reviewing.post_review import ReviewPoster
from src.utils.auth import LetterboxdPage, letterboxd_session
from src.utils.logs import configure

DELETE_BUTTON = "button#diary-entry-delete-button[data-js-trigger=delete]"
ENTRY_FORM = "form.js-diary-entry-form"
REVIEW_BODY = "div.body-text.-prose"
VIEW_DATE = ".view-date"


@dataclass(frozen=True)
class Duplicate:
    uri: str
    name: str
    year: int | None
    date_watched: str | None
    count: int
    ai_text: str


@dataclass(frozen=True)
class Entry:
    viewing_id: int
    url: str
    review: str
    watched: str


@dataclass
class Plan:
    keep: Entry | None
    remove: list[Entry] = field(default_factory=list)
    repost: bool = False
    reason: str = ""


def _norm(text: str | None) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def find_duplicates(conn: sqlite3.Connection) -> list[Duplicate]:
    """Films the tool reviewed that carry an extra diary row, by name."""
    if (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='posted_reviews'"
        ).fetchone()
        is None
    ):
        return []
    posted: dict[tuple[str, int | None], tuple[str, str]] = {}
    for uri, name, year, text in conn.execute(
        "SELECT letterboxd_uri, film_name, film_year, review_text FROM posted_reviews "
        "ORDER BY posted_at"
    ):
        posted[film_key(name, year)] = (uri, text)

    rows: dict[tuple[str, int | None], list[tuple[str, int | None, str | None]]] = {}
    for name, year, date in conn.execute("SELECT name, year, date_watched FROM diary"):
        rows.setdefault(film_key(name, year), []).append((name, year, date))

    found = []
    for key, (uri, text) in posted.items():
        entries = rows.get(key, [])
        dates = [d for _, _, d in entries if d]
        if len(entries) < 2 or (len(dates) == len(entries) and len(set(dates)) == len(dates)):
            continue
        name, year = entries[0][0], entries[0][1]
        found.append(Duplicate(uri, name, year, min(dates) if dates else None, len(entries), text))
    return sorted(found, key=lambda d: d.name)


def plan_removal(entries: list[Entry], ai_text: str) -> Plan:
    """Keep the oldest entry; remove the extras that carry the tool's text.

    Refuses (removes nothing) when any extra entry carries other text: that
    is not ours to delete, and a film in that state needs a human look.
    """
    if len(entries) < 2:
        return Plan(entries[0] if entries else None, reason="only one entry")
    oldest = min(entries, key=lambda e: e.viewing_id)
    wanted = _norm(ai_text)
    extras = [e for e in entries if e is not oldest]
    foreign = [e for e in extras if wanted not in _norm(e.review) or not wanted]
    if foreign:
        return Plan(oldest, reason=f"{foreign[0].url} is not the tool's text; skipped")
    return Plan(oldest, extras, repost=not _norm(oldest.review))


# -- live -------------------------------------------------------------------

_ENTRY_JS = """() => {
  const norm = t => (t || '').replace(/\\s+/g, ' ').trim();
  const btn = [...document.querySelectorAll('button[data-diary-entry-form-options]')]
      .find(b => /"mode":"edit"/.test(b.dataset.diaryEntryFormOptions));
  const body = document.querySelector('%s');
  let text = '';
  if (body) {
    const clone = body.cloneNode(true);
    clone.querySelectorAll('[class*="hidden"], [class*="visually"]').forEach(e => e.remove());
    text = norm(clone.textContent);
  }
  const date = document.querySelector('%s');
  return {options: btn ? btn.dataset.diaryEntryFormOptions : null, review: text,
          watched: date ? norm(date.textContent) : ''};
}""" % (REVIEW_BODY, VIEW_DATE)


def _slug(uri: str) -> str:
    return uri.rstrip("/").split("/film/")[-1].split("/")[0]


def list_entries(page: LetterboxdPage, username: str, slug: str) -> list[Entry]:
    """Every entry for the film, read from its activity page then each entry."""
    base = f"/{username}/film/{slug}/"
    page.open(f"https://letterboxd.com{base}activity/")
    page.wait_for_timeout(2000)
    hrefs: list[str] = page.evaluate(
        "() => [...document.querySelectorAll('a.target[href]')].map(a => a.getAttribute('href'))"
    )
    pattern = re.compile(rf"^{re.escape(base)}(\d+/)?$")
    urls = sorted({f"https://letterboxd.com{h}" for h in hrefs if pattern.match(h)})

    entries = []
    for url in urls:
        page.open(url)
        page.wait_for_timeout(2000)
        info = page.evaluate(_ENTRY_JS)
        if not info["options"]:
            raise RuntimeError(f"{url}: no edit button; is the session signed in?")
        viewing_id = int(json.loads(info["options"])["viewingId"])
        entries.append(Entry(viewing_id, url, info["review"], info["watched"]))
    return entries


def remove_entry(page: LetterboxdPage, entry: Entry) -> bool:
    """Delete one entry through its edit modal; True once it is gone."""
    page.open(entry.url)
    page.wait_for_timeout(2000)
    # The same edit-only opener the poster uses: never a "log again" control.
    if not DiaryForm(page).open_for_edit():
        print(f"    no edit button on {entry.url}; skipped")
        return False
    page.wait_for_timeout(2000)
    form_id = page.locator(f"{ENTRY_FORM} input[name=viewingId]").first
    if form_id.count() == 0 or form_id.input_value() != str(entry.viewing_id):
        print(f"    modal is not for viewing {entry.viewing_id}; skipped")
        page.keyboard.press("Escape")
        return False

    seen: list[str] = []

    def accept(dialog: Dialog) -> None:
        seen.append(dialog.message)
        dialog.accept()

    page.on("dialog", accept)
    try:
        page.locator(DELETE_BUTTON).first.click()
        page.wait_for_timeout(4000)
    finally:
        page.remove_listener("dialog", accept)

    # Through the navigator: `gone` is read off this page, so a challenge
    # served here would be scored as "the entry is deleted" -- the worst
    # possible reading of a block.
    if not page.open(entry.url):
        print("    could not re-open the entry to confirm; treating as not removed")
        return False
    page.wait_for_timeout(2000)
    gone = page.evaluate(_ENTRY_JS)["options"] is None or "404" in page.title()
    print(f"    confirm dialog: {seen[0][:40] + '…' if seen else 'none shown'}; gone: {gone}")
    return gone


def forget_local_rows(conn: sqlite3.Connection, dup: Duplicate, removed: int) -> int:
    """Drop the local diary rows that stood for the removed entries."""
    name, year = film_key(dup.name, dup.year)
    ids = [
        row_id
        for (row_id,) in conn.execute(
            "SELECT id FROM diary WHERE lower(trim(name)) = ? AND year IS ? "
            "ORDER BY (date_watched IS NULL OR date_watched = '') DESC, id DESC",
            (name, year),
        )
    ][:removed]
    conn.executemany("DELETE FROM diary WHERE id = ?", [(i,) for i in ids])
    conn.commit()
    return len(ids)


def main() -> None:
    configure("dedupe_logs")
    parser = argparse.ArgumentParser(description="Remove tool-made duplicate diary entries")
    parser.add_argument("--inspect", action="store_true", help="read the live entries, no writes")
    parser.add_argument("--apply", action="store_true", help="remove them (asks once)")
    args = parser.parse_args()

    config = get_config()
    db_path = Path(config.database_file)
    if not db_path.exists():
        print(f"Database not found: {db_path}", file=sys.stderr)
        sys.exit(2)
    with open_db(db_path) as conn:
        dups = find_duplicates(conn)
        if not dups:
            print("No duplicate entries found.")
            return
        print(f"{len(dups)} film(s) with a duplicate entry:")
        for d in dups:
            print(f"  {d.name} ({d.year}): {d.count} diary rows, watched {d.date_watched}; {d.uri}")
        if not (args.inspect or args.apply):
            print("\nDry run. --inspect reads the live entries; --apply removes the extras.")
            return
        if args.apply:
            answer = input(f"\nRemove the extra entries for these {len(dups)} films? [y/N] ")
            if answer.strip().lower() != "y":
                print("Nothing removed.")
                return

        removed_total = 0
        # Bound before the try: constructing it inside means a failure there
        # leaves `poster` unbound and the finally raises UnboundLocalError,
        # masking the real error.
        poster = ReviewPoster() if args.apply else None
        with letterboxd_session(config) as page:
            try:
                for d in dups:
                    print(f"\n== {d.name} ({d.year})")
                    entries = list_entries(page, config.username, _slug(d.uri))
                    for e in sorted(entries, key=lambda e: e.viewing_id):
                        print(f"  viewing {e.viewing_id}  {e.watched:<22} {e.url}")
                        print(f"    review: {e.review[:90]!r}")
                    plan = plan_removal(entries, d.ai_text)
                    if not plan.remove:
                        print(f"  skip: {plan.reason}")
                        continue
                    print(f"  keep   {plan.keep.url if plan.keep else '?'}")
                    for e in plan.remove:
                        print(f"  remove {e.url}")
                    print(f"  re-post AI text onto the survivor: {'yes' if plan.repost else 'no'}")
                    if not args.apply or poster is None:
                        continue
                    removed = sum(1 for e in plan.remove if remove_entry(page, e))
                    if removed and plan.repost and plan.keep is not None:
                        ok, _ = poster.post_review(
                            page,
                            {
                                "name": d.name,
                                "year": d.year,
                                "review": d.ai_text,
                                "letterboxd_uri": plan.keep.url,
                                "rating": None,
                            },
                        )
                        print(f"  re-posted AI text onto {plan.keep.url}: {ok}")
                    if removed:
                        forget_local_rows(conn, d, removed)
                    removed_total += removed
            finally:
                if poster is not None:
                    poster.close()
        if args.apply:
            print(f"\nRemoved {removed_total} entries. Now run: uv run python -m src.sync")


if __name__ == "__main__":
    main()
