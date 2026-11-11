"""BM25 辅助纯函数测试：bigram 化与 tsquery 组装。"""

from app.indexing.bm25_store import build_tsquery, to_bigrams


def test_to_bigrams_chinese_windows():
    # 三字连续段 → 2 个 bigram；ASCII 单词原样小写
    assert to_bigrams("思路") == "思路"
    assert to_bigrams("选品思路") == "选品 品思 思路"
    assert to_bigrams("KB检索") == "kb 检索"


def test_build_tsquery_default_is_and():
    assert build_tsquery("选品 思路") == "选品 & 思路"


def test_build_tsquery_loose_or_mode():
    assert build_tsquery("选品 思路", match_all=False) == "选品 | 思路"


def test_build_tsquery_single_term():
    assert build_tsquery("品牌", match_all=False) == "品牌"
