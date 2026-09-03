"""Set tags and descriptions on lists that already exist.

Distinct from create_list, which builds new lists: this pass fixes the
metadata on lists already on the account, so the whole profile shares one
tag vocabulary instead of ad-hoc per-list wording.
"""

import argparse
import json
import logging
from pathlib import Path
from typing import Any

from playwright.sync_api import Page

from src.tagging.taxonomy import MAX_TAGS, normalize_tag, validate_tags
from src.utils.logs import configure

logger = logging.getLogger(__name__)


def load_plan(path: Path) -> dict[str, dict]:
    """Read a slug-keyed curation plan, rejecting off-vocabulary tags.

    A junk tag in the plan is a typo, and applying it would put a
    single-use tag on the account, which is what the vocabulary exists to
    prevent. So this fails loudly rather than silently dropping it.
    """
    plan: dict[str, dict] = json.loads(Path(path).read_text())

    for slug, entry in plan.items():
        tags = entry.get("tags") or []
        kept = validate_tags(tags, include_list_kinds=True)
        unknown = [t for t in tags if normalize_tag(t) not in kept]
        if unknown:
            raise ValueError(f"{slug}: tags outside the vocabulary: {', '.join(unknown)}")
        if len(tags) > MAX_TAGS:
            raise ValueError(f"{slug}: {len(tags)} tags, more than the {MAX_TAGS} allowed")

    return plan


class ListCurator:
    """Edit an existing list's tags and description."""

    def __init__(self, username: str):
        self.username = username

    def _read_state(self, page: Page) -> dict:
        tags = page.evaluate(
            "() => [...document.querySelectorAll('#current-tags input[name=tag]')]"
            ".map(i => i.value)"
        )
        description = page.evaluate(
            "() => (document.querySelector('textarea[name=notes]') || {}).value || ''"
        )
        return {"tags": list(tags or []), "description": description or ""}

    def curate(
        self,
        page: Page,
        slug: str,
        tags: list[str] | None = None,
        description: str | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Apply tags and/or a description to one list.

        Tags replace whatever is there: the point of the pass is to swap
        ad-hoc tags for vocabulary ones. A description is only written
        when given, so a tag-only run cannot blank existing prose.
        """
        page.goto(
            f"https://letterboxd.com/{self.username}/list/{slug}/edit/",
            wait_until="domcontentloaded",
        )
        page.wait_for_timeout(1200)

        before = self._read_state(page)
        wanted_tags = list(tags) if tags is not None else before["tags"]
        wanted_desc = description if description is not None else before["description"]

        changed = wanted_tags != before["tags"] or wanted_desc != before["description"]
        result = {
            "slug": slug,
            "tags": wanted_tags,
            "description": wanted_desc,
            "changed": changed,
        }

        if dry_run or not changed:
            return result

        if tags is not None:
            # Replace the token list wholesale. Typing into the typeahead
            # races, so the hidden inputs are written directly instead.
            page.evaluate(
                """(wanted) => {
                    const box = document.querySelector('#current-tags');
                    if (!box) return false;
                    box.querySelectorAll('li.tag').forEach(li => li.remove());
                    for (const tag of wanted) {
                        const li = document.createElement('li');
                        li.className = 'tag';
                        const input = document.createElement('input');
                        input.type = 'hidden';
                        input.name = 'tag';
                        input.value = tag;
                        li.appendChild(input);
                        box.appendChild(li);
                    }
                    return true;
                }""",
                wanted_tags,
            )

        if description is not None:
            page.evaluate(
                """(text) => {
                    const box = document.querySelector('textarea[name=notes]');
                    if (!box) return false;
                    box.value = text;
                    box.dispatchEvent(new Event('input', {bubbles: true}));
                    return true;
                }""",
                description,
            )

        # The visible Save button sits outside the form, so only the
        # site's own submit handler actually persists anything.
        page.evaluate(
            """() => {
                const form = document.querySelector('input[name=name]').form;
                form.requestSubmit();
                return true;
            }"""
        )
        page.wait_for_timeout(3000)
        return result

    def run(self, page: Page, plan: dict[str, dict], dry_run: bool = False) -> int:
        """Curate every list in the plan, returning how many changed."""
        changed = 0
        for slug, entry in plan.items():
            result = self.curate(
                page,
                slug,
                tags=entry.get("tags"),
                description=entry.get("description"),
                dry_run=dry_run,
            )
            state = "would change" if dry_run else ("changed" if result["changed"] else "unchanged")
            logger.info(f"{slug}: {state} tags={result['tags']}")
            if result["changed"]:
                changed += 1
        return changed


def main() -> None:
    from playwright.sync_api import sync_playwright

    from src.config import get_config
    from src.utils.auth import login, open_browser

    configure("list_curation")

    parser = argparse.ArgumentParser(description="Set tags and descriptions on existing lists")
    parser.add_argument("--plan", required=True, type=Path, help="Slug-keyed JSON plan")
    parser.add_argument("--dry-run", action="store_true", help="Report without saving")
    args = parser.parse_args()

    plan = load_plan(args.plan)
    config = get_config()
    curator = ListCurator(username=config.username)

    print(f"\n{len(plan)} lists in the plan")

    with sync_playwright() as playwright:
        context, page = open_browser(playwright, config)
        try:
            if not login(page, config):
                logging.error("Login failed, aborting")
                return
            changed = curator.run(page, plan, dry_run=args.dry_run)
            verb = "would change" if args.dry_run else "changed"
            print(f"\n{verb} {changed} lists")
        finally:
            # An abandoned persistent profile keeps the browser's
            # SingletonLock and blocks every later run
            context.close()


if __name__ == "__main__":
    main()
