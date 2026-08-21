from __future__ import annotations

import os
from dataclasses import dataclass

import pytest

from lawcorpus.storage.raw_store import get_raw, put_raw


@dataclass
class _FakeSettings:
    raw_s3_endpoint: str = ""
    raw_s3_bucket: str = "lawcorpus-raw"
    raw_s3_access_key: str = ""
    raw_s3_secret_key: str = ""
    raw_dir: str = "/tmp"


@pytest.mark.asyncio
async def test_put_raw_falls_back_to_fs_when_s3_not_configured(tmp_path):
    settings = _FakeSettings(raw_dir=str(tmp_path))

    uri = await put_raw(settings, "statutes/소득세법.xml", b"<law/>")

    assert uri == f"file://{tmp_path}/statutes/소득세법.xml"
    assert (tmp_path / "statutes/소득세법.xml").read_bytes() == b"<law/>"


@pytest.mark.asyncio
async def test_get_raw_reads_back_fs_uri(tmp_path):
    settings = _FakeSettings(raw_dir=str(tmp_path))
    uri = await put_raw(settings, "x.xml", b"hello")

    content = await get_raw(settings, uri)

    assert content == b"hello"


@pytest.mark.asyncio
async def test_get_raw_rejects_unknown_scheme():
    settings = _FakeSettings()

    with pytest.raises(ValueError, match="알 수 없는"):
        await get_raw(settings, "ftp://nope")


@pytest.mark.asyncio
async def test_get_raw_s3_uri_without_s3_config_raises():
    settings = _FakeSettings(raw_s3_endpoint="")

    with pytest.raises(RuntimeError, match="S3 설정"):
        await get_raw(settings, "s3://lawcorpus-raw/x.xml")


@pytest.mark.asyncio
async def test_put_raw_s3_roundtrip_against_real_minio():
    """실제 MinIO에 연결되면 S3 경로를 타는지 확인하는 스모크 테스트.

    자격증명은 환경변수로만 받는다(레포에 평문 보관 금지) — LAWCORPUS_RAW_S3_ENDPOINT/
    ACCESS_KEY/SECRET_KEY가 없거나 mac-server(intermittent)가 다운이면 skip한다.
    """
    endpoint = os.environ.get("LAWCORPUS_RAW_S3_ENDPOINT")
    access_key = os.environ.get("LAWCORPUS_RAW_S3_ACCESS_KEY")
    secret_key = os.environ.get("LAWCORPUS_RAW_S3_SECRET_KEY")
    if not (endpoint and access_key and secret_key):
        pytest.skip("LAWCORPUS_RAW_S3_* 환경변수 미설정 — 실 MinIO 스모크 테스트 건너뜀")

    settings = _FakeSettings(raw_s3_endpoint=endpoint, raw_s3_access_key=access_key, raw_s3_secret_key=secret_key)
    try:
        uri = await put_raw(settings, "smoke-test/ping.txt", b"ping")
    except Exception:
        pytest.skip("MinIO에 연결할 수 없음 — intermittent 호스트")

    assert uri.startswith("s3://lawcorpus-raw/")
    content = await get_raw(settings, uri)
    assert content == b"ping"
