"""Line-level diff counting. Pure functions, no I/O."""

from difflib import SequenceMatcher


def split_lines(text: str) -> list[str]:
    """Split text into comparable lines.

    Trailing whitespace is stripped per line and trailing blank lines are
    dropped, so an editor leaving empty paragraphs at the end of a document
    does not register as activity.
    """
    lines = [line.rstrip() for line in text.splitlines()]
    while lines and not lines[-1]:
        lines.pop()
    return lines


def count_changes(old_lines: list[str], new_lines: list[str]) -> tuple[int, int]:
    """Return (added, removed) between two versions of a document.

    A replacement counts on both sides, so a rewrite that keeps the line count
    constant reads as `+n −n` rather than as no change at all.
    """
    added = 0
    removed = 0

    # autojunk=False matters: on sequences longer than 200 items SequenceMatcher
    # otherwise treats frequently repeated lines (blank lines, in a real
    # document) as junk and skips them, which silently distorts the counts.
    matcher = SequenceMatcher(a=old_lines, b=new_lines, autojunk=False)

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "insert":
            added += j2 - j1
        elif tag == "delete":
            removed += i2 - i1
        elif tag == "replace":
            added += j2 - j1
            removed += i2 - i1

    return added, removed
