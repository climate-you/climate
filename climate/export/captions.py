from __future__ import annotations
import textwrap


def normalize_caption(md: str) -> str:
    """
    Normalize caption markdown for frontend consumption.
    ...
    """
    if md is None:
        return ""

    md = md.replace("\r\n", "\n")
    md = textwrap.dedent(md)

    # Strip leading whitespace on every line (aggressive, but correct for our captions)
    md = "\n".join(line.lstrip() for line in md.splitlines())

    return md.strip() + "\n"


def caption_md_to_json(
    md: str,
    *,
    title: str | None = None,
    header: str | None = None,
    source: str | None = None,
    url: str | None = None,
) -> dict:
    """
    Phase-1 caption schema (v1):
    - Keep markdown in `description` so we can migrate the web renderer gradually.
    - Add structured fields for future slide layout (title/header/source/url).

    The frontend can keep using *.caption.md for now.
    """
    return {
        "version": 1,
        "title": title or "",
        "header": header or "",
        "description": normalize_caption(md),
        "source": source or "",
        "url": url or "",
    }
