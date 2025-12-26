from __future__ import annotations
import textwrap

def normalize_caption(md: str) -> str:
    """
    Normalize caption markdown for frontend consumption.

    Why:
    - Many captions are written with triple-quoted strings, which often introduce
      indentation and accidental code blocks in Markdown.
    - We want stable, renderer-friendly markdown assets.

    Policy (v1):
    - Dedent common indentation
    - Strip ALL leading whitespace per line (prevents accidental code blocks)
    - Trim outer whitespace
    """
    if md is None:
        return ""

    md = md.replace("\r\n", "\n")
    md = textwrap.dedent(md)

    # Strip leading whitespace on every line (aggressive, but correct for our captions)
    md = "\n".join(line.lstrip() for line in md.splitlines())

    return md.strip() + "\n"
