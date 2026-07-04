"""
Tests for contracts/direct_api.py (Track G, G5): the D17 direct-API escalation
channel (stdlib-urllib, OpenAI-compatible /chat/completions).

Covers: a text step round-trip forcing MODE_FIELD="api"; a vision endpoint
attaching the rendered image as a base64 data URL; the Authorization header
only when an api_key is set; transport / missing-choices / unparseable /
validation failures all mapping to DirectApiError (never leaking the key); and
the api_then_copy_paste escalation helper's fall-back-to-copy-paste behaviour.
"""

from __future__ import annotations

import io
import json
import sys
import urllib.error
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "lint"))
sys.path.insert(0, str(REPO_ROOT / "roundtrip"))

from contracts import direct_api  # noqa: E402
from contracts import model_config as mc  # noqa: E402
import contextualize as ctx  # noqa: E402
import vision_review_contract as vr  # noqa: E402

# --- a 1x1 PNG (smallest valid) for the vision-attach test --------------------
_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06"
    b"\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00"
    b"\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _text_input():
    return ctx.assemble_input({"verdict": "FAST_FORWARD", "manual": []}, "doc.md", "My Doc")


def _valid_context_reply():
    entry = ctx.deterministic_entry(_text_input())  # a known-valid contextualize entry
    entry.pop("capture_mode", None)                 # the channel sets it
    return entry


def _fake_urlopen(captured, *, content=None, raise_exc=None, payload=None):
    """Return a urlopen(req, timeout=...) stand-in that records the request and
    yields a canned OpenAI-style response body."""
    def _open(req, timeout=None):
        captured["req"] = req
        captured["body"] = req.data.decode("utf-8") if req.data else None
        captured["headers"] = dict(req.header_items())
        if raise_exc is not None:
            raise raise_exc
        if payload is not None:
            data = json.dumps(payload)
        else:
            data = json.dumps({"choices": [{"message": {"content": content}}]})

        class _Resp:
            def __enter__(self_):
                return io.BytesIO(data.encode("utf-8"))

            def __exit__(self_, *a):
                return False
        return _Resp()
    return _open


def _endpoint(api_key=None, vision=False):
    return mc.ModelEndpoint("http://model/v1", "test-model", api_key=api_key, vision=vision)


# ------------------------------------------------------------ text round-trip --

def test_text_step_forces_api_mode():
    captured = {}
    urlopen = _fake_urlopen(captured, content=json.dumps(_valid_context_reply()))
    result = direct_api.run_api_step(
        "contextualize", ctx, _text_input(), _endpoint(api_key="SECRET"), urlopen=urlopen)
    assert result["capture_mode"] == "api"
    ok, errors = ctx.validate_output(result)
    assert ok, errors
    # url + method
    assert captured["req"].full_url == "http://model/v1/chat/completions"
    assert captured["req"].method == "POST"
    # text-only message (no image part) for a text step
    assert "image_url" not in captured["body"]


def test_authorization_header_present_with_key():
    captured = {}
    urlopen = _fake_urlopen(captured, content=json.dumps(_valid_context_reply()))
    direct_api.run_api_step("contextualize", ctx, _text_input(), _endpoint(api_key="SECRET"), urlopen=urlopen)
    # header keys are capitalised by urllib
    assert captured["headers"].get("Authorization") == "Bearer SECRET"


def test_no_authorization_header_without_key():
    captured = {}
    urlopen = _fake_urlopen(captured, content=json.dumps(_valid_context_reply()))
    direct_api.run_api_step("contextualize", ctx, _text_input(), _endpoint(api_key=None), urlopen=urlopen)
    assert "Authorization" not in captured["headers"]


# ------------------------------------------------------------- vision attach --

def _valid_vision_reply():
    return {"status": "OK", "findings": [], "summary": "looks fine", "reviewer_mode": "harness"}


def _vision_input(image_path):
    return {"task_intent": vr.TASK_INTENT, "rendered_image_path": str(image_path),
            "tier": vr.VALID_TIERS[0], "deterministic_metrics": {}}


def test_vision_endpoint_attaches_image(tmp_path):
    img = tmp_path / "diagram.png"
    img.write_bytes(_PNG)
    captured = {}
    urlopen = _fake_urlopen(captured, content=json.dumps(_valid_vision_reply()))
    result = direct_api.run_api_step(
        "vision-review", vr, _vision_input(img), _endpoint(api_key="K", vision=True), urlopen=urlopen)
    assert result["reviewer_mode"] == "api"
    body = json.loads(captured["body"])
    parts = body["messages"][0]["content"]
    kinds = [p["type"] for p in parts]
    assert "image_url" in kinds
    img_part = next(p for p in parts if p["type"] == "image_url")
    assert img_part["image_url"]["url"].startswith("data:image/png;base64,")


def test_text_endpoint_ignores_image(tmp_path):
    # a vision=False endpoint sends the image path only as text, never inline
    img = tmp_path / "diagram.png"
    img.write_bytes(_PNG)
    captured = {}
    urlopen = _fake_urlopen(captured, content=json.dumps(_valid_vision_reply()))
    direct_api.run_api_step(
        "vision-review", vr, _vision_input(img), _endpoint(api_key="K", vision=False), urlopen=urlopen)
    assert "data:image/png;base64" not in captured["body"]


# --------------------------------------------------------------- error paths --

def test_http_error_maps_to_direct_api_error():
    urlopen = _fake_urlopen({}, raise_exc=urllib.error.HTTPError("http://x", 500, "err", {}, None))
    with pytest.raises(direct_api.DirectApiError) as e:
        direct_api.run_api_step("contextualize", ctx, _text_input(), _endpoint(api_key="SECRET"), urlopen=urlopen)
    assert "SECRET" not in str(e.value)


def test_url_error_maps_to_direct_api_error():
    urlopen = _fake_urlopen({}, raise_exc=urllib.error.URLError("refused"))
    with pytest.raises(direct_api.DirectApiError):
        direct_api.run_api_step("contextualize", ctx, _text_input(), _endpoint(), urlopen=urlopen)


def test_missing_choices_maps_to_error():
    urlopen = _fake_urlopen({}, payload={"no": "choices"})
    with pytest.raises(direct_api.DirectApiError):
        direct_api.run_api_step("contextualize", ctx, _text_input(), _endpoint(), urlopen=urlopen)


def test_unparseable_content_maps_to_error():
    urlopen = _fake_urlopen({}, content="this is not json or yaml: {[")
    with pytest.raises(direct_api.DirectApiError):
        direct_api.run_api_step("contextualize", ctx, _text_input(), _endpoint(), urlopen=urlopen)


def test_invalid_output_maps_to_error():
    # parses fine but fails the step's own validate_output (missing changes/title...)
    urlopen = _fake_urlopen({}, content=json.dumps({"summary": "incomplete"}))
    with pytest.raises(direct_api.DirectApiError):
        direct_api.run_api_step("contextualize", ctx, _text_input(), _endpoint(), urlopen=urlopen)


def test_missing_mode_field_errors():
    class _NoModeField:
        pass
    with pytest.raises(direct_api.DirectApiError):
        direct_api.run_api_step("x", _NoModeField, {}, _endpoint())


# ------------------------------------------------------- escalation helper --

def test_api_then_copy_paste_uses_api_when_configured(monkeypatch):
    sentinel = {"capture_mode": "api", "ok": True}
    monkeypatch.setattr(direct_api, "resolve_and_run", lambda *a, **k: sentinel)
    out = io.StringIO()
    assert direct_api.api_then_copy_paste("contextualize", ctx, _text_input(), out=out) is sentinel


def test_api_then_copy_paste_falls_back_on_no_config(monkeypatch):
    monkeypatch.setattr(direct_api, "resolve_and_run", lambda *a, **k: None)
    from contracts import copy_paste
    monkeypatch.setattr(copy_paste, "run_copy_paste_step", lambda *a, **k: {"capture_mode": "copy-paste"})
    out = io.StringIO()
    result = direct_api.api_then_copy_paste("contextualize", ctx, _text_input(), out=out)
    assert result["capture_mode"] == "copy-paste"


def test_api_then_copy_paste_falls_back_on_transport_error(monkeypatch):
    def _boom(*a, **k):
        raise direct_api.DirectApiError("POST http://x unreachable: refused")
    monkeypatch.setattr(direct_api, "resolve_and_run", _boom)
    from contracts import copy_paste
    monkeypatch.setattr(copy_paste, "run_copy_paste_step", lambda *a, **k: {"capture_mode": "copy-paste"})
    out = io.StringIO()
    result = direct_api.api_then_copy_paste("contextualize", ctx, _text_input(), out=out)
    assert result["capture_mode"] == "copy-paste"
    assert "falling back to copy-paste" in out.getvalue()


def test_resolve_and_run_returns_none_when_unconfigured(tmp_path, monkeypatch):
    for v in ("RENDERFACT_LLM_BASE_URL", "RENDERFACT_LLM_MODEL"):
        monkeypatch.delenv(v, raising=False)
    cfg = mc.load(tmp_path / "nope.toml")
    assert direct_api.resolve_and_run("contextualize", ctx, _text_input(), config=cfg) is None
