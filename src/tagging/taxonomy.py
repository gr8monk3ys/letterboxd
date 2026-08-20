"""The controlled tag vocabulary.

Letterboxd tags are free text, which is how a list here once accumulated
forty single-use junk tags: a tag used once is worse than no tag, because
it adds a sidebar entry that leads to a page of one film. So tagging goes
through a fixed vocabulary, organised by facet, and anything outside it
is dropped rather than stored.

Facets exist so a film picks up tags along different axes (how it was
made, how it felt, what it is about) instead of three synonyms for the
same idea.
"""

import re

# Keep this small enough that every tag earns its place. A tag is worth
# adding only if it would plausibly group a dozen films in this library.
FACETS: dict[str, tuple[str, ...]] = {
    # How it was made, and what stands out about the craft
    "craft": (
        "cinematography",
        "score",
        "sound-design",
        "editing",
        "production-design",
        "costume-design",
        "practical-effects",
        "long-takes",
        "one-location",
        "ensemble-cast",
        "career-best-performance",
    ),
    # How it feels to sit through
    "mood": (
        "devastating",
        "comforting",
        "unsettling",
        "feel-good",
        "slow-burn",
        "tense",
        "hypnotic",
        "hilarious",
        "melancholy",
        "cathartic",
        "bleak",
    ),
    # What it is actually about
    "theme": (
        "coming-of-age",
        "grief",
        "class",
        "memory",
        "loneliness",
        "obsession",
        "revenge",
        "family",
        "identity",
        "faith",
        "war",
        "love-story",
        "friendship",
        "mortality",
        "addiction",
    ),
    # Form and format
    "form": (
        "animation",
        "anime",
        "silent",
        "black-and-white",
        "documentary",
        "musical",
        "short-film",
        "minimal-dialogue",
        "non-linear",
        "anthology",
        "sci-fi",
        "horror",
        "noir",
        "western",
    ),
    # Where it sits in film history
    "movement": (
        "french-new-wave",
        "italian-neorealism",
        "new-hollywood",
        "german-expressionism",
        "japanese-classic",
        "korean-cinema",
        "hong-kong-cinema",
        "iranian-cinema",
        "spaghetti-western",
    ),
    # This viewer's relationship to the film
    "canon": (
        "all-timer",
        "blind-spot",
        "underseen",
        "rewatchable",
        "debut-feature",
        "directors-best",
    ),
}

# Common ways the same idea gets written, mapped onto the canonical tag.
# The model reaches for these; resolving beats discarding.
ALIASES: dict[str, str] = {
    "b&w": "black-and-white",
    "bw": "black-and-white",
    "monochrome": "black-and-white",
    "science-fiction": "sci-fi",
    "scifi": "sci-fi",
    "film-noir": "noir",
    "tearjerker": "devastating",
    "heartbreaking": "devastating",
    "comfort": "comforting",
    "comfort-film": "comforting",
    "funny": "hilarious",
    "comedy": "hilarious",
    "creepy": "unsettling",
    "disturbing": "unsettling",
    "soundtrack": "score",
    "music": "score",
    "visuals": "cinematography",
    "visually-stunning": "cinematography",
    "cinematography-porn": "cinematography",
    "acting": "career-best-performance",
    "performance": "career-best-performance",
    "one-take": "long-takes",
    "single-location": "one-location",
    "masterpiece": "all-timer",
    "favorite": "all-timer",
    "favourite": "all-timer",
    "classic": "all-timer",
    "hidden-gem": "underseen",
    "overlooked": "underseen",
    "first-feature": "debut-feature",
    "debut": "debut-feature",
    "coming-of-age-story": "coming-of-age",
    "growing-up": "coming-of-age",
    "death": "mortality",
    "loss": "grief",
    "romance": "love-story",
    "dreamlike": "hypnotic",
    "surreal": "hypnotic",
    "depressing": "bleak",
    "slowburn": "slow-burn",
    "slow": "slow-burn",
    "no-dialogue": "minimal-dialogue",
    "quiet": "minimal-dialogue",
    "animated": "animation",
    "doc": "documentary",
    "korean": "korean-cinema",
    "japanese": "japanese-classic",
    "iranian": "iranian-cinema",
    "kurosawa": "japanese-classic",
    "nouvelle-vague": "french-new-wave",
    "neorealism": "italian-neorealism",
}

# A film carrying more than a handful of tags is indexing noise, not
# signal, and Letterboxd shows them all in the sidebar.
MAX_TAGS = 4


def canonical_tags() -> tuple[str, ...]:
    """Every tag in the vocabulary, flattened."""
    return tuple(tag for tags in FACETS.values() for tag in tags)


def normalize_tag(raw: str) -> str:
    """Reduce a written tag to the vocabulary's spelling conventions."""
    text = raw.strip().lower().lstrip("#")
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-{2,}", "-", text)
    return text.strip("-")


def validate_tags(raw_tags: list[str]) -> list[str]:
    """Keep only vocabulary tags, resolving aliases and capping the count.

    Order is preserved so the suggester's ranking survives, and anything
    invented is dropped silently: a junk tag must never reach the account.
    """
    allowed = set(canonical_tags())
    result: list[str] = []

    for raw in raw_tags:
        tag = normalize_tag(raw)
        tag = ALIASES.get(tag, tag)
        if tag in allowed and tag not in result:
            result.append(tag)
        if len(result) == MAX_TAGS:
            break

    return result


def describe_taxonomy() -> str:
    """The vocabulary as prompt text, grouped by facet."""
    lines = []
    for facet, tags in FACETS.items():
        lines.append(f"{facet}: {', '.join(tags)}")
    return "\n".join(lines)
