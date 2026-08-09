"""`[[wikilink]]` syntax extraction -- the only place in Stage 6B that
knows this syntax exists.

Supports `[[Note]]`, `[[Note|Alias]]`, `[[folder/Note]]`,
`[[Note#Heading]]`, and `[[Note#Heading|Alias]]`. Reuses `app.
integrations.markdown.parser.iter_unfenced_lines` for fence tracking so a
`[[...]]` example inside a documentation code block is never mistaken for
a real link -- the same guarantee generic heading/link extraction already
gets, not a second implementation of it.
"""

import re

from app.integrations.markdown.parser import iter_unfenced_lines
from app.integrations.obsidian.models import ObsidianWikiLink

_WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#([^\]|]+))?(?:\|([^\]]+))?\]\]")


def parse_wikilinks(body: str) -> tuple[ObsidianWikiLink, ...]:
    """Every `[[...]]` reference in `body`, outside fenced code blocks, in
    document order. Never resolved against anything here -- see `app.
    integrations.obsidian.links` for resolution."""
    links: list[ObsidianWikiLink] = []
    for line, fenced in iter_unfenced_lines(body):
        if fenced:
            continue
        for match in _WIKILINK_RE.finditer(line):
            target = match.group(1).strip()
            if not target:
                continue
            heading = match.group(2).strip() if match.group(2) else None
            alias = match.group(3).strip() if match.group(3) else None
            links.append(
                ObsidianWikiLink(
                    target=target,
                    heading=heading or None,
                    alias=alias or None,
                )
            )
    return tuple(links)


__all__ = ["parse_wikilinks"]
