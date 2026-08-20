"""Propose tags for a film from the controlled vocabulary."""

import logging

from src.tagging.taxonomy import MAX_TAGS, describe_taxonomy, validate_tags

logger = logging.getLogger(__name__)

SYSTEM = (
    "You tag films for a personal Letterboxd account. You only ever use tags "
    "from the vocabulary you are given, and you prefer fewer, more accurate "
    "tags over filling the quota."
)


class TagSuggester:
    """Pick vocabulary tags for a film, given its review."""

    def __init__(self, provider):
        self.provider = provider

    def build_prompt(self, film: dict, review_text: str) -> str:
        return f"""Choose tags for "{film.get("name")}" ({film.get("year")}).

My review of it:
"{review_text}"

Pick from this vocabulary only, one line, comma separated:
{describe_taxonomy()}

Rules:
- At most {MAX_TAGS} tags, and only ones that genuinely apply
- Fewer is better; two right tags beat four vague ones
- Spread across different facets rather than four from one
- Never invent a tag or alter its spelling
- Reply with only the tags, no explanation"""

    def suggest(self, film: dict, review_text: str) -> list[str]:
        """Return validated tags for the film, or [] if none apply."""
        try:
            # The answer is a dozen tokens, but extended thinking draws
            # on the same budget: at 60 the thinking block consumed all
            # of it and the reply carried no text at all.
            reply = self.provider.generate(
                prompt=self.build_prompt(film, review_text),
                system=SYSTEM,
                max_tokens=500,
            )
        except Exception as e:
            logger.warning(f"Tag suggestion failed for {film.get('name')}: {e}")
            return []

        if not reply:
            return []

        # Replies arrive comma separated, sometimes as a bullet list
        parts = [piece.lstrip("-*• ") for line in reply.splitlines() for piece in line.split(",")]
        return validate_tags(parts)
