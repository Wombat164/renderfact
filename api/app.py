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
                 rate_limit: int = 120):
        self.root = (root or Path.cwd()).resolve()
        self.enable_ui = enable_ui
        self.limiter = RateLimiter(limit=rate_limit)
        self.csrf_tokens: set[str] = set()
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
        if environ["REQUEST_METHOD"] == "POST":
            origin = environ.get("HTTP_ORIGIN")
            fetch_site = environ.get("HTTP_SEC_FETCH_SITE")
            if origin is not None:
                m = re.match(r"https?://([^/:]+)(:\d+)?$", origin)
                if not m or m.group(1) not in LOOPBACK_HOSTS:
                    raise ApiError(403, f"cross-origin POST rejected: {origin!r}")
            elif fetch_site is not None and fetch_site not in ("same-origin", "none"):
                raise ApiError(403, f"cross-site POST rejected: Sec-Fetch-Site={fetch_site!r}")

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

    # ---- routes ----

    def route(self, method: str, path: str, body: dict | None):
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
        raise ApiError(404, f"no route: {method} {path}")

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
                "POST /render/pdf", "POST /statement/check",
                "GET /doctor", "GET /locales", "GET /theme/variants",
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
            try:
                typst_backend.render_pdf(src, out, brand=brand, fmt=fmt, data_root=data_root, **opts)
            except typst_backend.TypstBackendError as e:
                raise ApiError(400, str(e)) from None
            data = out.read_bytes()

        if fmt == "pdf":
            return BinaryResponse(data, "application/pdf", filename="render.pdf")
        return BinaryResponse(data, "image/png")


class HtmlResponse:
    def __init__(self, html: str):
        self.html = html


class BinaryResponse:
    def __init__(self, data: bytes, content_type: str, filename: str | None = None):
        self.data = data
        self.content_type = content_type
        self.filename = filename


def make_wsgi_app(api: RenderfactApi):
    def app(environ, start_response):
        try:
            api._guard(environ)
            method = environ["REQUEST_METHOD"]
            path = environ.get("PATH_INFO", "/")
            body = None
            if method == "POST":
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
            result = api.route(method, path, body)
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
            413: "Payload Too Large", 429: "Too Many Requests"}.get(status, "Error")


def openapi_spec(api: RenderfactApi) -> dict:
    """Hand-authored OpenAPI 3 description of the small route surface."""
    step_names = sorted(api.steps)
    return {
        "openapi": "3.0.3",
        "info": {
            "title": "renderfact API",
            "version": "0.2.0",
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
    parser.add_argument("--enable-ui", action="store_true",
                        help="mount the thin reference UI at /ui (off by default)")
    parser.add_argument("--rate-limit", type=int, default=120,
                        help="requests per client per 10s window")
    args = parser.parse_args(argv)

    if args.bind not in ("127.0.0.1", "localhost", "::1"):
        print("WARNING: this server has NO authentication or authorization controls; "
              "only bind to non-localhost in trusted network environments.", file=sys.stderr)

    api = RenderfactApi(root=Path(args.root) if args.root else None,
                        enable_ui=args.enable_ui, rate_limit=args.rate_limit)

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
