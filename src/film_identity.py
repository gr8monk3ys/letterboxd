"""The one rule for deciding whether two records mean the same film.

The export identifies films by opaque `boxd.it` URLs (`https://boxd.it/103U`)
while scraped pages carry readable slugs (`parasite`), so those can never be
compared directly. Worse, the `reviews` table has no film URI at all: it keys
on `review_uri` and can only be matched to a film by name and year.

Title+year is therefore the only shared identity, and it needs normalizing --
casing, stray whitespace and a year arriving as `"2021"` rather than `2021`
all split one film into two.

This module exists because that rule used to be written nine times. Six were
near-identical Python copies; two were SQL joins with no normalization at all,
which disagreed with the Python ones on case, on whitespace, and on NULL
years. The disagreement was not theoretical: the review generator used the
SQL rule and so drafted AI reviews for films the user had already reviewed by
hand, which is exactly what the campaign module's "a human review is never
touched" invariant promises cannot happen.

Two callers deliberately do *not* use this and should not be folded in:

- `recommend/prioritize.py` `_match_key` strips leading articles and all
  punctuation, because it matches titles the *model* wrote back against the
  batch it was given. That is fuzzy matching, a different job with a
  different tolerance for false positives.
- `utils/tmdb.py` `_make_key` builds a cache key, not an identity.
"""


def film_key(title: str | None, year: int | str | None) -> tuple[str, int | None]:
    """Build the identity used to compare films across data sources.

    Titles are normalized so casing and stray whitespace do not split a film
    in two. Years are coerced to int, because the same film arrives as `2021`
    from a database column with INTEGER affinity and as `"2021"` from JSON, a
    scraper dict or a form post.

    A missing year is a value, not an absence: two records that both lack a
    year and share a title are the same film. That is the one place SQL
    equality cannot express the rule, since `f.year = r.year` is never true
    when both are NULL.
    """
    normalized = (title or "").strip().lower()
    if year is None or year == "":
        return (normalized, None)
    try:
        return (normalized, int(year))
    except (TypeError, ValueError):
        # An unparseable year is closer to "unknown" than to a match against
        # some other film that happens to share the title.
        return (normalized, None)
