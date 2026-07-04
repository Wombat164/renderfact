"""direct_api.py -- the D17 direct-API escalation channel (Track G, G5).

The THIRD D8 escalation mode, off by default. When `contracts/model_config.py`
resolves an endpoint for a step, this runs that step by POSTing an
OpenAI-compatible `/chat/completions` request with stdlib urllib -- no new
dependency, no vendor SDK. The prompt is the SAME one the copy-paste channel
composes (contracts/copy_paste.compose_prompt), so a step's contract is the one
source of truth across all three modes; the reply is parsed and validated with
the SAME parse_llm_response + module.validate_output.

Vision: a resolved vision endpoint gets the rendered image inline as a base64
data URL (OpenAI `image_url` content part). A text endpoint just gets the text.

SECRETS: the api_key travels only in the Authorization header of the outbound
request. It is NEVER printed, logged, or placed in an exception message -- a
transport failure raises DirectApiError with the URL and status only. When the
endpoint is unreachable the caller (render.py) falls back to copy-paste rather
than failing the render.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import sys
import urllib.error
import urllib.request
from pathlib import Path

from contracts.copy_paste import compose_prompt, parse_llm_response

API_MODE = "api"
DEFAULT_TIMEOUT = 60.0


class DirectApiError(RuntimeError):
    """Raised when the direct-API call fails to reach the endpoint or returns an
    unusable response. Its message never contains the api_key."""


def _image_data_url(image_path: str) -> "str | None":
    """Read an image file and return an OpenAI `image_url` data URL, or None if
    the path is missing/unreadable (the step then runs text-only)."""
    p = Path(image_path)
    if not p.is_file():
        return None
    mime = mimetypes.guess_type(p.name)[0] or "image/png"
    try:
        raw = p.read_bytes()
    except OSError:
        return None
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"


def _build_messages(prompt: str, input_obj: dict, endpoint) -> list:
    """One user turn. For a vision endpoint with a readable rendered_image_path,
    attach the image as a second content part; otherwise a plain text message."""
    image_path = input_obj.get("rendered_image_path")
    if getattr(endpoint, "vision", False) and image_path:
        data_url = _image_data_url(image_path)
        if data_url is not None:
            return [{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": data_url}},
            ]}]
    return [{"role": "user", "content": prompt}]


def run_api_step(
    step_name: str,
    module,
    input_obj: dict,
    endpoint,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    urlopen=urllib.request.urlopen,
) -> dict:
    """Run one D8 step through the direct-API channel and return the validated
    result with MODE_FIELD forced to "api". `urlopen` is injectable for tests.
    Raises DirectApiError on any transport/parse/validation failure -- callers
    fall back to copy-paste."""
    mode_field = getattr(module, "MODE_FIELD", None)
    if mode_field is None:
        raise DirectApiError(
            f"step contract '{step_name}' must declare MODE_FIELD"
        )

    prompt = compose_prompt(step_name, module, input_obj)
    body = json.dumps({
        "model": endpoint.model,
        "messages": _build_messages(prompt, input_obj, endpoint),
    }).encode("utf-8")

    url = f"{endpoint.base_url}/chat/completions"
    headers = {"Content-Type": "application/json"}
    if endpoint.api_key:
        headers["Authorization"] = f"Bearer {endpoint.api_key}"
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")

    try:
        with urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise DirectApiError(f"POST {url} -> HTTP {e.code}") from None
    except urllib.error.URLError as e:
        raise DirectApiError(f"POST {url} unreachable: {e.reason}") from None
    except (OSError, ValueError) as e:
        raise DirectApiError(f"POST {url} failed: {e}") from None

    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise DirectApiError(f"POST {url} -> response missing choices[0].message.content") from None

    try:
        result = parse_llm_response(content)
    except ValueError as e:
        raise DirectApiError(f"could not parse the model reply: {e}") from None

    result[mode_field] = API_MODE
    ok, errors = module.validate_output(result)
    if not ok:
        raise DirectApiError(f"direct-API reply failed validation: {'; '.join(errors)}")
    return result


def resolve_and_run(step_name: str, module, input_obj: dict, *, config=None) -> "dict | None":
    """Load the [models] config, resolve an endpoint for this step, and run it.
    Returns the validated result, or None when the direct-API channel is not
    usable for this step (no config, or a vision step degraded to copy-paste).
    Raises DirectApiError on a transport/validation failure -- the caller falls
    back to copy-paste."""
    from contracts import model_config

    cfg = config if config is not None else model_config.load()
    res = model_config.resolve_for_step(module, cfg)
    if res.endpoint is None:
        return None
    return run_api_step(step_name, module, input_obj, res.endpoint)


def api_then_copy_paste(
    step_name: str,
    module,
    input_obj: dict,
    *,
    scratch_dir: Path = Path("."),
    out=sys.stdout,
    config=None,
) -> dict:
    """The D17 escalation body: try the direct-API channel first; on no-config or
    any transport/validation failure, fall back to the D8 copy-paste channel.
    Always returns a validated result (or raises whatever copy-paste raises)."""
    from contracts import copy_paste

    try:
        result = resolve_and_run(step_name, module, input_obj, config=config)
        if result is not None:
            print(f"[D17 direct-API] {step_name} handled by the configured model", file=out)
            return result
    except DirectApiError as e:
        print(f"[D17 direct-API] {e} -- falling back to copy-paste", file=out)
    return copy_paste.run_copy_paste_step(step_name, module, input_obj, scratch_dir=scratch_dir, out=out)
