"""Tests for `app.integrations.obsidian.parser.parse_wikilinks`: the
Obsidian-only `[[...]]` syntax (Stage 6B, section 10)."""

from app.integrations.obsidian.models import ObsidianWikiLink
from app.integrations.obsidian.parser import parse_wikilinks


def test_plain_wikilink() -> None:
    links = parse_wikilinks("See [[Note]] for details.")
    assert links == (ObsidianWikiLink(target="Note"),)


def test_wikilink_with_alias() -> None:
    links = parse_wikilinks("See [[Note|Alias]] for details.")
    assert links == (ObsidianWikiLink(target="Note", alias="Alias"),)


def test_wikilink_with_folder_path() -> None:
    links = parse_wikilinks("See [[folder/Note]] for details.")
    assert links == (ObsidianWikiLink(target="folder/Note"),)


def test_wikilink_with_heading() -> None:
    links = parse_wikilinks("See [[Note#Heading]] for details.")
    assert links == (ObsidianWikiLink(target="Note", heading="Heading"),)


def test_wikilink_with_heading_and_alias() -> None:
    links = parse_wikilinks("See [[Note#Heading|Alias]] for details.")
    assert links == (ObsidianWikiLink(target="Note", heading="Heading", alias="Alias"),)


def test_multiple_wikilinks_in_order() -> None:
    links = parse_wikilinks("[[First]] then [[Second]] then [[Third]]")
    assert [link.target for link in links] == ["First", "Second", "Third"]


def test_wikilinks_inside_fenced_code_blocks_are_ignored() -> None:
    text = "Real [[Real Note]] here.\n\n```\nExample [[Fake Note]] in docs.\n```\n"
    links = parse_wikilinks(text)
    assert links == (ObsidianWikiLink(target="Real Note"),)


def test_empty_target_is_ignored() -> None:
    links = parse_wikilinks("[[]]")
    assert links == ()


def test_no_wikilinks_returns_empty_tuple() -> None:
    assert parse_wikilinks("Just plain text, no links at all.") == ()


def test_wikilink_target_whitespace_is_stripped() -> None:
    links = parse_wikilinks("[[ Note With Spaces ]]")
    assert links == (ObsidianWikiLink(target="Note With Spaces"),)
