"""app.py: the renderfact HTTP API (chunk 5.1 / E1), stdlib-only WSGI.

D9: "same contract, HTTP instead of copy-paste". The API exposes the D8
per-step I/O contracts (list, introspect, validate) plus the projection
engine, wrapping the SAME code paths the CLI uses; it has nothing of its own
to say about rendering. Per D12's resolved stack decision the server is
Python stdlib (wsgiref/http.server), no web framework; the reference UI
(api/ui.py) is one deliberately thin client of this API, not the product.

Security posture (E2 + D15, modeled on calm-server then hardened past it):
  - binds 127.0.0.1 by default; binding wider prints an explicit runtime
    warning (this server has NO authentication or authorization controls)
  - Host-header check on EVERY request: non-loopback Host is rejected with
    403 (DNS-rebinding protection; a rebound hostname carries the attacker's
    Host value)
  - browser-origin check on every POST: when a browser signals its origin
    (Origin or Sec-Fetch-Site header), it must be same-origin; non-browser
    clients (curl, scripts) carry neither header and pass. A CSRF session
    token endpoint exists for future truly-mutating routes (the editor);
    v0 routes are compute/read-only.
  - path jail: every filesystem path a request names is resolved and must
    stay under the server's --root (default: the working directory at start)
  - a small per-client rate limit (fixed window) returns 429 when exceeded

Run: render serve [--port N] [--bind ADDR] [--root DIR] [--enable-ui]
"""

from __future__ import annotations

import json
import re
import secrets
import shutil
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "[::1]", "::1")

# Workspace static assets (Track J, chunk 6.5 / D23): package-data files, not
# string literals. Exact-filename allowlist -- traversal is not possible by
# construction, no path-jail arithmetic needed. Gated behind --enable-ui.
STATIC_DIR = REPO_ROOT / "api" / "static"
STATIC_ALLOWLIST = {
    "common.js", "dashboard.css", "dashboard.js", "wizard.js", "templates-library.js",
}
_STATIC_CONTENT_TYPES = {".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8"}


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _field_doc(spec) -> dict:
    d = {
        "name": spec.name,
        "type": spec.type.__name__,
        "required": spec.required,
        "description": spec.description,
    }
    if spec.allowed_values is not None:
        d["allowed_values"] = list(spec.allowed_values)
    if spec.item_schema is not None:
        d["item_schema"] = [_field_doc(s) for s in spec.item_schema]
    return d


class RateLimiter:
    """Fixed-window per-client counter. Localhost single-operator scale."""

    def __init__(self, limit: int = 120, window_s: int = 10):
        self.limit = limit
        self.window_s = window_s
        self._counts: dict[str, tuple[int, int]] = {}

    def allow(self, client: str) -> bool:
        window = int(time.time() // self.window_s)
        w, n = self._counts.get(client, (window, 0))
        if w != window:
            w, n = window, 0
        n += 1
        self._counts[client] = (w, n)
        return n <= self.limit


class RenderfactApi:
    def __init__(self, root: Path | None = None, enable_ui: bool = False,
                 rate_limit: int = 120, projects_root: Path | None = None,
                 templates_root: Path | None = None):
        self.root = (root or Path.cwd()).resolve()
        self.enable_ui = enable_ui
        self.limiter = RateLimiter(limit=rate_limit)
        self.csrf_tokens: set[str] = set()
        self.projects_root = (Path(projects_root).resolve() if projects_root
                              else self.root / "projects")
        self.templates_root = (Path(templates_root).resolve() if templates_root
                               else self.root / "templates")
        self._store = None
        self._templates = None
        sys.path.insert(0, str(REPO_ROOT))
        sys.path.insert(0, str(REPO_ROOT / "lint"))
        from contracts import init_ai  # noqa: PLC0415

        self.steps = dict(init_ai.step_contracts())

    # ---- guards (E2/D15) ----

    def _guard(self, environ) -> None:
        host = (environ.get("HTTP_HOST") or "").rsplit(":", 1)[0]
        if host not in LOOPBACK_HOSTS:
            raise ApiError(403, f"non-loopback Host rejected: {host!r}")
        client = environ.get("REMOTE_ADDR", "?")
        if not self.limiter.allow(client):
            raise ApiError(429, "rate limit exceeded")
        if environ["REQUEST_METHOD"] in ("POST", "PUT"):
            origin = environ.get("HTTP_ORIGIN")
            fetch_site = environ.get("HTTP_SEC_FETCH_SITE")
            if origin is not None:
                m = re.match(r"https?://([^/:]+)(:\d+)?$", origin)
                if not m or m.group(1) not in LOOPBACK_HOSTS:
                    raise ApiError(403, f"cross-origin {environ['REQUEST_METHOD']} rejected: {origin!r}")
            elif fetch_site is not None and fetch_site not in ("same-origin", "none"):
                raise ApiError(403, f"cross-site {environ['REQUEST_METHOD']} rejected: "
                                    f"Sec-Fetch-Site={fetch_site!r}")

    def _require_csrf(self, environ) -> None:
        """D15 point 2: a per-session CSRF token, checked on every truly
        mutating endpoint (chunk 6.2 is the first to enforce this; earlier
        POST routes render-and-return, they do not persist server-side
        state). Token comes from GET /session; it is not single-use."""
        token = environ.get("HTTP_X_CSRF_TOKEN")
        if not token or token not in self.csrf_tokens:
            raise ApiError(403, "missing or invalid CSRF token (GET /session first)")

    def _jail(self, raw: str, what: str) -> Path:
        p = Path(raw)
        if not p.is_absolute():
            p = self.root / p
        p = p.resolve()
        try:
            p.relative_to(self.root)
        except ValueError:
            raise ApiError(403, f"{what} escapes the server root: {raw!r}") from None
        return p

    def _require_ui(self) -> None:
        if not self.enable_ui:
            raise ApiError(404, "UI not enabled (start with --enable-ui)")

    def _static_asset(self, name: str):
        """GET /ui/static/{name} (D23): an exact-filename allowlist, so no
        directory-traversal check is even needed -- an unlisted name never
        reaches the filesystem at all."""
        if name not in STATIC_ALLOWLIST:
            raise ApiError(404, f"no such static asset: {name}")
        path = STATIC_DIR / name
        if not path.is_file():
            raise ApiError(404, f"static asset missing on disk: {name}")
        ctype = _STATIC_CONTENT_TYPES.get(path.suffix, "application/octet-stream")
        return BinaryResponse(path.read_bytes(), ctype,
                              extra_headers={"Cache-Control": "public, max-age=86400"})

    # ---- routes ----

    def route(self, method: str, path: str, body: dict | None, environ: dict | None = None):
        if method == "GET" and path == "/":
            return self._info()
        if method == "GET" and path == "/session":
            token = secrets.token_urlsafe(32)
            self.csrf_tokens.add(token)
            return {"csrf_token": token, "note": "required on future mutating endpoints"}
        if method == "GET" and path == "/openapi.json":
            return openapi_spec(self)
        if method == "GET" and path == "/docs":
            return HtmlResponse(render_docs_html(self))
        if method == "GET" and path == "/ui":
            if not self.enable_ui:
                raise ApiError(404, "UI not enabled (start with --enable-ui)")
            from api.ui import UI_HTML  # noqa: PLC0415

            return HtmlResponse(UI_HTML)
        if method == "GET" and path == "/ui/projects":
            self._require_ui()
            return HtmlResponse(render_dashboard_html())
        if method == "GET" and path == "/ui/projects/new":
            self._require_ui()
            return HtmlResponse(render_wizard_html())
        if method == "GET" and path == "/ui/templates":
            self._require_ui()
            return HtmlResponse(render_template_library_html())
        m = re.match(r"^/ui/static/([A-Za-z0-9_.-]+)$", path)
        if method == "GET" and m:
            self._require_ui()
            return self._static_asset(m.group(1))
        if method == "GET" and path == "/steps":
            return {"steps": sorted(self.steps)}
        if method == "GET" and path == "/doctor":
            return self._doctor()
        if method == "GET" and path == "/locales":
            return self._locales()
        if method == "GET" and path == "/theme/variants":
            return self._theme_variants()
        if method == "POST" and path == "/statement/check":
            return self._statement_check(body)
        m = re.match(r"^/steps/([a-z0-9-]+)$", path)
        if method == "GET" and m:
            return self._step_schema(m.group(1))
        m = re.match(r"^/steps/([a-z0-9-]+)/validate-output$", path)
        if method == "POST" and m:
            return self._validate_output(m.group(1), body)
        if method == "POST" and path == "/project":
            return self._project(body)
        if method == "POST" and path == "/render/pdf":
            return self._render_pdf(body)
        if method == "POST" and path == "/render/docx":
            return self._render_docx(body)
        if method == "GET" and path == "/projects":
            return self._projects_list()
        if method == "POST" and path == "/projects":
            return self._project_create(body, environ)
        m = re.match(r"^/projects/([a-z0-9][a-z0-9-]*)$", path)
        if method == "GET" and m:
            return self._project_detail(m.group(1), body)
        m = re.match(r"^/projects/([a-z0-9][a-z0-9-]*)/config$", path)
        if method == "PUT" and m:
            return self._project_config_put(m.group(1), body, environ)
        m = re.match(r"^/projects/([a-z0-9][a-z0-9-]*)/profiles$", path)
        if method == "GET" and m:
            return self._project_profiles(m.group(1))
        if method == "GET" and path == "/profiles":
            return self._profiles_by_path(body)
        if method == "GET" and path == "/templates":
            return self._templates_list()
        if method == "POST" and path == "/templates/import":
            return self._template_import(body, environ)
        m = re.match(r"^/templates/([a-z0-9][a-z0-9-]*)$", path)
        if method == "GET" and m:
            return self._template_detail(m.group(1))
        raise ApiError(404, f"no route: {method} {path}")

    # ---- project registry (Track J, chunk 6.1; read-side) ----

    def _project_store(self):
        if self._store is None:
            sys.path.insert(0, str(REPO_ROOT))
            from api import store  # noqa: PLC0415

            self._store = store.ProjectStore(self.projects_root)
        return self._store

    def _projects_list(self):
        store = self._project_store()
        return {"projects_root": str(store.root), "projects": store.scan()}

    def _project_detail(self, name: str, body: dict | None):
        sys.path.insert(0, str(REPO_ROOT))
        from api import store  # noqa: PLC0415

        limit = 20
        if isinstance(body, dict) and body.get("limit") is not None:
            try:
                limit = max(0, int(body["limit"]))
            except (TypeError, ValueError):
                raise ApiError(400, "limit must be an integer") from None
        try:
            return self._project_store().get(name, limit=limit)
        except store.ManifestError as e:
            raise ApiError(404, str(e)) from None

    def _project_create(self, body: dict | None, environ: dict | None):
        """POST /projects (chunk 6.2): scaffold a new project. The first
        route to enforce the full D15 mutating set: CSRF token (this
        handler), Origin/Host (already enforced for every POST by _guard),
        no path-jail needed beyond the slug regex + a fixed root (traversal
        is structurally impossible: valid_slug forbids '/' and '..')."""
        self._require_csrf(environ or {})
        sys.path.insert(0, str(REPO_ROOT))
        from api import store  # noqa: PLC0415

        if not isinstance(body, dict) or not body.get("name"):
            raise ApiError(400, "missing required field 'name'")
        formats = body.get("formats")
        if formats is not None and not isinstance(formats, list):
            raise ApiError(400, "'formats' must be a list of strings")
        try:
            return self._project_store().create(
                body["name"], title=body.get("title"), template=body.get("template"),
                doc_type=body.get("doc_type", "report"),
                diagram_scaffold=body.get("diagram_scaffold", "none"),
                default_profile=body.get("default_profile", "internal-full"),
                formats=formats, locale=body.get("locale", "en-US"))
        except store.ProjectExistsError as e:
            raise ApiError(409, str(e)) from None
        except store.ManifestError as e:
            raise ApiError(400, str(e)) from None

    def _project_config_put(self, name: str, body: dict | None, environ: dict | None):
        """PUT /projects/{name}/config (chunk 6.2): mutate manifest fields.
        Same optimistic-concurrency shape as the (specified, not yet built)
        editor PUT /editor/section: base_hash + 409 on staleness, one commit
        per diff-carrying change, required non-empty commit message."""
        self._require_csrf(environ or {})
        sys.path.insert(0, str(REPO_ROOT))
        from api import store  # noqa: PLC0415

        if not isinstance(body, dict):
            raise ApiError(400, "request body must be a JSON object")
        for key in ("base_hash", "message", "patch"):
            if not body.get(key):
                raise ApiError(400, f"missing required field {key!r}")
        if not isinstance(body["patch"], dict):
            raise ApiError(400, "'patch' must be an object")
        try:
            return self._project_store().update_config(
                name, body["patch"], body["base_hash"], body["message"])
        except store.StaleManifestError as e:
            raise ApiError(409, str(e)) from None
        except store.CommitMessageError as e:
            raise ApiError(400, str(e)) from None
        except store.ManifestError as e:
            status = 404 if "no such project" in str(e) else 400
            raise ApiError(status, str(e)) from None

    # ---- template library (Track J, chunk 6.3) ----

    def _template_library(self):
        if self._templates is None:
            sys.path.insert(0, str(REPO_ROOT))
            from api import templates as templates_mod  # noqa: PLC0415

            self._templates = templates_mod.TemplateLibrary(self.templates_root)
        return self._templates

    def _templates_list(self):
        lib = self._template_library()
        return {"templates_root": str(lib.custom_root), "templates": lib.scan()}

    def _template_detail(self, name: str):
        sys.path.insert(0, str(REPO_ROOT))
        from api import templates as templates_mod  # noqa: PLC0415

        try:
            return self._template_library().get(name)
        except templates_mod.TemplateError as e:
            raise ApiError(404, str(e)) from None

    def _template_import(self, body: dict | None, environ: dict | None):
        """POST /templates/import (chunk 6.3): thin wrapper over the shipped
        import-template pipeline, landing the derived profile + this
        module's own template.yaml metadata in the custom library root.
        D15-hardened (this writes into the library): CSRF required."""
        self._require_csrf(environ or {})
        sys.path.insert(0, str(REPO_ROOT))
        from api import templates as templates_mod  # noqa: PLC0415

        if not isinstance(body, dict):
            raise ApiError(400, "request body must be a JSON object")
        for key in ("name", "source"):
            if not body.get(key):
                raise ApiError(400, f"missing required field {key!r}")
        docx_path = self._jail(body["source"], "source")
        check_probe = self._jail(body["check_probe"], "check_probe") if body.get("check_probe") else None
        scaffolds = body.get("diagram_scaffolds")
        if scaffolds is not None and not isinstance(scaffolds, list):
            raise ApiError(400, "'diagram_scaffolds' must be a list of strings")
        try:
            return self._template_library().import_docx(
                body["name"], docx_path, doc_type=body.get("doc_type"),
                description=body.get("description"), diagram_scaffolds=scaffolds,
                copy_reference=bool(body.get("copy_reference")), check_probe=check_probe)
        except templates_mod.TemplateExistsError as e:
            raise ApiError(409, str(e)) from None
        except templates_mod.TemplateError as e:
            raise ApiError(400, str(e)) from None

    def _info(self):
        sys.path.insert(0, str(REPO_ROOT / "roundtrip"))
        try:
            import provenance  # noqa: PLC0415

            version = provenance.tool_version()
        except Exception:
            version = "unknown"
        return {
            "service": "renderfact-api",
            "tool_version": version,
            "root": str(self.root),
            "endpoints": [
                "GET /", "GET /session", "GET /openapi.json", "GET /docs",
                "GET /steps", "GET /steps/{name}",
                "POST /steps/{name}/validate-output", "POST /project",
                "POST /render/pdf", "POST /render/docx", "POST /statement/check",
                "GET /doctor", "GET /locales", "GET /theme/variants",
                "GET /projects", "POST /projects", "GET /projects/{name}",
                "PUT /projects/{name}/config", "GET /projects/{name}/profiles",
                "GET /profiles", "GET /templates", "GET /templates/{name}",
                "POST /templates/import",
            ] + (["GET /ui"] if self.enable_ui else []),
        }

    def _get_step(self, name: str):
        if name not in self.steps:
            raise ApiError(404, f"unknown step {name!r} (available: {', '.join(sorted(self.steps))})")
        return self.steps[name]

    def _step_schema(self, name: str):
        module = self._get_step(name)
        return {
            "step": name,
            "task_intent": module.TASK_INTENT,
            "input_schema": [_field_doc(s) for s in module.INPUT_SCHEMA],
            "output_schema": [_field_doc(s) for s in module.OUTPUT_SCHEMA],
        }

    def _validate_output(self, name: str, body: dict | None):
        module = self._get_step(name)
        if not isinstance(body, dict):
            raise ApiError(400, "request body must be a JSON object (the candidate step output)")
        ok, errors = module.validate_output(body)
        if not ok:
            raise ApiError(400, "; ".join(errors))
        return {"valid": True, "step": name}

    def _project(self, body: dict | None):
        if not isinstance(body, dict):
            raise ApiError(400, "request body must be a JSON object")
        for key in ("source", "profiles", "profile"):
            if not body.get(key):
                raise ApiError(400, f"missing required field {key!r}")
        source = self._jail(body["source"], "source")
        profiles_path = self._jail(body["profiles"], "profiles")
        if not source.exists():
            raise ApiError(404, f"source not found: {body['source']}")
        if not profiles_path.exists():
            raise ApiError(404, f"profiles config not found: {body['profiles']}")
        from projection import projector  # noqa: PLC0415

        try:
            ladders, profiles = projector.load_config(profiles_path)
            if body["profile"] not in profiles:
                raise ApiError(
                    400, f"unknown profile {body['profile']!r} (available: {', '.join(sorted(profiles))})")
            bank = projector.load_terms(None)
            text, dropped = projector.project(
                source, profiles[body["profile"]], ladders, bank,
                keep_fm=bool(body.get("keep_frontmatter")),
            )
        except projector.ProjectionError as e:
            raise ApiError(400, str(e)) from None
        return {"profile": body["profile"], "blocks_dropped": dropped, "text": text}

    # ---- #44 capability discovery ----

    def _doctor(self):
        """Tool availability (wraps doctor.check), plus whether the PDF backend is
        ready -- so a client knows what it can call before hitting /render/pdf."""
        import dataclasses  # noqa: PLC0415

        sys.path.insert(0, str(REPO_ROOT))
        import doctor  # noqa: PLC0415

        try:
            results = [dataclasses.asdict(r) for r in doctor.check(doctor.parse_lock())]
        except OSError:
            results = []
        backends = {t: shutil.which(t) is not None for t in ("typst", "pandoc")}
        return {"tools": results, "backends": backends,
                "render_pdf_ready": all(backends.values())}

    def _locales(self):
        """The locale table with a sample formatted number + date each (#35)."""
        sys.path.insert(0, str(REPO_ROOT / "pdf"))
        import locale_fmt  # noqa: PLC0415
        import statement_data  # noqa: PLC0415

        out = []
        for code, cfg in sorted(locale_fmt.LOCALES.items()):
            fmt = {**locale_fmt.number_format(cfg), "currency": "EUR"}
            out.append({
                "code": code, "lang": cfg["lang"],
                "sample_number": statement_data.format_amount(1234567.89, fmt),
                "sample_date": locale_fmt.format_date("2025-02-15", cfg),
            })
        return {"locales": out}

    def _theme_variants(self):
        """The theme variants defined in brand.yaml [theme.variants], plus base (#32)."""
        sys.path.insert(0, str(REPO_ROOT / "tokens" / "gen"))
        from _common import load_tokens  # noqa: PLC0415

        theme = load_tokens(None).get("theme") or {}
        return {"variants": ["base"] + sorted((theme.get("variants") or {}).keys())}

    # ---- profile discovery (Track J, chunk 6.4) ----

    def _profiles_summary(self, profiles_path: Path) -> dict:
        """Names + minimal metadata for the audience menu (OQ11: names+ranks,
        not full ladder governance vocabulary -- a private skin's clearance
        scheme is not something every consumer wants on an HTTP surface even
        on loopback). Reuses projector.load_config exactly (F1's own fail-
        closed ladder validation), so a broken profiles.yaml surfaces the
        same error here as it would at render time."""
        sys.path.insert(0, str(REPO_ROOT))
        from projection import projector  # noqa: PLC0415

        try:
            ladders, profiles = projector.load_config(profiles_path)
        except projector.ProjectionError as e:
            raise ApiError(400, str(e)) from None
        rows = []
        for name, prof in profiles.items():
            rows.append({
                "name": name,
                "clearance_ceiling": prof.get("clearance_ceiling"),
                "clearance_rank": ladders["clearance"][prof["clearance_ceiling"]],
                "releasable_to": prof.get("releasable_to"),
                "distribution_rank": ladders["distribution"][prof["releasable_to"]],
                "lang": prof.get("lang"),
                "audience": prof.get("audience"),
                "disclosure": prof.get("disclosure"),
            })
        rows.sort(key=lambda r: r["name"])
        return {
            "ladders": {
                "clearance": sorted(ladders["clearance"], key=ladders["clearance"].get),
                "distribution": sorted(ladders["distribution"], key=ladders["distribution"].get),
            },
            "profiles": rows,
        }

    def _profiles_by_path(self, body: dict | None):
        if not isinstance(body, dict) or not body.get("path"):
            raise ApiError(400, "missing required query param 'path'")
        profiles_path = self._jail(body["path"], "path")
        if not profiles_path.is_file():
            raise ApiError(404, f"profiles config not found: {body['path']}")
        return self._profiles_summary(profiles_path)

    def _project_profiles(self, name: str):
        sys.path.insert(0, str(REPO_ROOT))
        from api import store  # noqa: PLC0415

        try:
            detail = self._project_store().get(name, limit=0)
        except store.ManifestError as e:
            raise ApiError(404, str(e)) from None
        project_dir = Path(detail["path"])
        profiles_rel = detail["manifest"].get("profiles")
        if not profiles_rel:
            raise ApiError(400, f"project {name!r} manifest has no 'profiles' field")
        profiles_path = (project_dir / profiles_rel).resolve()
        try:
            profiles_path.relative_to(project_dir)  # a project's own jail, not self.root
        except ValueError:
            raise ApiError(403, f"profiles path escapes the project directory: {profiles_rel!r}") from None
        if not profiles_path.is_file():
            raise ApiError(404, f"profiles config not found: {profiles_rel}")
        return self._profiles_summary(profiles_path)

    # ---- #43 statement reconciliation (no render) ----

    def _statement_check(self, body: dict | None):
        """Compute + reconcile a statement spec without rendering: rows out, or a
        400 with the reconciliation/validation error. Input is exactly one of
        `data` (a YAML/JSON string), `spec` (a JSON object), or `source` (a jailed
        path); an optional `locale` supplies default number formatting."""
        if not isinstance(body, dict):
            raise ApiError(400, "request body must be a JSON object")
        provided = [k for k in ("data", "spec", "source") if body.get(k) is not None]
        if len(provided) != 1:
            raise ApiError(400, "provide exactly one of 'data' (string), 'spec' (object), 'source' (path)")

        sys.path.insert(0, str(REPO_ROOT / "pdf"))
        import statement_data  # noqa: PLC0415

        key = provided[0]
        if key == "source":
            path = self._jail(body["source"], "source")
            if not path.exists():
                raise ApiError(404, f"source not found: {body['source']}")
            try:
                spec = statement_data.load_spec(path)
            except statement_data.StatementError as e:
                raise ApiError(400, str(e)) from None
        elif key == "spec":
            spec = body["spec"]
            if not isinstance(spec, dict) or "rows" not in spec:
                raise ApiError(400, "'spec' must be an object with a 'rows' list")
        else:
            import yaml  # noqa: PLC0415
            try:
                spec = yaml.safe_load(body["data"])
            except yaml.YAMLError:
                raise ApiError(400, "'data' is not valid YAML/JSON") from None
            if not isinstance(spec, dict) or "rows" not in spec:
                raise ApiError(400, "'data' must parse to a mapping with a 'rows' list")

        default_format = None
        if body.get("locale"):
            import locale_fmt  # noqa: PLC0415
            try:
                default_format = locale_fmt.number_format(locale_fmt.resolve(body["locale"]))
            except locale_fmt.LocaleError as e:
                raise ApiError(400, str(e)) from None

        try:
            rows = statement_data.compute_rows(spec, default_format)
        except statement_data.StatementError as e:
            raise ApiError(400, str(e)) from None
        return {"reconciled": True, "rows": rows}

    MAX_INLINE_BYTES = 512 * 1024

    def _render_pdf(self, body: dict | None):
        """D9 render-as-a-service: markdown (inline or a jailed path) + options ->
        the rendered PDF (or a first-page PNG preview). The typst backend's own
        data-path jail is pointed at the server root (source mode) or the temp dir
        (inline mode) so an untrusted document cannot read outside the sandbox."""
        if not isinstance(body, dict):
            raise ApiError(400, "request body must be a JSON object")
        fmt = body.get("format", "pdf")
        if fmt not in ("pdf", "png"):
            raise ApiError(400, "format must be 'pdf' or 'png'")
        markdown, source = body.get("markdown"), body.get("source")
        if bool(markdown) == bool(source):
            raise ApiError(400, "provide exactly one of 'markdown' (inline) or 'source' (path under root)")

        opts = {k: body.get(k) for k in ("title", "subtitle", "org", "date", "locale")}
        opts["paper"] = body.get("paper", "a4")
        opts["variant"] = body.get("variant", "base")
        opts["project"] = body.get("project")
        opts["profiles"] = str(self._jail(body["profiles"], "profiles")) if body.get("profiles") else None
        brand = str(self._jail(body["brand"], "brand")) if body.get("brand") else None
        font_paths = body.get("font_paths")
        if font_paths is not None:
            if not isinstance(font_paths, list):
                raise ApiError(400, "'font_paths' must be a list of paths under the server root")
            font_paths = [str(self._jail(p, "font-path")) for p in font_paths]

        import tempfile

        sys.path.insert(0, str(REPO_ROOT / "pdf"))
        import typst_backend  # noqa: PLC0415

        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            if markdown is not None:
                if len(markdown.encode("utf-8")) > self.MAX_INLINE_BYTES:
                    raise ApiError(413, "inline markdown exceeds the size limit")
                src = td / "input.md"
                src.write_text(markdown, encoding="utf-8")
                data_root = td  # inline: statement data may not read server files
            else:
                src = self._jail(source, "source")
                if not src.exists():
                    raise ApiError(404, f"source not found: {source}")
                data_root = self.root
            out = td / f"out.{fmt}"
            page = body.get("page", 1)
            if not isinstance(page, int) or page < 1:
                raise ApiError(400, "page must be a positive integer")
            counts: list = []
            try:
                typst_backend.render_pdf(src, out, brand=brand, fmt=fmt, data_root=data_root,
                                         page=page, page_count=counts, font_paths=font_paths, **opts)
            except typst_backend.TypstBackendError as e:
                raise ApiError(400, str(e)) from None
            data = out.read_bytes()

        if fmt == "pdf":
            return BinaryResponse(data, "application/pdf", filename="render.pdf")
        total = counts[0] if counts else 1
        return BinaryResponse(data, "image/png", extra_headers={"X-Total-Pages": str(total)})

    DOCX_CTYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    def _render_docx(self, body: dict | None):
        """D9 render-as-a-service, DOCX peer of /render/pdf: markdown (inline or a
        jailed path) -> a styled DOCX via the render-doc.sh pipeline. The source is
        rendered from a temp copy so the server's own files are never mutated by the
        provenance-uid embed; images resolve via RESOURCE_PATH to the original dir."""
        if not isinstance(body, dict):
            raise ApiError(400, "request body must be a JSON object")
        markdown, source = body.get("markdown"), body.get("source")
        if bool(markdown) == bool(source):
            raise ApiError(400, "provide exactly one of 'markdown' (inline) or 'source' (path under root)")
        profile = body.get("profile", "reference")
        name = body.get("name")
        project = body.get("project")
        profiles = str(self._jail(body["profiles"], "profiles")) if body.get("profiles") else None

        import shutil
        import tempfile

        sys.path.insert(0, str(REPO_ROOT))
        from docstyle import docx_pipeline  # noqa: PLC0415

        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            work_src = td / "input.md"
            if markdown is not None:
                if len(markdown.encode("utf-8")) > self.MAX_INLINE_BYTES:
                    raise ApiError(413, "inline markdown exceeds the size limit")
                work_src.write_text(markdown, encoding="utf-8")
                resource_path = td
            else:
                original = self._jail(source, "source")
                if not original.exists():
                    raise ApiError(404, f"source not found: {source}")
                shutil.copyfile(original, work_src)  # render a copy: never mutate the original
                resource_path = original.parent
            out_dir = td / "out"
            try:
                produced = docx_pipeline.render_docx(
                    work_src, out_dir, name=name, profile=profile, project=project,
                    profiles=profiles, resource_path=resource_path)
            except docx_pipeline.DocxBackendError as e:
                raise ApiError(400, str(e)) from None
            data = produced.read_bytes()
        return BinaryResponse(data, self.DOCX_CTYPE, filename="render.docx")


class HtmlResponse:
    def __init__(self, html: str):
        self.html = html


class BinaryResponse:
    def __init__(self, data: bytes, content_type: str, filename: str | None = None,
                 extra_headers: dict | None = None):
        self.data = data
        self.content_type = content_type
        self.filename = filename
        self.extra_headers = extra_headers or {}


def make_wsgi_app(api: RenderfactApi):
    def app(environ, start_response):
        try:
            api._guard(environ)
            method = environ["REQUEST_METHOD"]
            path = environ.get("PATH_INFO", "/")
            query = environ.get("QUERY_STRING", "")
            # Real WSGI servers split the query into QUERY_STRING; the in-process
            # test driver leaves it on PATH_INFO. Normalise both so query params
            # are available regardless of transport.
            if "?" in path:
                path, _, embedded = path.partition("?")
                query = embedded if not query else f"{query}&{embedded}"
            body = None
            if method in ("POST", "PUT"):
                try:
                    length = int(environ.get("CONTENT_LENGTH") or 0)
                except ValueError:
                    length = 0
                raw = environ["wsgi.input"].read(length) if length else b""
                if raw:
                    try:
                        body = json.loads(raw.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        raise ApiError(400, "request body is not valid JSON") from None
            # For requests carrying no JSON body, expose query params as
            # `body` so read handlers (e.g. ?limit=) can consume them uniformly.
            if body is None and query:
                from urllib.parse import parse_qsl  # noqa: PLC0415

                body = dict(parse_qsl(query))
            result = api.route(method, path, body, environ)
        except ApiError as e:
            payload = json.dumps({"error": e.message}).encode("utf-8")
            start_response(f"{e.status} {_reason(e.status)}",
                           [("Content-Type", "application/json; charset=utf-8"),
                            ("Content-Length", str(len(payload)))])
            return [payload]
        if isinstance(result, BinaryResponse):
            headers = [("Content-Type", result.content_type),
                       ("Content-Length", str(len(result.data)))]
            if result.filename:
                headers.append(("Content-Disposition", f'attachment; filename="{result.filename}"'))
            headers += list(result.extra_headers.items())
            start_response("200 OK", headers)
            return [result.data]
        if isinstance(result, HtmlResponse):
            payload = result.html.encode("utf-8")
            ctype = "text/html; charset=utf-8"
        else:
            payload = json.dumps(result, indent=2).encode("utf-8")
            ctype = "application/json; charset=utf-8"
        start_response("200 OK", [("Content-Type", ctype),
                                  ("Content-Length", str(len(payload)))])
        return [payload]

    return app


def _reason(status: int) -> str:
    return {400: "Bad Request", 403: "Forbidden", 404: "Not Found",
            409: "Conflict", 413: "Payload Too Large",
            429: "Too Many Requests"}.get(status, "Error")


def openapi_spec(api: RenderfactApi) -> dict:
    """Hand-authored OpenAPI 3 description of the small route surface."""
    step_names = sorted(api.steps)
    return {
        "openapi": "3.0.3",
        "info": {
            "title": "renderfact API",
            "version": "0.4.0",
            "description": "Same contract, HTTP instead of copy-paste (D9). "
                           "Localhost-bound, no authentication: do not expose.",
        },
        "paths": {
            "/": {"get": {"summary": "Service info", "responses": {"200": {"description": "info"}}}},
            "/session": {"get": {"summary": "Issue a CSRF token for future mutating endpoints",
                                 "responses": {"200": {"description": "token"}}}},
            "/steps": {"get": {"summary": "List D8 step contracts",
                               "responses": {"200": {"description": f"steps: {', '.join(step_names)}"}}}},
            "/steps/{name}": {"get": {"summary": "Input/output schema of one step",
                                      "parameters": [{"name": "name", "in": "path", "required": True,
                                                      "schema": {"type": "string", "enum": step_names}}],
                                      "responses": {"200": {"description": "schemas"},
                                                    "404": {"description": "unknown step"}}}},
            "/steps/{name}/validate-output": {
                "post": {"summary": "Validate a candidate step output against the contract",
                         "responses": {"200": {"description": "valid"},
                                       "400": {"description": "invalid, error lists the violations"}}}},
            "/project": {
                "post": {"summary": "Project a source through one profile (F1 engine)",
                         "requestBody": {"content": {"application/json": {"schema": {
                             "type": "object",
                             "required": ["source", "profiles", "profile"],
                             "properties": {
                                 "source": {"type": "string", "description": "path under server root"},
                                 "profiles": {"type": "string", "description": "ladders+profiles yaml path"},
                                 "profile": {"type": "string"},
                                 "keep_frontmatter": {"type": "boolean"}}}}}},
                         "responses": {"200": {"description": "projected markdown + blocks_dropped"},
                                       "403": {"description": "path escapes server root"}}}},
            "/render/pdf": {
                "post": {"summary": "Render markdown to a PDF (or first-page PNG preview) via the typst backend",
                         "requestBody": {"content": {"application/json": {"schema": {
                             "type": "object",
                             "description": "exactly one of markdown|source, plus options",
                             "properties": {
                                 "markdown": {"type": "string", "description": "inline source (<=512 KB)"},
                                 "source": {"type": "string", "description": "path under server root"},
                                 "format": {"type": "string", "enum": ["pdf", "png"], "default": "pdf"},
                                 "title": {"type": "string"}, "subtitle": {"type": "string"},
                                 "org": {"type": "string"}, "date": {"type": "string"},
                                 "variant": {"type": "string"}, "locale": {"type": "string"},
                                 "paper": {"type": "string"}, "brand": {"type": "string"},
                                 "project": {"type": "string", "description": "audience profile name"},
                                 "profiles": {"type": "string", "description": "ladders+profiles yaml path"}}}}}},
                         "responses": {"200": {"description": "application/pdf or image/png bytes"},
                                       "400": {"description": "bad input or a render/reconciliation error"},
                                       "413": {"description": "inline markdown too large"}}}},
            "/render/docx": {
                "post": {"summary": "Render markdown to a styled DOCX via the render-doc.sh pipeline",
                         "requestBody": {"content": {"application/json": {"schema": {
                             "type": "object",
                             "description": "exactly one of markdown|source, plus options",
                             "properties": {
                                 "markdown": {"type": "string", "description": "inline source (<=512 KB)"},
                                 "source": {"type": "string", "description": "path under server root"},
                                 "profile": {"type": "string", "enum": ["reference", "compact"]},
                                 "name": {"type": "string"},
                                 "project": {"type": "string", "description": "audience profile name"},
                                 "profiles": {"type": "string", "description": "ladders+profiles yaml path"}}}}}},
                         "responses": {"200": {"description": "application/vnd...wordprocessingml.document bytes"},
                                       "400": {"description": "bad input or a render error (e.g. pandoc missing)"},
                                       "413": {"description": "inline markdown too large"}}}},
            "/statement/check": {
                "post": {"summary": "Compute + reconcile a statement spec without rendering",
                         "requestBody": {"content": {"application/json": {"schema": {
                             "type": "object",
                             "description": "exactly one of data|spec|source, plus optional locale",
                             "properties": {
                                 "data": {"type": "string", "description": "YAML/JSON statement spec"},
                                 "spec": {"type": "object", "description": "statement spec object"},
                                 "source": {"type": "string", "description": "path under server root"},
                                 "locale": {"type": "string"}}}}}},
                         "responses": {"200": {"description": "reconciled rows"},
                                       "400": {"description": "reconciliation or validation error"}}}},
            "/doctor": {"get": {"summary": "Tool availability + whether the PDF backend is ready",
                                "responses": {"200": {"description": "tools + backends"}}}},
            "/locales": {"get": {"summary": "Supported locales with sample number/date",
                                 "responses": {"200": {"description": "locales"}}}},
            "/theme/variants": {"get": {"summary": "Theme variants from brand.yaml",
                                        "responses": {"200": {"description": "variants"}}}},
            "/projects": {
                "get": {"summary": "List projects under the projects root (Track J, 6.1)",
                       "responses": {"200": {"description": "project summaries"}}},
                "post": {"summary": "Create a new project (Track J, 6.2). Requires a CSRF token from GET /session.",
                         "requestBody": {"content": {"application/json": {"schema": {
                             "type": "object", "required": ["name"],
                             "properties": {
                                 "name": {"type": "string", "description": "project slug"},
                                 "title": {"type": "string"},
                                 "template": {"type": "string", "description": "built-in templates/ pack name"},
                                 "doc_type": {"type": "string", "enum": ["report", "deck", "poster", "sheet"]},
                                 "diagram_scaffold": {"type": "string", "enum": ["none", "mermaid", "d2"]},
                                 "default_profile": {"type": "string"},
                                 "formats": {"type": "array", "items": {"type": "string"}},
                                 "locale": {"type": "string"}}}}}},
                         "responses": {"200": {"description": "the new project's manifest + history + git"},
                                       "400": {"description": "bad input"},
                                       "403": {"description": "missing/invalid CSRF token or cross-origin"},
                                       "409": {"description": "a project with that name already exists"}}}},
            "/projects/{name}": {
                "get": {"summary": "One project's manifest, render-ledger tail, and git facts",
                        "parameters": [
                            {"name": "name", "in": "path", "required": True,
                             "schema": {"type": "string"}},
                            {"name": "limit", "in": "query", "required": False,
                             "schema": {"type": "integer", "default": 20},
                             "description": "render-ledger entries to include"}],
                        "responses": {"200": {"description": "manifest + history + git + manifest_hash"},
                                      "404": {"description": "unknown or invalid project name"}}}},
            "/projects/{name}/config": {
                "put": {"summary": "Mutate manifest fields (Track J, 6.2), hash-guarded + one commit per change. "
                                   "Requires a CSRF token from GET /session.",
                        "parameters": [{"name": "name", "in": "path", "required": True,
                                        "schema": {"type": "string"}}],
                        "requestBody": {"content": {"application/json": {"schema": {
                            "type": "object", "required": ["patch", "base_hash", "message"],
                            "properties": {
                                "patch": {"type": "object", "description": "mutable manifest fields to merge"},
                                "base_hash": {"type": "string", "description": "manifest_hash from a prior GET"},
                                "message": {"type": "string", "description": "required non-empty commit message"}}}}}},
                        "responses": {"200": {"description": "{changed, manifest_hash[, commit]}"},
                                      "400": {"description": "bad patch, empty message, or not a git work tree"},
                                      "403": {"description": "missing/invalid CSRF token or cross-origin"},
                                      "404": {"description": "unknown project"},
                                      "409": {"description": "base_hash is stale; re-GET and retry"}}}},
            "/projects/{name}/profiles": {
                "get": {"summary": "Audience profiles defined in a project's own profiles.yaml (Track J, 6.4): "
                                   "names + minimal metadata (clearance/distribution rank, lang, audience, "
                                   "disclosure), not the full ladder governance vocabulary",
                        "parameters": [{"name": "name", "in": "path", "required": True,
                                        "schema": {"type": "string"}}],
                        "responses": {"200": {"description": "ladders (ordered value lists) + profile rows"},
                                      "400": {"description": "manifest has no 'profiles' field, or it fails to parse"},
                                      "404": {"description": "unknown project or missing profiles file"}}}},
            "/profiles": {
                "get": {"summary": "Same shape as /projects/{name}/profiles for an arbitrary profiles.yaml "
                                   "path (the New Project wizard's profile-source step, before a project exists)",
                        "parameters": [{"name": "path", "in": "query", "required": True,
                                        "schema": {"type": "string"}, "description": "path under server root"}],
                        "responses": {"200": {"description": "ladders + profile rows"},
                                      "400": {"description": "config fails to parse"},
                                      "404": {"description": "path not found"}}}},
            "/templates": {
                "get": {"summary": "List template library entries (Track J, 6.3): built-in + custom root, merged",
                       "responses": {"200": {"description": "template summaries"}}}},
            "/templates/{name}": {
                "get": {"summary": "One template entry's metadata, scaffold source, and derived profile",
                        "parameters": [{"name": "name", "in": "path", "required": True,
                                        "schema": {"type": "string"}}],
                        "responses": {"200": {"description": "metadata + scaffold + profile"},
                                      "404": {"description": "unknown template"}}}},
            "/templates/import": {
                "post": {"summary": "Import a branded DOCX into the custom library root via the C7 "
                                    "import-template pipeline. Requires a CSRF token from GET /session.",
                         "requestBody": {"content": {"application/json": {"schema": {
                             "type": "object", "required": ["name", "source"],
                             "properties": {
                                 "name": {"type": "string", "description": "new library entry slug"},
                                 "source": {"type": "string", "description": "path under server root: the .docx to import"},
                                 "doc_type": {"type": "string"}, "description": {"type": "string"},
                                 "diagram_scaffolds": {"type": "array", "items": {"type": "string"}},
                                 "copy_reference": {"type": "boolean"},
                                 "check_probe": {"type": "string",
                                                "description": "path under server root: idempotency-gate probe .md"}}}}}},
                         "responses": {"200": {"description": "the new entry's metadata + import_output + idempotency_check_passed"},
                                       "400": {"description": "bad input or derivation failure"},
                                       "403": {"description": "missing/invalid CSRF token or cross-origin"},
                                       "409": {"description": "a template with that name already exists"}}}},
        },
    }


def render_docs_html(api: RenderfactApi) -> str:
    """Self-contained /docs page (no external assets: same posture as the UI)."""
    spec = openapi_spec(api)
    rows = []
    for path, methods in spec["paths"].items():
        for method, op in methods.items():
            rows.append(f"<tr><td><code>{method.upper()}</code></td>"
                        f"<td><code>{path}</code></td><td>{op['summary']}</td></tr>")
    return ("<!doctype html><meta charset='utf-8'><title>renderfact API</title>"
            "<style>body{font-family:sans-serif;margin:2rem;max-width:60rem}"
            "table{border-collapse:collapse}td,th{border:1px solid #ccc;padding:.4rem .6rem}"
            "</style><h1>renderfact API</h1>"
            f"<p>{spec['info']['description']}</p>"
            "<table><tr><th>Method</th><th>Path</th><th>Summary</th></tr>"
            + "".join(rows) +
            "</table><p>Machine-readable: <a href='/openapi.json'>/openapi.json</a></p>")


# ---- workspace screens (Track J, chunk 6.5 / D23) ----
# Each shell is a small Python string (matching render_docs_html's pattern);
# the substantial JS/CSS logic lives in api/static/ files, not inline.

_WORKSPACE_STYLE = (
    "body{font-family:sans-serif;margin:1.5rem;max-width:78rem}"
    "h1{font-size:1.3rem}h2{font-size:1.05rem;margin-top:1.6rem}"
    ".hint{color:#666;font-size:.85rem}"
    ".err{color:#b00;font-family:monospace;white-space:pre-wrap;font-size:.85rem}"
    "nav a{margin-right:1rem}"
)


def render_dashboard_html() -> str:
    """GET /ui/projects: the Projects Dashboard (design spike 5.1)."""
    return (
        "<!doctype html><meta charset='utf-8'><title>renderfact projects</title>"
        f"<link rel='stylesheet' href='/ui/static/dashboard.css'>"
        f"<style>{_WORKSPACE_STYLE}</style>"
        "<h1>Projects <span id='doctor' class='hint'></span></h1>"
        "<nav><a href='/ui/projects/new'>+ New project</a>"
        "<a href='/ui/templates'>Template library</a>"
        "<a href='/ui'>Scratchpad studio</a></nav>"
        "<div id='cards' class='cards'></div>"
        "<div id='err' class='err'></div>"
        "<script src='/ui/static/common.js'></script>"
        "<script src='/ui/static/dashboard.js'></script>"
    )


def render_wizard_html() -> str:
    """GET /ui/projects/new: the New Project wizard, manual path only (design
    spike 5.2; auto-choose is chunk 6.7, deferred so this ships without any
    LLM machinery)."""
    return (
        "<!doctype html><meta charset='utf-8'><title>renderfact: new project</title>"
        f"<style>{_WORKSPACE_STYLE}"
        ".step{margin:1rem 0}label{display:block;margin:.4rem 0 .15rem;font-size:.9rem}"
        "input,select,textarea{font-family:monospace;box-sizing:border-box;width:100%;"
        "max-width:28rem;padding:.3rem}"
        ".cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(14rem,1fr));gap:.8rem}"
        ".card{border:1px solid #ccc;border-radius:.3rem;padding:.6rem;cursor:pointer}"
        ".card.selected{border-color:#2E7D32;box-shadow:0 0 0 1px #2E7D32}"
        "</style>"
        "<h1>New project</h1>"
        "<nav><a href='/ui/projects'>&larr; Dashboard</a></nav>"
        "<div class='step'><label for='w-name'>Project name (slug)</label>"
        "<input id='w-name' placeholder='q3-partner-briefing'></div>"
        "<div class='step'><label for='w-title'>Display title (optional)</label>"
        "<input id='w-title' placeholder='Q3 Partner Briefing'></div>"
        "<div class='step'><label>Template <span class='hint'>(manual selection -- "
        "renderfact does not choose for you yet)</span></label>"
        "<div id='w-templates' class='cards'></div></div>"
        "<div class='step'><label for='w-doctype'>Document type</label>"
        "<select id='w-doctype'><option value='report'>report</option>"
        "<option value='deck'>deck</option><option value='poster'>poster</option>"
        "<option value='sheet'>sheet</option></select></div>"
        "<div class='step'><label for='w-scaffold'>Diagram scaffold</label>"
        "<select id='w-scaffold'><option value='none'>none</option>"
        "<option value='mermaid'>mermaid</option><option value='d2'>d2</option></select></div>"
        "<div class='step'><button onclick='createProject()'>Create project</button></div>"
        "<div id='err' class='err'></div>"
        "<script src='/ui/static/common.js'></script>"
        "<script src='/ui/static/wizard.js'></script>"
    )


def render_template_library_html() -> str:
    """GET /ui/templates: the Template Library (design spike 5.6)."""
    return (
        "<!doctype html><meta charset='utf-8'><title>renderfact: templates</title>"
        f"<style>{_WORKSPACE_STYLE}"
        ".cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(16rem,1fr));gap:.8rem}"
        ".card{border:1px solid #ccc;border-radius:.3rem;padding:.6rem}"
        ".tag{font-size:.75rem;color:#666;border:1px solid #ccc;border-radius:.2rem;"
        "padding:0 .3rem;margin-left:.3rem}"
        "form.import{margin-top:1rem;max-width:28rem}"
        "form.import input{font-family:monospace;box-sizing:border-box;width:100%;padding:.3rem;"
        "margin:.2rem 0}"
        "</style>"
        "<h1>Template library</h1>"
        "<nav><a href='/ui/projects'>&larr; Dashboard</a></nav>"
        "<div id='cards' class='cards'></div>"
        "<h2>Import a branded DOCX</h2>"
        "<p class='hint'>Wraps <code>render import-template</code> (C7). Path is under the "
        "server root.</p>"
        "<form class='import' onsubmit='return false'>"
        "<input id='t-name' placeholder='new template slug'>"
        "<input id='t-source' placeholder='path/to/corporate.docx'>"
        "<input id='t-doctype' placeholder='doc_type (default: report)'>"
        "<input id='t-description' placeholder='description (optional)'>"
        "<button onclick='importTemplate()'>Import</button>"
        "</form>"
        "<div id='err' class='err'></div>"
        "<script src='/ui/static/common.js'></script>"
        "<script src='/ui/static/templates-library.js'></script>"
    )


def main(argv: list[str] | None = None) -> int:
    import argparse
    from wsgiref.simple_server import make_server, WSGIRequestHandler

    parser = argparse.ArgumentParser(
        prog="render serve",
        description="Serve the renderfact API (localhost by default; no auth).",
    )
    parser.add_argument("--port", type=int, default=8385)
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--root", default=None,
                        help="filesystem jail root for request paths (default: cwd)")
    parser.add_argument("--projects-root", default=None,
                        help="project registry root scanned by /projects "
                             "(default: <root>/projects)")
    parser.add_argument("--templates-root", default=None,
                        help="custom template library root for /templates "
                             "(default: <root>/templates; merged with the built-in "
                             "templates/library/ entries shipped in this repo)")
    parser.add_argument("--enable-ui", action="store_true",
                        help="mount the thin reference UI at /ui (off by default)")
    parser.add_argument("--rate-limit", type=int, default=120,
                        help="requests per client per 10s window")
    args = parser.parse_args(argv)

    if args.bind not in ("127.0.0.1", "localhost", "::1"):
        print("WARNING: this server has NO authentication or authorization controls; "
              "only bind to non-localhost in trusted network environments.", file=sys.stderr)

    api = RenderfactApi(root=Path(args.root) if args.root else None,
                        enable_ui=args.enable_ui, rate_limit=args.rate_limit,
                        projects_root=Path(args.projects_root) if args.projects_root else None,
                        templates_root=Path(args.templates_root) if args.templates_root else None)

    class QuietHandler(WSGIRequestHandler):
        def log_message(self, fmt, *log_args):  # one line, no noise
            print(f"  {self.address_string()} {fmt % log_args}")

    with make_server(args.bind, args.port, make_wsgi_app(api),
                     handler_class=QuietHandler) as httpd:
        print(f"renderfact API on http://{args.bind}:{httpd.server_port} "
              f"(root: {api.root}{', UI at /ui' if args.enable_ui else ''})")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
