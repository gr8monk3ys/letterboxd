"""Generate AI-powered movie reviews that match your writing style."""

import argparse
import csv
import json
import logging
import random
import time
from datetime import datetime
from pathlib import Path

from tqdm import tqdm

from src.config import DATA_DIR, get_config, get_log_path
from src.data_processing.create_database import MovieDatabase
from src.providers import get_provider
from src.providers.base import VALID_PROVIDERS
from src.utils.errors import handle_exception
from src.utils.tmdb import TMDBClient, format_film_context

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(get_log_path("review_generation"), encoding="utf-8"),
        logging.StreamHandler(),
    ],
)

# Review tone presets with their guidelines and system prompts
TONE_PRESETS = {
    "casual": {
        "name": "Casual",
        "description": "Relaxed, conversational style (default)",
        "guidelines": """- Match my casual, conversational writing style from the examples
- Keep it between 2-4 sentences (50-150 words)
- Include a specific observation about the film
- Feel free to use humor, rhetorical questions, or witty remarks if it fits
- Don't be generic - make it feel personal
- No spoilers""",
        "system": "You are writing Letterboxd reviews in the user's personal style. "
        "Be casual, authentic, and specific. Match the tone and length of the examples.",
    },
    "snarky": {
        "name": "Snarky",
        "description": "Witty, sarcastic, and playfully critical",
        "guidelines": """- Be witty, sarcastic, and playfully critical
- Keep it between 2-4 sentences (50-150 words)
- Use sharp observations and clever wordplay
- Don't be mean-spirited, but don't hold back on humor
- Rhetorical questions and irony work well
- No spoilers""",
        "system": "You are a witty film critic writing snarky Letterboxd reviews. "
        "Be clever, use irony, and make sharp observations. Keep it fun, not mean.",
    },
    "thoughtful": {
        "name": "Thoughtful",
        "description": "Reflective and emotionally engaged",
        "guidelines": """- Be reflective and emotionally engaged
- Keep it between 3-5 sentences (75-200 words)
- Focus on themes, emotions, and what the film made you feel
- Connect the film to broader ideas or personal experience
- Be sincere and genuine in your observations
- No spoilers""",
        "system": "You are writing thoughtful, reflective Letterboxd reviews. "
        "Focus on emotional resonance, themes, and personal connection to the film.",
    },
    "brief": {
        "name": "Brief",
        "description": "Short and punchy, 1-2 sentences max",
        "guidelines": """- Keep it extremely brief: 1-2 sentences (15-50 words)
- Be punchy and memorable
- One strong observation or reaction
- No filler words
- No spoilers""",
        "system": "You are writing ultra-brief Letterboxd reviews. "
        "One or two punchy sentences max. Make every word count.",
    },
    "analytical": {
        "name": "Analytical",
        "description": "Film criticism style with technical observations",
        "guidelines": """- Write like a film critic with technical knowledge
- Keep it between 3-5 sentences (100-200 words)
- Discuss cinematography, direction, performances, or narrative structure
- Use film terminology appropriately
- Balance technical observation with accessibility
- No spoilers""",
        "system": "You are a knowledgeable film critic writing analytical Letterboxd reviews. "
        "Discuss craft elements like cinematography, direction, and performances.",
    },
}

# Valid tone names for CLI validation
VALID_TONES = list(TONE_PRESETS.keys())


class ReviewGenerator:
    # Which env var holds the key for each vendor. The provider classes fall
    # back to reading these themselves; this lets config supply one first.
    _KEY_ENV = {
        "anthropic": "anthropic_api_key",
        "openai": "openai_api_key",
        "gemini": "gemini_api_key",
    }

    def _api_key_for(self, provider_name: str) -> str:
        """The configured key for a vendor, or "" to let the provider look."""
        return str(getattr(self.config, self._KEY_ENV.get(provider_name, ""), "") or "")

    def _log_provider(self) -> None:
        logging.info(f"Generating with provider: {self.provider_name}")

    def __init__(self, tone: str | None = None, use_tmdb: bool = True, provider: str | None = None):
        self.config = get_config()

        # A typo in AI_PROVIDER should not take a whole batch down, so fall
        # back rather than raise. Same shape as the tone handling below.
        self.provider_name = provider or getattr(self.config, "ai_provider", "") or "anthropic"
        if self.provider_name not in VALID_PROVIDERS:
            logging.warning(f"Unknown provider '{self.provider_name}', using 'anthropic'")
            self.provider_name = "anthropic"
        self.provider = get_provider(
            self.provider_name, api_key=self._api_key_for(self.provider_name)
        )

        self.db = MovieDatabase(db_path=self.config.database_file)
        self.db.connect()
        self._style_examples: list[dict] | None = None

        # Set tone from parameter, env var, or default
        self.tone = tone or self.config.review_tone
        if self.tone not in VALID_TONES:
            logging.warning(f"Invalid tone '{self.tone}', using 'casual'")
            self.tone = "casual"

        self._log_provider()

        # Initialize TMDB client for richer film metadata
        self.use_tmdb = use_tmdb
        self.tmdb: TMDBClient | None = None
        if use_tmdb:
            self.tmdb = TMDBClient()
            if not self.tmdb.is_configured():
                logging.info("TMDB API key not configured, reviews will use basic film info")
                self.tmdb = None

    def get_tone_preset(self) -> dict:
        """Get the current tone preset configuration."""
        return TONE_PRESETS[self.tone]

    def _get_style_examples(self, count: int = 15, rating: float | None = None) -> list[dict]:
        """Get a sample of user's reviews for style matching.

        One-liners are part of the voice, so only empty scraps and
        multi-page outliers are excluded. When the target film's rating
        is known, examples rated within one star are preferred — the
        user's register (earnest vs. jokey) tracks how seriously they
        took the film, and rating is the recorded proxy for that.
        """
        if self._style_examples is None:
            all_reviews = self.db.get_user_reviews()
            good_reviews = [r for r in all_reviews if 10 <= len(r["review"]) <= 1000]
            self._style_examples = good_reviews

        pool = self._style_examples
        if len(pool) <= count:
            return pool
        if rating is not None:
            near = [
                r
                for r in pool
                if r.get("rating") is not None and abs(float(r["rating"]) - rating) <= 1.0
            ]
            if len(near) >= count:
                return random.sample(near, count)
            far = [r for r in pool if r not in near]
            return near + random.sample(far, count - len(near))
        return random.sample(pool, count)

    def _build_style_prompt(self, rating: float | None = None) -> str:
        """Build a prompt section with style examples from user's reviews."""
        examples = self._get_style_examples(15, rating=rating)
        if not examples:
            return ""

        prompt = "\n\nHere are examples of my previous reviews to match my style:\n"
        for ex in examples:
            rating_label = f"{ex['rating']}★" if ex["rating"] else "unrated"
            prompt += f'\n{ex["name"]} ({ex["year"]}) [{rating_label}]:\n"{ex["review"]}"\n'

        return prompt

    def generate_review(self, film: dict) -> str | None:
        """Generate a review for a single movie matching user's style."""
        try:
            title = film.get("name", "Unknown")
            year = film.get("year", "Unknown")
            rating = film.get("rating")

            rating_context = ""
            if rating:
                if float(rating) >= 4.5:
                    rating_context = "I loved this film."
                elif float(rating) >= 3.5:
                    rating_context = "I enjoyed this film."
                elif float(rating) >= 2.5:
                    rating_context = "This film was okay."
                else:
                    rating_context = "I didn't like this film much."

            # Fetch rich metadata from TMDB if available
            film_context = ""
            if self.tmdb:
                metadata = self.tmdb.get_film_metadata(title, year)
                if metadata:
                    film_context = format_film_context(metadata)
                    logging.debug(f"TMDB metadata for {title}: {film_context}")

            target_rating = float(rating) if rating else None
            style_examples = self._build_style_prompt(rating=target_rating)
            tone_preset = self.get_tone_preset()

            # Each call is independent, so without a concrete target the
            # model writes the same medium-length review every time.
            # Sampling a length from the user's real reviews (at this
            # rating) reproduces their natural spread of one-liners and
            # paragraphs across a batch.
            length_pool = self._get_style_examples(15, rating=target_rating)
            length_line = ""
            if length_pool:
                target_len = len(random.choice(length_pool)["review"])
                length_line = (
                    f"\n- Aim for about {target_len} characters, "
                    "the length of one of my typical reviews"
                )

            # Build prompt with optional TMDB context
            context_line = f"\nFilm info: {film_context}" if film_context else ""

            prompt = f"""Write a Letterboxd review for "{title}" ({year}).
{rating_context}{context_line}

Guidelines:
{tone_preset["guidelines"]}
- My real reviews are usually 1-3 sentences; never pad — a one-line reaction is fine
- Match how seriously the examples take their films; that is my register at this rating{length_line}
- Write only the review text, no title or rating
{style_examples}

Now write a review for "{title}" ({year}):"""

            # Vendor-specific error handling lives in the provider, which
            # logs and returns None rather than leaking one SDK's exception
            # types into this module.
            review = self.provider.generate(
                prompt=prompt,
                system=tone_preset["system"],
                max_tokens=300,
            )
            if review is not None:
                # Models sometimes return the review wrapped in quotation
                # marks; posted verbatim that reads as a formatting bug.
                for open_q, close_q in (('"', '"'), ("“", "”")):
                    if review.startswith(open_q) and review.endswith(close_q):
                        inner = review[1:-1]
                        if open_q not in inner and close_q not in inner:
                            review = inner.strip()
            return review

        except Exception as e:
            handle_exception(e, f"Error generating review for '{film.get('name')}'")
            return None

    def generate_reviews(
        self,
        limit: int | None = None,
        year: int | None = None,
        year_start: int | None = None,
        year_end: int | None = None,
        min_rating: float | None = None,
    ) -> int:
        """Generate reviews for films without reviews.

        Args:
            limit: Maximum number of reviews to generate (None for all)
            year: Filter to specific year
            year_start: Start of year range (inclusive)
            year_end: End of year range (inclusive)
            min_rating: Minimum rating filter

        Returns:
            Number of reviews generated
        """
        try:
            films = self.db.get_films_without_reviews(
                year=year,
                year_start=year_start,
                year_end=year_end,
                min_rating=min_rating,
            )

            if not films:
                logging.info("All films already have reviews!")
                return 0

            if limit:
                films = films[:limit]

            logging.info(f"Generating reviews for {len(films)} films...")

            # Show style info
            style_count = len(self._get_style_examples(100))
            logging.info(f"Using {style_count} of your reviews for style matching")

            generated = 0
            for film in tqdm(films, desc="Generating reviews"):
                review = self.generate_review(film)

                if review:
                    self.db.save_ai_review(
                        letterboxd_uri=film["letterboxd_uri"],
                        name=film["name"],
                        year=film["year"],
                        review=review,
                    )
                    generated += 1
                    logging.debug(f"Generated review for: {film['name']} ({film['year']})")

                # Rate limiting
                time.sleep(0.5)

            return generated

        finally:
            pass  # Keep connection open for potential follow-up calls

    def preview_review(self, film_name: str) -> str | None:
        """Generate a preview review for a specific film (doesn't save)."""
        # Find the film. films.rating is NULL in a real export; the score
        # lives in the ratings table, and the preview's sentiment follows it.
        self.db.cursor.execute(
            """
            SELECT f.letterboxd_uri, f.name, f.year,
                   COALESCE(rt.rating, f.rating) AS rating
            FROM films f
            LEFT JOIN ratings rt ON f.letterboxd_uri = rt.letterboxd_uri
            WHERE f.name LIKE ?
            """,
            (f"%{film_name}%",),
        )
        row = self.db.cursor.fetchone()
        if not row:
            return None

        film = dict(zip(["letterboxd_uri", "name", "year", "rating"], row))
        return self.generate_review(film)

    def export_reviews(self, format: str = "csv") -> Path | None:
        """Export AI-generated reviews to CSV or JSON.

        Args:
            format: Output format ('csv' or 'json')

        Returns:
            Path to the exported file, or None if no reviews to export
        """
        rows = self.db.get_ai_reviews()

        if not rows:
            logging.info("No AI reviews to export")
            return None

        columns = ["name", "year", "rating", "review", "generated_at", "letterboxd_uri"]
        reviews = [{k: r[k] for k in columns} for r in rows]

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        if format == "json":
            output_file = DATA_DIR / f"ai_reviews_{timestamp}.json"
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(reviews, f, indent=2, ensure_ascii=False)
        else:  # csv
            output_file = DATA_DIR / f"ai_reviews_{timestamp}.csv"
            with open(output_file, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=columns)
                writer.writeheader()
                writer.writerows(reviews)

        logging.info(f"Exported {len(reviews)} reviews to {output_file}")
        return output_file

    def close(self):
        """Close database and TMDB connections."""
        self.db.close()
        if self.tmdb:
            self.tmdb.close()


def build_arg_parser() -> "argparse.ArgumentParser":
    """The CLI surface, separated from main() so it can be tested."""
    parser = argparse.ArgumentParser(description="Generate AI reviews matching your style")
    parser.add_argument(
        "-n",
        "--limit",
        type=int,
        default=10,
        help="Maximum number of reviews to generate (default: 10)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Generate reviews for all unreviewed films",
    )
    parser.add_argument(
        "--preview",
        type=str,
        help="Preview a review for a specific film (doesn't save)",
    )
    parser.add_argument(
        "--export",
        choices=["csv", "json"],
        help="Export AI reviews to CSV or JSON file",
    )
    parser.add_argument(
        "--tone",
        choices=VALID_TONES,
        help=f"Review tone preset (choices: {', '.join(VALID_TONES)})",
    )
    parser.add_argument(
        "--list-tones",
        action="store_true",
        help="List available tone presets and exit",
    )
    parser.add_argument(
        "--provider",
        choices=VALID_PROVIDERS,
        help=(
            "AI vendor to generate with "
            f"(choices: {', '.join(VALID_PROVIDERS)}; default: anthropic, "
            "or the AI_PROVIDER env var)"
        ),
    )

    # Batch filtering options
    filter_group = parser.add_argument_group("batch filtering")
    filter_group.add_argument(
        "--year",
        type=int,
        help="Generate reviews only for films from a specific year (e.g., --year 2024)",
    )
    filter_group.add_argument(
        "--year-range",
        type=str,
        metavar="START-END",
        help="Generate reviews for films in a year range (e.g., --year-range 2020-2024)",
    )
    filter_group.add_argument(
        "--min-rating",
        type=float,
        help="Only generate reviews for films rated at least this high (e.g., 4.0)",
    )

    return parser


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()

    # Parse year range if provided
    year_start, year_end = None, None
    if args.year_range:
        try:
            parts = args.year_range.split("-")
            if len(parts) == 2:
                year_start = int(parts[0])
                year_end = int(parts[1])
            else:
                parser.error("--year-range must be in format START-END (e.g., 2020-2024)")
        except ValueError:
            parser.error("--year-range must contain valid years (e.g., 2020-2024)")

    # Handle --list-tones before creating generator
    if args.list_tones:
        print("\nAvailable review tone presets:\n")
        for tone_name, preset in TONE_PRESETS.items():
            default = " (default)" if tone_name == "casual" else ""
            print(f"  {tone_name}{default}")
            print(f"    {preset['description']}\n")
        print("Set tone via --tone flag or REVIEW_TONE env var")
        return

    generator = ReviewGenerator(tone=args.tone)

    try:
        if args.export:
            output = generator.export_reviews(format=args.export)
            if output:
                print(f"\nExported reviews to: {output}")
            else:
                print("\nNo AI reviews found to export. Generate some first with -n or --all")
        elif args.preview:
            tone_info = generator.get_tone_preset()
            print(f"\n=== Preview review for '{args.preview}' (tone: {tone_info['name']}) ===\n")
            review = generator.preview_review(args.preview)
            if review:
                print(review)
            else:
                print(f"Film '{args.preview}' not found in your watched list")
        else:
            # Show current stats
            counts = generator.db.get_review_count()
            tone_info = generator.get_tone_preset()
            print(
                f"\nFilms: {counts['total_films']} total, "
                f"{counts['user_reviewed']} reviewed by you, "
                f"{counts['ai_reviewed']} AI reviews, "
                f"{counts['unreviewed']} remaining"
            )
            print(f"Tone: {tone_info['name']} - {tone_info['description']}")

            # Show active filters
            filters_active = []
            if args.year:
                filters_active.append(f"year={args.year}")
            if year_start and year_end:
                filters_active.append(f"year range={year_start}-{year_end}")
            if args.min_rating:
                filters_active.append(f"min rating={args.min_rating}")
            if filters_active:
                print(f"Filters: {', '.join(filters_active)}")
            print()

            limit = None if args.all else args.limit
            generated = generator.generate_reviews(
                limit=limit,
                year=args.year,
                year_start=year_start,
                year_end=year_end,
                min_rating=args.min_rating,
            )

            if generated > 0:
                print(f"\nGenerated {generated} reviews!")
                print("Reviews stored in database (ai_reviews table)")
            else:
                print("\nNo reviews generated.")
    finally:
        generator.close()


if __name__ == "__main__":
    main()
