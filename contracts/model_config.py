"""model_config.py -- the optional [models] config layer for D17 (Track G, G5).

D8 gives every LLM-touching step a harness mode and a copy-paste mode, both
renderfact-code-free. D17 adds an OPTIONAL, off-by-default THIRD escalation
channel: a directly-called model. This module is the config + routing for it.

Two endpoints can be declared, `llm` (text) and `vlm` (vision-language):
  - route by modality: a step whose INPUT_SCHEMA declares `rendered_image_path`
    routes to the vlm, else the llm.
  - the vlm DEFAULTS TO the llm when it is unset or its endpoint fails a cheap
    reachability probe -- one configured model serves both.
  - a vision step whose resolved model is NOT vision-capable degrades to
    copy-paste; a vision step is never silently run text-only.

Off by default: with no config, `configured()` is False and nothing here runs --
escalation stays harness-or-copy-paste exactly as D8 defined.

SECRETS: `api_key` is ENV-ONLY, never read from the config file, so a committed
`renderfact-models.toml` can never carry a secret. No function here ever prints,
logs, or includes an api_key in an error message (grep-enforced by a test).
"""

from __future__ import annotations

import os
import tomllib
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

CONFIG_ENV = "RENDERFACT_MODELS_CONFIG"
DEFAULT_CONFIG_FILE = "renderfact-models.toml"


@dataclass(frozen=True)
class ModelEndpoint:
    base_url: str
    model: str
    api_key: str | None = None
    vision: bool = False


@dataclass(frozen=True)
class ModelsConfig:
    llm: ModelEndpoint | None = None
    vlm: ModelEndpoint | None = None

    def configured(self) -> bool:
        """The direct-API channel is active only when at least the llm is set."""
        return self.llm is not None


@dataclass(frozen=True)
class Resolution:
    endpoint: ModelEndpoint | None       # None -> use the copy-paste fallback
    degrade_to_copy_paste: bool
    reason: str


def _endpoint_from(file_section: dict, prefix: str) -> ModelEndpoint | None:
    """Merge a [llm]/[vlm] TOML section with env overrides. base_url/model/vision
    are file-or-env; api_key is ENV-ONLY. Returns None if no base_url+model
    resolve (the endpoint is simply not configured)."""
    base_url = os.environ.get(f"{prefix}_BASE_URL") or file_section.get("base_url")
    model = os.environ.get(f"{prefix}_MODEL") or file_section.get("model")
    if not base_url or not model:
        return None
    vision_env = os.environ.get(f"{prefix}_VISION")
    vision = (vision_env.lower() in ("1", "true", "yes")) if vision_env is not None \
        else bool(file_section.get("vision", False))
    api_key = os.environ.get(f"{prefix}_API_KEY")  # env-only, never from the file
    return ModelEndpoint(base_url=base_url.rstrip("/"), model=model, api_key=api_key, vision=vision)


def load(config_path: "str | Path | None" = None) -> ModelsConfig:
    """Load the [models] config from a TOML file (path arg > CONFIG_ENV >
    ./renderfact-models.toml) merged with env overrides. Missing file is fine --
    env alone can configure it, or nothing does (off by default)."""
    path = Path(config_path) if config_path is not None \
        else Path(os.environ.get(CONFIG_ENV, DEFAULT_CONFIG_FILE))
    data: dict = {}
    if path.exists():
        try:
            with open(path, "rb") as f:
                data = tomllib.load(f)
        except (OSError, tomllib.TOMLDecodeError):
            data = {}
    return ModelsConfig(
        llm=_endpoint_from(data.get("llm", {}) or {}, "RENDERFACT_LLM"),
        vlm=_endpoint_from(data.get("vlm", {}) or {}, "RENDERFACT_VLM"),
    )


def probe(endpoint: ModelEndpoint, timeout: float = 3.0) -> bool:
    """Cheap reachability check: did the server RESPOND (even with an HTTP error)?
    A connection failure / timeout -> False. Never raises. Used only to decide the
    vlm-vs-llm fallback; a wrong key surfaces later as a DirectApiError -> copy-paste."""
    req = urllib.request.Request(endpoint.base_url, method="HEAD")
    try:
        urllib.request.urlopen(req, timeout=timeout).close()
        return True
    except urllib.error.HTTPError:
        return True  # server responded (4xx/5xx) -> it is up
    except Exception:
        return False


def wants_vision(module) -> bool:
    """True iff the step's INPUT_SCHEMA declares a `rendered_image_path` field --
    the canonical image-modality signal (vision-review has it, decision-capture /
    contextualize do not)."""
    schema = getattr(module, "INPUT_SCHEMA", [])
    return any(getattr(f, "name", None) == "rendered_image_path" for f in schema)


def resolve_for_step(module, cfg: ModelsConfig) -> Resolution:
    """D17 routing. Returns which endpoint (if any) to call, or a
    degrade_to_copy_paste flag when a vision step has no vision-capable model."""
    if not cfg.configured():
        return Resolution(None, False, "no [models] config (direct-API off)")

    if not wants_vision(module):
        return Resolution(cfg.llm, False, "text step -> llm")

    # vision step: prefer a reachable vlm, else fall back to the llm
    if cfg.vlm is not None and probe(cfg.vlm):
        endpoint, note = cfg.vlm, "vision step -> vlm"
    else:
        endpoint = cfg.llm
        note = "vision step -> llm (vlm unset or unreachable)"
    if not endpoint.vision:
        return Resolution(None, True, "resolved model is not vision-capable -> copy-paste")
    return Resolution(endpoint, False, note)
