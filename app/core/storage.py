"""MinIO/S3 对象存储封装：上传、下载、删除、预签名 URL。"""

from functools import lru_cache

from minio import Minio

from app.config import get_settings


@lru_cache
def get_minio_client() -> Minio:
    s = get_settings()
    return Minio(
        s.minio_endpoint,
        access_key=s.minio_access_key,
        secret_key=s.minio_secret_key,
        secure=s.minio_secure,
    )


def ensure_bucket() -> None:
    client = get_minio_client()
    bucket = get_settings().minio_bucket
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)


async def put_object(storage_key: str, data: bytes, content_type: str) -> None:
    import io

    client = get_minio_client()
    ensure_bucket()
    client.put_object(
        get_settings().minio_bucket,
        storage_key,
        io.BytesIO(data),
        length=len(data),
        content_type=content_type,
    )


async def get_object(storage_key: str) -> bytes:
    client = get_minio_client()
    resp = client.get_object(get_settings().minio_bucket, storage_key)
    try:
        return resp.read()
    finally:
        resp.close()
        resp.release_conn()


def presigned_get_url(storage_key: str, expires_seconds: int = 3600) -> str:
    from datetime import timedelta

    client = get_minio_client()
    return client.presigned_get_object(
        get_settings().minio_bucket, storage_key, expires=timedelta(seconds=expires_seconds)
    )


def remove_object(storage_key: str) -> None:
    client = get_minio_client()
    client.remove_object(get_settings().minio_bucket, storage_key)
