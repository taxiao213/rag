"""鉴权与敏感值加密。

- API Key 头校验（查询级 / 管理级两级）
- settings 表中云 API Key 的 Fernet 加解密（密钥由 APP_SECRET 派生）
"""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

from app.config import get_settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

# 支持的上传扩展名白名单（Phase 1 范围，视频格式 Phase 3 开启解析）
ALLOWED_EXTENSIONS = {
    "pdf",
    "docx",
    "txt",
    "md",
    "png",
    "jpg",
    "jpeg",
    "webp",
    "xlsx",
    "pptx",
    # Phase 3 视频
    "mp4",
    "mov",
    "avi",
    "mkv",
}


def require_query_key(key: str | None = Security(api_key_header)) -> str:
    s = get_settings()
    if not s.auth_enabled:
        return "auth-disabled"
    if key != s.api_key_query and key != s.api_key_admin:
        raise HTTPException(status_code=401, detail="无效的 API Key")
    return key


def require_admin_key(key: str | None = Security(api_key_header)) -> str:
    s = get_settings()
    if not s.auth_enabled:
        return "auth-disabled"
    if key != s.api_key_admin:
        raise HTTPException(status_code=403, detail="需要管理级 API Key")
    return key


def _fernet() -> Fernet:
    """由 APP_SECRET 派生 32 字节密钥（sha256），保证固定 secret 下加密可复现。"""
    digest = hashlib.sha256(get_settings().app_secret.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_secret(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as e:
        raise ValueError("密钥解密失败：APP_SECRET 与加密时使用的不同") from e


def mask_secret(plaintext: str) -> str:
    """返回尾 4 位掩码形式，用于前端展示。"""
    return "****" + plaintext[-4:] if len(plaintext) >= 4 else "****"


def validate_upload(filename: str, size_bytes: int) -> str:
    """校验扩展名白名单与大小上限，返回规范化扩展名。校验失败抛 HTTPException。"""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=f"不支持的文件类型 .{ext}，允许：{', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )
    max_bytes = get_settings().upload_max_mb * 1024 * 1024
    if size_bytes > max_bytes:
        raise HTTPException(
            status_code=413, detail=f"文件超过大小上限 {get_settings().upload_max_mb}MB"
        )
    return ext
