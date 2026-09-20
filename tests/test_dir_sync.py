"""目录同步扫描的纯函数测试：文件遍历过滤、hash、路径校验。"""

import os

from app.sync.dir_sync import iter_sync_files, sha256_file


def _touch(path, content: bytes = b"x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def test_iter_sync_files_filters_by_whitelist(tmp_path):
    _touch(tmp_path / "a.pdf")
    _touch(tmp_path / "b.txt")
    _touch(tmp_path / "c.png")
    _touch(tmp_path / "d.exe")  # 非白名单
    _touch(tmp_path / "noext")  # 无扩展名
    _touch(tmp_path / ".hidden.pdf")  # 隐藏文件
    _touch(tmp_path / ".git" / "e.pdf")  # 隐藏目录

    found = [p.name for p in iter_sync_files(str(tmp_path))]
    assert sorted(found) == ["a.pdf", "b.txt", "c.png"]


def test_iter_sync_files_recursive(tmp_path):
    _touch(tmp_path / "sub" / "deep" / "doc.docx")
    _touch(tmp_path / "top.md")

    found = [p.name for p in iter_sync_files(str(tmp_path))]
    assert sorted(found) == ["doc.docx", "top.md"]


def test_iter_sync_files_skips_oversized(tmp_path, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "upload_max_mb", 0)  # 上限 0MB → 全部超限
    _touch(tmp_path / "big.pdf", b"x" * 1024)
    assert iter_sync_files(str(tmp_path)) == []


def test_sha256_file_stable(tmp_path):
    f = tmp_path / "a.txt"
    _touch(f, b"hello")
    assert sha256_file(f) == sha256_file(f)
    _touch(f, b"world")
    import hashlib

    assert sha256_file(f) == hashlib.sha256(b"world").hexdigest()
