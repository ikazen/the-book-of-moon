"""원본(XML/PDF/HTML) 불변 보관. S3 호환(MinIO) 우선, LAWCORPUS_RAW_DIR fs 폴백.
mac-server(MinIO 호스트)가 intermittent라 S3 업로드 실패 시 로컬에 떨군다.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError


def _s3_client(settings) -> Any | None:
    if not settings.raw_s3_endpoint:
        return None
    return boto3.client(
        "s3",
        endpoint_url=settings.raw_s3_endpoint,
        aws_access_key_id=settings.raw_s3_access_key,
        aws_secret_access_key=settings.raw_s3_secret_key,
    )


def _fs_path(settings, key: str) -> Path:
    return Path(settings.raw_dir) / key


async def put_raw(settings, key: str, content: bytes) -> str:
    """content를 key(버킷/디렉터리 상대 경로)에 저장하고 실제 저장 위치를 URI로 반환한다.

    S3가 설정돼 있으면 우선 시도하고, 실패(mac-server 다운 등)하면 fs로 떨군다.
    """
    client = _s3_client(settings)
    if client is not None:
        try:
            await asyncio.to_thread(client.put_object, Bucket=settings.raw_s3_bucket, Key=key, Body=content)
            return f"s3://{settings.raw_s3_bucket}/{key}"
        except (BotoCoreError, ClientError):
            pass  # MinIO 다운 시 fs 폴백으로 넘어간다

    path = _fs_path(settings, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(path.write_bytes, content)
    return f"file://{path}"


async def get_raw(settings, raw_uri: str) -> bytes:
    """put_raw가 반환한 raw_uri(s3:// 또는 file://)로부터 원본을 읽어온다."""
    if raw_uri.startswith("s3://"):
        bucket, _, key = raw_uri.removeprefix("s3://").partition("/")
        client = _s3_client(settings)
        if client is None:
            raise RuntimeError(f"S3 설정 없이 s3:// URI를 읽을 수 없습니다: {raw_uri}")
        resp = await asyncio.to_thread(client.get_object, Bucket=bucket, Key=key)
        return await asyncio.to_thread(resp["Body"].read)
    if raw_uri.startswith("file://"):
        return await asyncio.to_thread(Path(raw_uri.removeprefix("file://")).read_bytes)
    raise ValueError(f"알 수 없는 raw_uri 형식: {raw_uri}")
