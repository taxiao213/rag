"""路径浏览（系统选择窗口）输出的解析测试。"""

from app.api.routes_paths import _parse_browse_output


def test_parse_browse_output_returns_stripped_path():
    assert _parse_browse_output("/Users/you/kb\n") == "/Users/you/kb"


def test_parse_browse_output_empty_means_cancelled():
    assert _parse_browse_output("") is None
    assert _parse_browse_output("  \n") is None


def test_parse_browse_output_keeps_spaces_in_path():
    assert _parse_browse_output("/Users/you/My Docs/note.md\n") == "/Users/you/My Docs/note.md"
