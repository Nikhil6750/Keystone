"""Tests for `app.integrations.markdown.parser`: frontmatter, headings,
tags, aliases, generic links, content hashing, and title fallback."""

import pytest

from app.integrations.markdown.errors import NoteParseError
from app.integrations.markdown.models import MarkdownLinkKind
from app.integrations.markdown.parser import parse_markdown_note

# --- title / headings ------------------------------------------------------------------


def test_title_from_frontmatter_wins() -> None:
    text = "---\ntitle: Explicit Title\n---\n# Heading One\n\nBody.\n"
    note = parse_markdown_note("doc.md", text)
    assert note.title == "Explicit Title"


def test_title_falls_back_to_first_h1() -> None:
    text = "## Not H1\n\n# Real Title\n\nBody.\n"
    note = parse_markdown_note("doc.md", text)
    assert note.title == "Real Title"


def test_title_falls_back_to_first_heading_of_any_level() -> None:
    text = "### Only A Level Three\n\nBody.\n"
    note = parse_markdown_note("doc.md", text)
    assert note.title == "Only A Level Three"


def test_title_falls_back_to_filename() -> None:
    text = "Just a body paragraph, no headings.\n"
    note = parse_markdown_note("some-notes_file.md", text)
    assert note.title == "Some Notes File"


def test_headings_extracted_in_order_and_skip_fenced_code() -> None:
    text = "# Real Heading\n\n```\n# Not a heading\n```\n\n## Second Real Heading\n"
    note = parse_markdown_note("doc.md", text)
    assert [h.text for h in note.headings] == ["Real Heading", "Second Real Heading"]
    assert [h.level for h in note.headings] == [1, 2]


# --- frontmatter -------------------------------------------------------------------------


def test_frontmatter_tags_and_aliases_normalized_from_lists() -> None:
    text = "---\ntitle: T\ntags: [beta, alpha, alpha]\naliases: [Second, First]\n---\nBody.\n"
    note = parse_markdown_note("doc.md", text)
    assert note.frontmatter.tags == ("alpha", "beta")
    assert note.frontmatter.aliases == ("First", "Second")


def test_frontmatter_tags_from_comma_separated_string() -> None:
    text = "---\ntags: alpha, beta, alpha\n---\nBody.\n"
    note = parse_markdown_note("doc.md", text)
    assert note.frontmatter.tags == ("alpha", "beta")


def test_frontmatter_description_extracted() -> None:
    text = "---\ndescription: A short summary.\n---\nBody.\n"
    note = parse_markdown_note("doc.md", text)
    assert note.frontmatter.description == "A short summary."


def test_frontmatter_unsupported_fields_are_dropped() -> None:
    text = "---\ntitle: T\nnested:\n  secret: value\ncustom_field: 123\n---\nBody.\n"
    note = parse_markdown_note("doc.md", text)
    assert note.frontmatter.title == "T"
    # Only the four documented fields are ever exposed.
    assert note.frontmatter.description is None


def test_no_frontmatter_delimiter_means_whole_text_is_body() -> None:
    text = "# Title\n\nNo frontmatter here.\n"
    note = parse_markdown_note("doc.md", text)
    assert note.frontmatter == note.frontmatter.__class__()
    assert "No frontmatter here." in note.content


def test_malformed_yaml_frontmatter_degrades_gracefully() -> None:
    text = "---\ntitle: [unterminated\n---\n# Real Body\n\nContent.\n"
    note = parse_markdown_note("doc.md", text)
    assert note.frontmatter.title is None
    assert note.title == "Real Body"
    assert "Content." in note.content


def test_unsafe_yaml_tag_never_deserialized() -> None:
    text = '---\nfoo: !!python/object/apply:builtins.list ["x"]\n---\nBody.\n'
    note = parse_markdown_note("doc.md", text)
    assert note.frontmatter.tags == ()
    assert note.frontmatter.title is None


def test_frontmatter_that_is_not_a_mapping_is_ignored() -> None:
    text = "---\n- just\n- a\n- list\n---\nBody.\n"
    note = parse_markdown_note("doc.md", text)
    assert note.frontmatter.tags == ()


def test_empty_frontmatter_block() -> None:
    text = "---\n---\n# Title\n\nBody.\n"
    note = parse_markdown_note("doc.md", text)
    assert note.title == "Title"


# --- content hash ---------------------------------------------------------------------


def test_content_hash_is_whole_file_and_changes_with_frontmatter_only_edit() -> None:
    body = "---\ntags: [a]\n---\n# T\n\nSame body.\n"
    body_edited_tags = "---\ntags: [b]\n---\n# T\n\nSame body.\n"
    note_a = parse_markdown_note("doc.md", body)
    note_b = parse_markdown_note("doc.md", body_edited_tags)
    assert note_a.content_hash != note_b.content_hash


def test_content_hash_stable_for_identical_bytes() -> None:
    text = "# T\n\nBody.\n"
    note_a = parse_markdown_note("doc.md", text)
    note_b = parse_markdown_note("doc.md", text)
    assert note_a.content_hash == note_b.content_hash


def test_mtime_never_affects_content_hash_or_frontmatter() -> None:
    text = "# T\n\nBody.\n"
    note_a = parse_markdown_note("doc.md", text, mtime=1.0)
    note_b = parse_markdown_note("doc.md", text, mtime=999999.0)
    assert note_a.content_hash == note_b.content_hash
    assert note_a.frontmatter == note_b.frontmatter
    assert note_a.title == note_b.title


# --- empty content -----------------------------------------------------------------------


def test_empty_body_after_frontmatter_raises_note_parse_error() -> None:
    text = "---\ntitle: Only Frontmatter\n---\n\n\n"
    with pytest.raises(NoteParseError):
        parse_markdown_note("doc.md", text)


def test_fully_empty_file_raises_note_parse_error() -> None:
    with pytest.raises(NoteParseError):
        parse_markdown_note("doc.md", "")


# --- generic links --------------------------------------------------------------------------


def test_relative_markdown_links_are_represented() -> None:
    text = "# T\n\nSee [Architecture](architecture.md) and [API](docs/api.md).\n"
    note = parse_markdown_note("doc.md", text)
    targets = {link.target: link.kind for link in note.links}
    assert targets["architecture.md"] == MarkdownLinkKind.RELATIVE
    assert targets["docs/api.md"] == MarkdownLinkKind.RELATIVE


@pytest.mark.parametrize(
    "target",
    [
        "https://example.com/page",
        "http://example.com",
        "file:///etc/passwd",
        "mailto:someone@example.com",
    ],
)
def test_external_links_are_represented_but_marked_external(target: str) -> None:
    text = f"# T\n\n[Link]({target})\n"
    note = parse_markdown_note("doc.md", text)
    assert len(note.links) == 1
    assert note.links[0].kind == MarkdownLinkKind.EXTERNAL
    assert note.links[0].target == target


def test_links_inside_fenced_code_blocks_are_ignored() -> None:
    text = "# T\n\n```\n[Fake](fake.md)\n```\n\n[Real](real.md)\n"
    note = parse_markdown_note("doc.md", text)
    assert [link.target for link in note.links] == ["real.md"]


def test_image_embeds_are_not_treated_as_links() -> None:
    text = "# T\n\n![Alt text](image.png)\n"
    note = parse_markdown_note("doc.md", text)
    assert note.links == ()
