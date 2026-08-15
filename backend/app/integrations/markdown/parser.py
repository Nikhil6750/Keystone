"""Deterministic, safe parsing of one Markdown note's raw text into a
`MarkdownNote`.

**Whole-file content hash, computed here.** `content_hash` is
`sha256(raw_text)` over the *entire* decoded file (frontmatter included)
-- never the mtime, and never caller-suppliable. Two parses of identical
bytes always produce an identical `MarkdownNote` (mtime aside).

**Safe YAML only.** Frontmatter is loaded with `yaml.safe_load`, which
cannot construct arbitrary Python objects -- a frontmatter block using an
unsafe tag (e.g. `!!python/object/apply:...`) raises `yaml.YAMLError`,
caught here and treated as "no frontmatter," never re-raised, never
executed. A frontmatter block that parses to something other than a
mapping (a bare list, a scalar) is treated the same way. Only four fields
are ever extracted from a successfully-parsed mapping -- `title`,
`description`, `tags`, `aliases` -- everything else in that mapping,
however deeply nested, is discarded; nothing here ever exposes an
arbitrary `dict[str, Any]` frontmatter blob.

**Does not execute anything.** Headings and links are recognized by plain
regular expressions over already-decoded text; fenced code blocks
(`` ``` `` / `~~~`) are tracked and skipped for both, so example headings
or example links inside a documentation code sample are never mistaken
for real document structure. No Markdown renderer, no HTML parser, no
code execution of any kind.

**Not a chunker.** `headings` is a flat structural summary (used only for
`title` fallback and for representing document structure) -- it does not
split `content` into retrievable pieces. That remains exclusively
`app.engine.knowledge.chunking.chunk_document`'s responsibility.
"""

import hashlib
import re
from pathlib import PurePosixPath

import yaml

from app.integrations.markdown.errors import NoteParseError
from app.integrations.markdown.models import (
    MarkdownFrontmatter,
    MarkdownHeading,
    MarkdownLink,
    MarkdownLinkKind,
    MarkdownNote,
)

_FRONTMATTER_RE = re.compile(r"\A---[ \t]*\r?\n(.*?\n)?---[ \t]*\r?\n?", re.DOTALL)
_FENCE_RE = re.compile(r"^(`{3,}|~{3,})")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_MD_LINK_RE = re.compile(r"(?<!!)\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_EXTERNAL_TARGET_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")


def _content_hash(raw_text: str) -> str:
    return hashlib.sha256(raw_text.encode("utf-8")).hexdigest()


def _split_frontmatter(raw_text: str) -> tuple[str, str]:
    """`(frontmatter_yaml_text, body)`. `frontmatter_yaml_text` is `""` if
    `raw_text` does not open with a `---` delimiter line, or if no closing
    `---` line is found anywhere afterward -- in either case the entire
    input is treated as `body`, unmodified."""
    match = _FRONTMATTER_RE.match(raw_text)
    if not match:
        return "", raw_text
    return match.group(1) or "", raw_text[match.end() :]


def _load_frontmatter_mapping(yaml_text: str) -> dict[object, object]:
    if not yaml_text.strip():
        return {}
    try:
        loaded: object = yaml.safe_load(yaml_text)
    except yaml.YAMLError:
        return {}
    if not isinstance(loaded, dict):
        return {}
    return loaded


def _normalize_string_list(value: object) -> tuple[str, ...]:
    items: list[str] = []
    if isinstance(value, str):
        items = [part.strip() for part in value.split(",")]
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, str):
                items.append(item.strip())
    return tuple(sorted({item for item in items if item}))


def _build_frontmatter(raw: dict[object, object]) -> MarkdownFrontmatter:
    title_value = raw.get("title")
    title = title_value.strip() if isinstance(title_value, str) and title_value.strip() else None
    description_value = raw.get("description")
    description = (
        description_value.strip()
        if isinstance(description_value, str) and description_value.strip()
        else None
    )
    return MarkdownFrontmatter(
        title=title,
        description=description,
        tags=_normalize_string_list(raw.get("tags")),
        aliases=_normalize_string_list(raw.get("aliases")),
    )


def iter_unfenced_lines(body: str) -> list[tuple[str, bool]]:
    """Every line of `body` paired with whether it falls inside a fenced
    code block (the fence delimiter lines themselves are marked
    in-fence). Shared with `app.integrations.obsidian.parser` so wikilink
    extraction gets the same "never parsed inside a code block" guarantee
    as generic heading/link extraction, without a second fence-tracking
    implementation."""
    result: list[tuple[str, bool]] = []
    in_fence = False
    for line in body.splitlines():
        if _FENCE_RE.match(line.strip()):
            in_fence = not in_fence
            result.append((line, True))
            continue
        result.append((line, in_fence))
    return result


def _extract_headings(body: str) -> tuple[MarkdownHeading, ...]:
    headings: list[MarkdownHeading] = []
    for line, fenced in iter_unfenced_lines(body):
        if fenced:
            continue
        match = _HEADING_RE.match(line)
        if match:
            headings.append(MarkdownHeading(level=len(match.group(1)), text=match.group(2)))
    return tuple(headings)


def _is_external_target(target: str) -> bool:
    return bool(_EXTERNAL_TARGET_RE.match(target))


def _extract_links(body: str) -> tuple[MarkdownLink, ...]:
    links: list[MarkdownLink] = []
    for line, fenced in iter_unfenced_lines(body):
        if fenced:
            continue
        for match in _MD_LINK_RE.finditer(line):
            target = match.group(2)
            kind = (
                MarkdownLinkKind.EXTERNAL
                if _is_external_target(target)
                else MarkdownLinkKind.RELATIVE
            )
            links.append(MarkdownLink(text=match.group(1), target=target, kind=kind))
    return tuple(links)


def _derive_title_from_filename(relative_path: str) -> str:
    stem = PurePosixPath(relative_path).stem
    normalized = re.sub(r"[-_]+", " ", stem)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized.title() if normalized else stem


def parse_markdown_note(
    relative_path: str, raw_text: str, *, mtime: float | None = None
) -> MarkdownNote:
    """Parse one note's already-decoded raw text into a `MarkdownNote`.

    Raises `NoteParseError` only when the note has no usable body left
    after frontmatter is removed (an empty or frontmatter-only file) --
    the sole condition this function treats as unrecoverable. Malformed
    YAML never raises; it degrades to an empty `MarkdownFrontmatter`."""
    content_hash = _content_hash(raw_text)
    frontmatter_yaml, body = _split_frontmatter(raw_text)
    frontmatter = _build_frontmatter(_load_frontmatter_mapping(frontmatter_yaml))

    if not body.strip():
        raise NoteParseError("note has no body content after removing frontmatter")

    headings = _extract_headings(body)
    links = _extract_links(body)

    title = frontmatter.title
    if not title:
        h1 = next((h.text for h in headings if h.level == 1), None)
        title = h1 or (headings[0].text if headings else None)
    if not title:
        title = _derive_title_from_filename(relative_path)

    return MarkdownNote(
        relative_path=relative_path,
        title=title,
        frontmatter=frontmatter,
        headings=headings,
        links=links,
        content=body,
        content_hash=content_hash,
        mtime=mtime,
    )


__all__ = ["iter_unfenced_lines", "parse_markdown_note"]
