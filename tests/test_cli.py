from __future__ import annotations

import sys

import pytest


def _run_cli(monkeypatch, argv, apply_schema_stub):
    import lawcorpus.cli as cli_mod

    monkeypatch.setattr(cli_mod, "get_settings", lambda: object())
    monkeypatch.setattr(cli_mod, "apply_schema", apply_schema_stub)
    monkeypatch.setattr(sys, "argv", ["lawcorpus", *argv])
    cli_mod.main()


def test_apply_schema_drop_without_confirmation_refused(monkeypatch):
    calls = []

    async def fake_apply_schema(settings, *, drop=False):
        calls.append(drop)

    with pytest.raises(SystemExit):
        _run_cli(monkeypatch, ["apply-schema", "--drop"], fake_apply_schema)
    assert calls == []


def test_apply_schema_drop_with_confirmation_proceeds(monkeypatch):
    calls = []

    async def fake_apply_schema(settings, *, drop=False):
        calls.append(drop)

    _run_cli(monkeypatch, ["apply-schema", "--drop", "--yes-i-mean-it"], fake_apply_schema)
    assert calls == [True]


def test_apply_schema_without_drop_does_not_require_confirmation(monkeypatch):
    calls = []

    async def fake_apply_schema(settings, *, drop=False):
        calls.append(drop)

    _run_cli(monkeypatch, ["apply-schema"], fake_apply_schema)
    assert calls == [False]
