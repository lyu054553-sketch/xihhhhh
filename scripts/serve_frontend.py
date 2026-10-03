"""Serve the public frontend and forward explicitly supported v1.2 API routes.

This development server has no business rules, database, or sample API responses.
"""

from __future__ import annotations

import argparse
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
import re
import shutil
import socket
from urllib.parse import quote, unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
MAX_BODY_BYTES = 6 * 1024 * 1024
PUBLIC_FILES = {
    "index.html", "app.js", "styles.css", "favicon.svg", "README.md", "API_CONTRACT.md",
    "retail-app.js", "retail-app.css", "retail-workbenches.js", "retail-workbenches.css",
    "retail-simulation.js", "retail-simulation.css",
    "assets/hackathon/preview.html", "assets/hackathon/decision/preview.html",
    "assets/hackathon/followup/preview.html",
}
PUBLIC_DOCS = {
    "docs/API_CONTRACT_V0_3_DRAFT.md", "docs/FRONTEND_INTEGRATION.md",
    "docs/DEMO_RUNBOOK.md", "docs/DEMO_SLIDES.html", "docs/DEMO_SLIDES.pptx",
    "docs/VALIDATION_RESULT.md", "docs/ZHU_DELIVERY.md", "docs/FRONTEND_BLUEPRINT.md",
    "docs/ZHU_NEXT_ITERATION.md", "docs/USER_VALIDATION.md", "docs/COMPETITION_CHECKLIST.md",
    "docs/BACKEND_CONCURRENCY_FIX.md",
    "docs/demo-recording/live-flow.webm", "docs/demo-recording/live-flow.png",
}
ASSET_SUFFIXES = {".js", ".mjs", ".css", ".woff2", ".svg", ".png", ".jpg", ".jpeg", ".webp", ".ico", ".txt"}
DATA_SUFFIXES = {".json", ".csv", ".md", ".txt"}
FORWARDED_REQUEST_HEADERS = ("Content-Type", "Accept", "Authorization", "X-Request-ID", "X-Tenant-Id", "Idempotency-Key")
FORWARDED_RESPONSE_HEADERS = ("Content-Type", "Content-Encoding", "Content-Language", "Retry-After", "X-Request-ID")
READ_ROUTE = re.compile(
    r"/api/v1/(?:retail/(?:overview|simulation-options)|risks(?:/[0-9]+)?|"
    r"workbenches/(?:transfer|expiry-rescue|procurement-brake)|"
    r"proposals(?:/[A-Za-z0-9_-]+/versions)?|execution-tasks|data-center|work-items|cases|"
    r"hackathon/(?:context|proposals|overview|tasks|tasks/[A-Za-z0-9_-]+|accounting|"
    r"agent-runs/[A-Za-z0-9_-]+|materials/drafts/[A-Za-z0-9_-]+|"
    r"materials/[A-Za-z0-9_-]+(?:/image)?|cases/[A-Za-z0-9_-]+))\Z"
)
WRITE_ROUTE = re.compile(
    r"/api/v1/(?:retail/simulate|risks/[0-9]+/(?:investigations|replan)|"
    r"investigations/[A-Za-z0-9_-]+/feedback|feedback/[A-Za-z0-9_-]+/(?:confirm|revisions)|"
    r"workbenches/(?:transfer|expiry-rescue|procurement-brake)/(?:draft|calculate|save)|"
    r"proposals/[A-Za-z0-9_-]+/(?:submit|approve|execute)|execution-tasks/[A-Za-z0-9_-]+/status|"
    r"hackathon/(?:facts/query|risks/assess|proposals/compare|proposals|"
    r"proposals/[A-Za-z0-9_-]+/confirm|tasks/[A-Za-z0-9_-]+/(?:channel-actions|events)|"
    r"replays/advance|agent-runs|materials/extract|materials/[A-Za-z0-9_-]+/confirm))\Z"
)


def validate_api_base(value: str | None) -> str | None:
    if not value:
        return None
    parts = urlsplit(value)
    try:
        port = parts.port
    except ValueError as error:
        raise ValueError("API base has an invalid port") from error
    if (parts.scheme not in {"http", "https"} or not parts.hostname
            or parts.username is not None or parts.password is not None
            or parts.query or parts.fragment or not parts.path.rstrip("/").endswith("/api/v1")
            or any(char.isspace() for char in value) or "\\" in value
            or any(segment in {".", ".."} for segment in parts.path.split("/"))
            or "%" in parts.path or (port is not None and not 1 <= port <= 65535)):
        raise ValueError("API base must be an HTTP(S) URL ending in /api/v1, without credentials, query, or fragment")
    return value.rstrip("/")


def public_path(relative: str) -> bool:
    path = Path(relative)
    if relative in PUBLIC_FILES or relative in PUBLIC_DOCS:
        return True
    if relative.startswith("assets/"):
        return path.suffix.lower() in ASSET_SUFFIXES
    if relative.startswith("sample-data/"):
        return path.suffix.lower() in DATA_SUFFIXES
    return False


def request_path(target: str) -> str:
    parts = urlsplit(target)
    if parts.scheme or parts.netloc or parts.fragment or re.search(r"%(?![0-9a-fA-F]{2})", parts.path):
        raise ValueError("Invalid request target")
    path = unquote(parts.path, errors="strict")
    if not path.startswith("/") or any(char in path for char in ("\\", ":", "%")):
        raise ValueError("Invalid path")
    if any(ord(char) < 32 or ord(char) == 127 for char in path):
        raise ValueError("Invalid path")
    if any(segment.startswith(".") for segment in path.split("/") if segment):
        raise ValueError("Hidden paths and traversal are not public")
    return path


def serve(root: Path | str = ROOT, api_base: str | None = None,
          host: str = "127.0.0.1", port: int = 8000,
          timeout: float = 30.0) -> ThreadingHTTPServer:
    """Return a bound server; callers own serve_forever(), shutdown(), and close()."""
    root = Path(root).resolve(strict=True)
    upstream = validate_api_base(api_base)
    if not root.is_dir() or timeout <= 0:
        raise ValueError("A directory and positive timeout are required")

    class Handler(BaseHTTPRequestHandler):
        server_version = "FrontendDev/1.2"
        sys_version = ""

        def respond(self, status, body=b"", headers=None):
            try:
                self.send_response(status)
                for key, value in (headers or {}).items():
                    self.send_header(key, value)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(body)
            except ConnectionError:
                pass

        def error(self, status, code, message, retryable=False):
            body = json.dumps({"error": {"code": code, "message": message,
                              "retryable": retryable, "field_errors": []}}, ensure_ascii=False).encode("utf-8")
            self.respond(status, body, {"Content-Type": "application/json; charset=utf-8"})

        def path_or_error(self):
            try:
                return request_path(self.path)
            except (ValueError, UnicodeError):
                self.error(400, "INVALID_PATH", "Invalid or non-public request path.")
                return None

        def do_GET(self):
            path = self.path_or_error()
            if path is None:
                return
            if READ_ROUTE.fullmatch(path):
                if self.command == "HEAD":
                    self.error(405, "METHOD_NOT_ALLOWED", "API reads require GET.")
                else:
                    self.forward(path)
                return
            relative = "index.html" if path == "/" else path.lstrip("/")
            if not public_path(relative):
                self.error(404, "NOT_FOUND", "This resource is not public.")
                return
            file = (root / relative).resolve()
            if not file.is_relative_to(root) or not public_path(file.relative_to(root).as_posix()) or not file.is_file():
                self.error(404, "NOT_FOUND", "This resource is not public.")
                return
            content_type = {".mjs": "text/javascript", ".md": "text/markdown", ".csv": "text/csv"}.get(file.suffix.lower())
            content_type = content_type or mimetypes.guess_type(file.name)[0] or "application/octet-stream"
            if content_type.startswith("text/") or content_type == "application/json":
                content_type += "; charset=utf-8"
            try:
                with file.open("rb") as stream:
                    self.send_response(200)
                    self.send_header("Content-Type", content_type)
                    self.send_header("Content-Length", str(os.fstat(stream.fileno()).st_size))
                    self.send_header("Cache-Control", "no-cache")
                    self.send_header("X-Content-Type-Options", "nosniff")
                    self.end_headers()
                    if self.command != "HEAD":
                        shutil.copyfileobj(stream, self.wfile)
            except ConnectionError:
                pass
            except OSError:
                self.error(404, "NOT_FOUND", "Resource unavailable.")

        do_HEAD = do_GET

        def read_request_body(self, *, required=True):
            """Consume a bounded, fixed-length body before deciding its route.

            Closing a socket with a valid request body still arriving can reset
            the connection before the client receives a rejection. Invalid or
            oversized framing is rejected immediately, without unbounded reads.
            """
            if self.headers.get_all("Transfer-Encoding"):
                self.error(400, "INVALID_REQUEST", "Chunked request bodies are not accepted.")
                return
            lengths = self.headers.get_all("Content-Length", [])
            if not lengths:
                if required:
                    self.error(411, "LENGTH_REQUIRED", "Content-Length is required.")
                    return
                return b""
            if len(lengths) != 1 or not re.fullmatch(r"[0-9]+", lengths[0]):
                self.error(400, "INVALID_REQUEST", "Invalid Content-Length.")
                return
            if len(lengths[0]) > 20:
                self.error(413, "BODY_TOO_LARGE", "Request body exceeds 6 MiB.")
                return
            length = int(lengths[0])
            if length > MAX_BODY_BYTES:
                self.error(413, "BODY_TOO_LARGE", "Request body exceeds 6 MiB.")
                return
            self.connection.settimeout(timeout)
            try:
                body = self.rfile.read(length)
            except (TimeoutError, socket.timeout):
                self.error(408, "REQUEST_TIMEOUT", "Timed out reading the request body.")
                return
            except ConnectionError:
                # A disconnected client cannot receive an error response.
                return
            if len(body) != length:
                self.error(400, "INVALID_REQUEST", "Incomplete request body.")
                return
            return body

        def do_POST(self):
            body = self.read_request_body()
            if body is None:
                return
            path = self.path_or_error()
            if path is None:
                return
            if not WRITE_ROUTE.fullmatch(path):
                self.error(404, "NOT_FOUND", "This API route is not supported by the frontend.")
                return
            self.forward(path, body)

        def reject_write_method(self):
            if self.read_request_body(required=False) is not None:
                self.error(501, "METHOD_NOT_IMPLEMENTED", "This write method is not supported by the frontend.")

        do_PUT = reject_write_method
        do_PATCH = reject_write_method
        do_DELETE = reject_write_method

        def forward(self, path, body=None):
            if upstream is None:
                self.error(503, "API_NOT_CONFIGURED", "Configure AGENT_API_BASE or --api-base with Wei's v1.2 API URL.")
                return
            parts = urlsplit(upstream)
            connection_class = http.client.HTTPSConnection if parts.scheme == "https" else http.client.HTTPConnection
            connection = connection_class(parts.hostname, parts.port, timeout=timeout)
            target = parts.path + quote(path.removeprefix("/api/v1"), safe="/-._~")
            query = urlsplit(self.path).query
            if query:
                target += "?" + query
            headers = {key: self.headers[key] for key in FORWARDED_REQUEST_HEADERS if key in self.headers}
            try:
                connection.request(self.command, target, body=body, headers=headers)
                response = connection.getresponse()
                payload = response.read()
                response_headers = {key: response.getheader(key) for key in FORWARDED_RESPONSE_HEADERS if response.getheader(key) is not None}
                self.respond(response.status, payload, response_headers)
            except (TimeoutError, socket.timeout):
                self.error(504, "UPSTREAM_TIMEOUT", "The configured API did not respond in time.", True)
            except (OSError, http.client.HTTPException):
                self.error(502, "UPSTREAM_UNAVAILABLE", "Cannot reach the configured v1.2 API.", True)
            finally:
                connection.close()

    server = ThreadingHTTPServer((host, port), Handler)
    if upstream:
        parts = urlsplit(upstream)
        local_hosts = {"localhost", "127.0.0.1", "::1", host}
        if parts.hostname in local_hosts and (parts.port or (443 if parts.scheme == "https" else 80)) == server.server_port:
            server.server_close()
            raise ValueError("The upstream API cannot point back to this frontend server")
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--api-base", default=os.environ.get("AGENT_API_BASE"))
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--check", action="store_true", help="Validate configuration without starting a server")
    args = parser.parse_args()
    try:
        api_base = validate_api_base(args.api_base)
        if not 1 <= args.port <= 65535 or args.timeout <= 0:
            raise ValueError("Port must be 1..65535 and timeout must be positive")
    except ValueError as error:
        parser.error(str(error))
    print(f"Frontend: http://{args.host}:{args.port}")
    print(f"Upstream v1.2 API: {api_base or 'not configured; API requests return API_NOT_CONFIGURED'}")
    print("Static frontend and API forwarding only; no database or business server is started.")
    if args.check:
        return
    with serve(ROOT, api_base, args.host, args.port, args.timeout) as server:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
