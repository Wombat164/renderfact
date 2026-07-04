"""
Tests for contracts/model_config.py (Track G, G5): the optional [models] config
layer for the D17 direct-API escalation channel.

Covers: TOML + env loading (with api_key ENV-ONLY, never from the file); the
off-by-default `configured()` gate; endpoint resolution routing (text -> llm,
vision -> vlm, vlm-fallback-to-llm when unset/unreachable, degrade-to-copy-paste
when the resolved model is not vision-capable); the reachability probe; and a
grep-style guarantee that no api_key is ever printed or logged.
"""

from __future__ import annotations

import sys
import urllib.error
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "lint"))
sys.path.insert(0, str(REPO_ROOT / "roundtrip"))

from contracts import model_config as mc  # noqa: E402

_ENV_VARS = [
    "RENDERFACT_MODELS_CONFIG",
    "RENDERFACT_LLM_BASE_URL", "RENDERFACT_LLM_MODEL", "RENDERFACT_LLM_VISION", "RENDERFACT_LLM_API_KEY",
    "RENDERFACT_VLM_BASE_URL", "RENDERFACT_VLM_MODEL", "RENDERFACT_VLM_VISION", "RENDERFACT_VLM_API_KEY",
]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for v in _ENV_VARS:
        monkeypatch.delenv(v, raising=False)


# fake step modules for routing (only INPUT_SCHEMA matters to wants_vision) -----

class _Field:
    def __init__(self, name):
        self.name = name


class _TextStep:
    INPUT_SCHEMA = [_Field("task_intent"), _Field("manual_changes")]


class _VisionStep:
    INPUT_SCHEMA = [_Field("rendered_image_path"), _Field("tier")]


def _toml(tmp_path, body):
    p = tmp_path / "renderfact-models.toml"
    p.write_text(body, encoding="utf-8")
    return p


# ------------------------------------------------------------------- loading --

def test_load_from_toml_no_key_in_file(tmp_path):
    cfg = mc.load(_toml(tmp_path, '[llm]\nbase_url = "http://x/v1"\nmodel = "m"\n'))
    assert cfg.llm.base_url == "http://x/v1" and cfg.llm.model == "m"
    assert cfg.llm.api_key is None  # never sourced from the file
    assert cfg.vlm is None and cfg.configured() is True


def test_api_key_is_env_only(tmp_path, monkeypatch):
    # even if someone puts api_key in the TOML, it must be ignored
    p = _toml(tmp_path, '[llm]\nbase_url = "http://x/v1"\nmodel = "m"\napi_key = "FROM_FILE"\n')
    monkeypatch.setenv("RENDERFACT_LLM_API_KEY", "FROM_ENV")
    cfg = mc.load(p)
    assert cfg.llm.api_key == "FROM_ENV"


def test_env_overrides_file(tmp_path, monkeypatch):
    p = _toml(tmp_path, '[llm]\nbase_url = "http://file/v1"\nmodel = "file-m"\n')
    monkeypatch.setenv("RENDERFACT_LLM_BASE_URL", "http://env/v1")
    monkeypatch.setenv("RENDERFACT_LLM_VISION", "true")
    cfg = mc.load(p)
    assert cfg.llm.base_url == "http://env/v1" and cfg.llm.model == "file-m"
    assert cfg.llm.vision is True


def test_env_only_no_file(monkeypatch, tmp_path):
    monkeypatch.setenv("RENDERFACT_LLM_BASE_URL", "http://env/v1")
    monkeypatch.setenv("RENDERFACT_LLM_MODEL", "env-m")
    cfg = mc.load(tmp_path / "does-not-exist.toml")
    assert cfg.configured() and cfg.llm.model == "env-m"


def test_unconfigured_is_off(tmp_path):
    cfg = mc.load(tmp_path / "nope.toml")
    assert cfg.llm is None and cfg.configured() is False


def test_trailing_slash_stripped(tmp_path):
    cfg = mc.load(_toml(tmp_path, '[llm]\nbase_url = "http://x/v1/"\nmodel = "m"\n'))
    assert cfg.llm.base_url == "http://x/v1"


def test_malformed_toml_degrades_to_env(tmp_path, monkeypatch):
    p = tmp_path / "renderfact-models.toml"
    p.write_text("this is not [valid toml", encoding="utf-8")
    monkeypatch.setenv("RENDERFACT_LLM_BASE_URL", "http://env/v1")
    monkeypatch.setenv("RENDERFACT_LLM_MODEL", "env-m")
    cfg = mc.load(p)
    assert cfg.configured() and cfg.llm.base_url == "http://env/v1"


# ------------------------------------------------------------------- routing --

def test_wants_vision():
    assert mc.wants_vision(_VisionStep) is True
    assert mc.wants_vision(_TextStep) is False


def test_resolve_text_step_uses_llm(tmp_path):
    cfg = mc.load(_toml(tmp_path, '[llm]\nbase_url = "http://llm/v1"\nmodel = "m"\n'))
    res = mc.resolve_for_step(_TextStep, cfg)
    assert res.endpoint is cfg.llm and res.degrade_to_copy_paste is False


def test_resolve_unconfigured(tmp_path):
    res = mc.resolve_for_step(_TextStep, mc.load(tmp_path / "nope.toml"))
    assert res.endpoint is None and res.degrade_to_copy_paste is False


def test_resolve_vision_prefers_reachable_vlm(tmp_path, monkeypatch):
    cfg = mc.load(_toml(tmp_path,
        '[llm]\nbase_url = "http://llm/v1"\nmodel = "l"\n'
        '[vlm]\nbase_url = "http://vlm/v1"\nmodel = "v"\nvision = true\n'))
    monkeypatch.setattr(mc, "probe", lambda ep, timeout=3.0: True)
    res = mc.resolve_for_step(_VisionStep, cfg)
    assert res.endpoint is cfg.vlm


def test_resolve_vision_falls_back_to_llm_when_vlm_unset(tmp_path):
    # vlm unset, llm happens to be vision-capable -> use llm
    cfg = mc.load(_toml(tmp_path,
        '[llm]\nbase_url = "http://llm/v1"\nmodel = "l"\nvision = true\n'))
    res = mc.resolve_for_step(_VisionStep, cfg)
    assert res.endpoint is cfg.llm and res.degrade_to_copy_paste is False


def test_resolve_vision_falls_back_when_vlm_unreachable(tmp_path, monkeypatch):
    cfg = mc.load(_toml(tmp_path,
        '[llm]\nbase_url = "http://llm/v1"\nmodel = "l"\nvision = true\n'
        '[vlm]\nbase_url = "http://vlm/v1"\nmodel = "v"\nvision = true\n'))
    monkeypatch.setattr(mc, "probe", lambda ep, timeout=3.0: False)  # vlm down
    res = mc.resolve_for_step(_VisionStep, cfg)
    assert res.endpoint is cfg.llm


def test_resolve_vision_degrades_when_no_vision_model(tmp_path):
    # vision step, but neither model is vision-capable -> copy-paste
    cfg = mc.load(_toml(tmp_path, '[llm]\nbase_url = "http://llm/v1"\nmodel = "l"\n'))
    res = mc.resolve_for_step(_VisionStep, cfg)
    assert res.endpoint is None and res.degrade_to_copy_paste is True


# --------------------------------------------------------------------- probe --

def test_probe_true_on_response(monkeypatch):
    class _Resp:
        def close(self):
            pass
    monkeypatch.setattr(mc.urllib.request, "urlopen", lambda req, timeout=3.0: _Resp())
    assert mc.probe(mc.ModelEndpoint("http://x", "m")) is True


def test_probe_true_on_http_error(monkeypatch):
    def _raise(req, timeout=3.0):
        raise urllib.error.HTTPError("http://x", 404, "nf", {}, None)
    monkeypatch.setattr(mc.urllib.request, "urlopen", _raise)
    assert mc.probe(mc.ModelEndpoint("http://x", "m")) is True


def test_probe_false_on_conn_error(monkeypatch):
    def _raise(req, timeout=3.0):
        raise urllib.error.URLError("connection refused")
    monkeypatch.setattr(mc.urllib.request, "urlopen", _raise)
    assert mc.probe(mc.ModelEndpoint("http://x", "m")) is False


# ------------------------------------------------------------------ secrets --

def test_no_api_key_in_logging_calls():
    """Static guarantee: no print()/log line in the config or direct-API modules
    references .api_key -- the key travels only in an Authorization header."""
    for name in ("model_config.py", "direct_api.py"):
        src = (REPO_ROOT / "contracts" / name).read_text(encoding="utf-8")
        for line in src.splitlines():
            low = line.strip()
            if low.startswith("#"):
                continue
            if ("print(" in line or "log_decision" in line or "logging" in line) and "api_key" in line:
                pytest.fail(f"{name}: api_key referenced on a logging line: {line!r}")
