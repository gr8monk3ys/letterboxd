"""Driving Letterboxd's diary-entry modal.

Everything about the form that a caller would otherwise have to know: which
of the five buttons opens it, which two of them silently create a *second*
diary entry for a film watched once, when the diary-date checkbox may be
touched, and that the visible Save button does not work.

This was inside ReviewPoster, alongside two database connections, posting
bookkeeping and an interactive CLI loop. Two other modules wanted only this
part and paid for all four: `tagging/apply.py` constructed a whole
ReviewPoster to borrow two methods and then re-implemented the submit block
verbatim, and `dedupe_logs.py` imported `_CLICK_BUTTON_JS` -- a private name
-- across modules.

The knowledge here was expensive to acquire. The label list, the
`specifiedDate` rule and the still-open-form check each record a specific
incident; the comments name them.
"""

from __future__ import annotations

import logging

from src.tagging.taxonomy import validate_tags
from src.utils.auth import LetterboxdPage

logger = logging.getLogger(__name__)

# Editing an existing entry never creates a duplicate, so these win.
EDIT_BUTTON_LABELS = ("edit or delete review", "edit entry or add review")
# Only offered when the film has never been logged.
NEW_ENTRY_BUTTON_LABELS = ("review or log",)
# Buttons that add a second diary entry for a film watched once. Their
# wording keeps changing ("log again / add review", "log again / edit
# review", "review or log again"), so they are recognised by the phrase
# they share rather than by an exact list that goes stale.
DUPLICATE_BUTTON_PHRASE = "log again"

# Match on the full label, trailing ellipsis and thin spaces normalized.
_NORMALIZE_LABEL_JS = """
    const norm = el => (el.textContent || '').trim().toLowerCase()
        .replace(/[\\s\\u2009\\u00a0]+/g, ' ')
        .replace(/[\\u2026.]+$/, '').trim();
"""

_FIND_DUPLICATE_JS = (
    """() => {"""
    + _NORMALIZE_LABEL_JS
    + f"""
    const btn = [...document.querySelectorAll('button')]
        .find(b => b.offsetParent !== null && norm(b).includes("{DUPLICATE_BUTTON_PHRASE}"));
    return btn ? norm(btn) : null;
}}"""
)

# True when any opener or duplicate button has rendered, so the click
# below is attempted on a page that has finished drawing its controls.
_FIND_ANY_BUTTON_JS = (
    """(labels) => {"""
    + _NORMALIZE_LABEL_JS
    + f"""
    return [...document.querySelectorAll('button')].some(b => b.offsetParent !== null
        && (labels.includes(norm(b)) || norm(b).includes("{DUPLICATE_BUTTON_PHRASE}")));
}}"""
)

_CLICK_BUTTON_JS = (
    """(labels) => {"""
    + _NORMALIZE_LABEL_JS
    + """
    for (const label of labels) {
        const btn = [...document.querySelectorAll('button')]
            .find(b => b.offsetParent !== null && norm(b) === label);
        if (btn) { btn.click(); return label; }
    }
    return null;
}"""
)


_KEEP_DIARY_DATE_JS = """() => {
    const form = document.querySelector('form.js-diary-entry-form');
    if (!form) return;
    const id = form.querySelector('input[name="viewingId"]');
    if (id && id.value) return;  // editing: keep the diary date
    const box = form.querySelector('input[name="specifiedDate"]');
    if (box && box.checked) box.click();
}"""

_SET_RATING_JS = """(idx) => {
    const stars = document.querySelectorAll(
        'form.js-diary-entry-form input[type=radio]');
    if (stars[idx]) stars[idx].click();
}"""

_SUBMIT_JS = """() => {
    const form = document.querySelector('form.js-diary-entry-form');
    if (!form) return false;
    form.requestSubmit();
    return true;
}"""


def squash(text: str) -> str:
    """Collapse whitespace, so two spellings of the same review compare equal."""
    return " ".join((text or "").split())


class DiaryForm:
    """The diary-entry modal for one film, on one page.

    Every method acts on the form currently open on `page`; nothing here
    touches a database or decides *which* film to act on. That separation is
    the point: the poster, the tagger and the de-duplicator all drive the
    same form and disagree only about why.
    """

    def __init__(self, page: LetterboxdPage, username: str = ""):
        self.page = page
        # Only needed to build the user's own entry URL, which `open` uses
        # when a film is already logged and `entry_url` reports afterwards.
        # Callers that only edit an open modal can leave it out.
        self.username = username

    # -- opening -------------------------------------------------------

    def open(self, name: str) -> bool:
        """Open the diary-entry modal from whichever button this page has.

        Letterboxd labels the control five ways depending on whether the
        film is logged and whether it already carries a review. Two of
        them ("...log again") create a *second* diary entry for a film
        watched once, so the edit variants are always preferred and the
        duplicate variants are never clicked. Matching is on the whole
        normalized label, never a substring: "Review or log again"
        contains "Review or log", and matching loosely would silently
        duplicate an entry every time a review was edited or re-tagged.
        """
        openers = EDIT_BUTTON_LABELS + NEW_ENTRY_BUTTON_LABELS
        # The action buttons are rendered client-side after the document
        # loads; a fixed pause after navigation is sometimes too short
        # (Kwaidan, 2026-08-27: "could not find review button" on a page
        # that offered "Edit entry or add review..." a moment later).
        for _ in range(5):
            if self.page.evaluate(_FIND_ANY_BUTTON_JS, list(openers)):
                break
            self.page.wait_for_timeout(1500)
        if self.page.evaluate(_CLICK_BUTTON_JS, list(openers)):
            return True

        # Only the duplicate-creating buttons are on this page, which
        # means the film is already logged: edit that entry instead.
        if self.page.evaluate(_FIND_DUPLICATE_JS):
            slug = self.page.url.split("/film/")[-1].strip("/").split("/")[0]
            entry_url = f"https://letterboxd.com/{self.username}/film/{slug}/"
            logger.info(f"{name} is already logged; editing the existing entry")
            if not self.page.open(entry_url):
                logger.warning(f"Could not open the existing entry for {name}")
                return False
            self.page.wait_for_timeout(2000)
            if self.page.evaluate(_CLICK_BUTTON_JS, list(EDIT_BUTTON_LABELS)):
                return True

        logger.warning(f"Could not find review button for {name}")
        return False

    def open_for_edit(self) -> bool:
        """Open the modal using only the edit-variant buttons.

        For callers that know the film is already logged and must not risk a
        "log again" control -- the de-duplicator, which is deleting entries.
        Public because it used to be reached by importing `_CLICK_BUTTON_JS`
        across modules.
        """
        clicked: str | None = self.page.evaluate(_CLICK_BUTTON_JS, list(EDIT_BUTTON_LABELS))
        return clicked is not None

    # -- reading and filling -------------------------------------------

    def _textarea(self):
        return self.page.locator('form.js-diary-entry-form textarea[name="review"]').first

    def existing_review(self) -> str | None:
        """The review already on this entry, or None if the form is missing."""
        textarea = self._textarea()
        if textarea.count() == 0:
            return None
        return str(textarea.input_value())

    def fill_review(self, text: str) -> bool:
        """Write the review into the form."""
        textarea = self._textarea()
        if textarea.count() == 0:
            return False
        textarea.fill(text)
        self.page.wait_for_timeout(500)
        return True

    def set_tags(self, tags: list[str]) -> list[str]:
        """Enter tags in the modal's typeahead, returning what stuck.

        The field tokenizes as you type into hidden `tag` inputs. It also
        races: a token can land half-typed, which is how a stray
        "tearjer" once reached a list on this account. So the tokens are
        read back and anything that was not asked for is removed before
        the form is saved.

        Tags are validated here rather than by each caller. The taxonomy
        guarantees an invented tag never reaches the account, and that
        guarantee used to hold on only one of the two paths that can write
        tags -- the tagger validated, the poster did not.
        """
        tags = validate_tags(tags) if tags else []
        if not tags:
            return []

        field = self.page.locator("input[name=tags]").first
        if field.count() == 0:
            logger.warning("Tag field not present; skipping tags")
            return []

        for tag in tags:
            field.click()
            field.type(tag, delay=40)
            self.page.wait_for_timeout(500)
            self.page.keyboard.press("Comma")
            self.page.wait_for_timeout(400)

        tokens: list[str] = self.page.evaluate(
            "() => [...document.querySelectorAll('input[name=tag]')].map(i => i.value)"
        )
        stray = [t for t in tokens if t not in tags]
        if stray:
            logger.warning(f"Removing tokens the typeahead invented: {stray}")
            self.page.evaluate(
                """(bad) => {
                    document.querySelectorAll('#current-tags li.tag, li.tag').forEach(li => {
                        const inp = li.querySelector('input[name=tag]');
                        if (inp && bad.includes(inp.value)) li.remove();
                    });
                }""",
                stray,
            )
            tokens = [t for t in tokens if t not in stray]

        return tokens

    def keep_diary_date(self) -> None:
        """Claim no watch date on a new entry; never touch an existing one.

        On a new entry an unchecked `specifiedDate` means no diary date is
        claimed (the old behaviour invented one). On an *existing* entry the
        box reflects the user's own diary date, and unchecking it deletes
        that date -- measured 2026-08-27 on The Sound of Music, whose 23 Aug
        entry silently became a dateless review.
        """
        try:
            self.page.evaluate(_KEEP_DIARY_DATE_JS)
        except Exception as e:
            logger.warning(f"Could not clear the date checkbox: {e}")

    def set_rating(self, rating: float | None) -> None:
        """Carry the user's rating onto the entry so it does not show unrated.

        Star radios are ordered half-star inputs, so index = rating * 2.
        """
        if not rating:
            return
        try:
            self.page.evaluate(_SET_RATING_JS, int(float(rating) * 2))
        except Exception as e:
            logger.warning(f"Could not set star rating: {e}")

    # -- saving --------------------------------------------------------

    def submit(self) -> bool:
        """Save the form.

        The visible Save button sits outside the form element (same as the
        list editor), so clicking it through Playwright is unreliable;
        requestSubmit() hands off to the site's own AJAX submit handler,
        which is the only path proven to save.
        """
        submitted: bool = self.page.evaluate(_SUBMIT_JS)
        return submitted

    def landed(self) -> bool:
        """True when the save actually took.

        A submit that "succeeded" proves nothing: a validation error or a
        Cloudflare interstitial leaves the form open while the call reports
        success -- and posted_at would then hide the review forever.

        Raises:
            BotChallengeError: Cloudflare served an interstitial.
        """
        self.page.raise_if_challenged()
        still_open = self._textarea()
        return not (still_open.count() > 0 and still_open.is_visible())

    def entry_url(self) -> str | None:
        """Where the saved entry lives, for recording against the review."""
        try:
            current = self.page.url
            if "/film/" in current:
                slug = current.split("/film/")[1].strip("/").split("/")[0]
                return f"https://letterboxd.com/{self.username}/film/{slug}/"
        except Exception:
            pass
        return None
