from app.utils.line_diff import count_changes, split_lines


def test_pure_insertion():
    assert count_changes(["a", "b"], ["a", "b", "c", "d"]) == (2, 0)


def test_pure_deletion():
    assert count_changes(["a", "b", "c"], ["a"]) == (0, 2)


def test_replacement_counts_both_sides():
    assert count_changes(["a", "b", "c"], ["a", "x", "c"]) == (1, 1)


def test_identical_content_is_no_change():
    assert count_changes(["a", "b"], ["a", "b"]) == (0, 0)


def test_full_rewrite_at_constant_length():
    """The case a net line count would hide: same length, everything different."""
    old = [f"old line {i}" for i in range(50)]
    new = [f"new line {i}" for i in range(50)]
    assert count_changes(old, new) == (50, 50)


def test_empty_inputs():
    assert count_changes([], []) == (0, 0)
    assert count_changes([], ["a", "b"]) == (2, 0)
    assert count_changes(["a", "b"], []) == (0, 2)


def test_large_repetitive_document_is_not_treated_as_junk():
    """SequenceMatcher's autojunk heuristic must be off, or popular lines are ignored."""
    old = ["" for _ in range(300)] + ["real content"]
    new = ["" for _ in range(300)] + ["different content"]
    assert count_changes(old, new) == (1, 1)


def test_split_lines_strips_trailing_whitespace():
    assert split_lines("a   \nb\t\n") == ["a", "b"]


def test_split_lines_drops_trailing_blank_lines():
    assert split_lines("a\nb\n\n\n\n") == ["a", "b"]


def test_split_lines_keeps_interior_blank_lines():
    assert split_lines("a\n\nb") == ["a", "", "b"]


def test_split_lines_on_empty_text():
    assert split_lines("") == []
    assert split_lines("\n\n\n") == []
