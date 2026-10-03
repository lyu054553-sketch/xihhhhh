"""The frontend server serves a closed file set and transparently forwards HTTP.

The upstream below is a transport fixture, never an Agent or model implementation.
"""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import http.client
import json
from pathlib import Path
from queue import Queue
import socket
import tempfile
from threading import Thread
import time
import unittest

from scripts.serve_frontend import MAX_BODY_BYTES, serve, validate_api_base


class UpstreamHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        self.server.requests.append((self.path, body, dict(self.headers)))
        self.server.methods.append(self.command)
        if self.server.status is None:
            self.close_connection = True
            return
        time.sleep(self.server.delay)
        payload = self.server.payload
        try:
            self.send_response(self.server.status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Retry-After", "5")
            self.end_headers()
            self.wfile.write(payload)
        except ConnectionError:
            pass

    do_GET = do_POST

    def log_message(self, *args):
        pass


class FrontendServerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        files = {
            "index.html": b"<!doctype html><title>frontend</title>",
            "app.js": b"export const contract = 'v1.2';",
            "styles.css": b"[hidden]{display:none}",
            "assets/js/client.mjs": b"export {};",
            "assets/fonts/icons.woff2": b"font-fixture",
            "API_CONTRACT.md": b"# v1.2",
            "docs/DEMO_SLIDES.pptx": b"deck-fixture",
            "sample-data/generated/dataset.json": b'{"synthetic":true}',
            "backend/api.py": b"private backend",
            ".git/config": b"private git",
            ".venv/secret.txt": b"private environment",
            "tests/private.js": b"private tests",
            "scripts/secret.txt": b"private script",
            "assets/private.db": b"private database",
            "sample-data/private.sqlite3": b"private database",
            "sample-data/generate.py": b"private implementation",
            "docs/ARCHITECTURE.md": b"not in the public document list",
        }
        for name, body in files.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)

    def start(self, server):
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def stop():
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)
            self.assertFalse(thread.is_alive())

        self.addCleanup(stop)
        return server

    def upstream(self, status=200, payload=b'{"fixture":true}', delay=0):
        server = ThreadingHTTPServer(("127.0.0.1", 0), UpstreamHandler)
        server.requests = []
        server.methods = []
        server.status, server.payload, server.delay = status, payload, delay
        return self.start(server)

    def frontend(self, upstream=None, timeout=1):
        base = None if upstream is None else f"http://127.0.0.1:{upstream.server_port}/gateway/api/v1"
        return self.start(serve(self.root, base, port=0, timeout=timeout))

    def request(self, server, path, method="GET", body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            return response.status, response.read(), dict(response.getheaders())
        finally:
            connection.close()

    def test_public_files_and_head(self):
        frontend = self.frontend()
        for path in ("/", "/app.js", "/styles.css", "/assets/js/client.mjs", "/assets/fonts/icons.woff2",
                     "/API_CONTRACT.md", "/docs/DEMO_SLIDES.pptx", "/sample-data/generated/dataset.json"):
            with self.subTest(path=path):
                status, body, headers = self.request(frontend, path)
                self.assertEqual(status, 200)
                self.assertTrue(body)
                self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        status, body, headers = self.request(frontend, "/app.js", "HEAD")
        self.assertEqual((status, body), (200, b""))
        self.assertGreater(int(headers["Content-Length"]), 0)

    def test_nonpublic_files_and_directory_listing_are_denied(self):
        frontend = self.frontend()
        for path in ("/backend/api.py", "/.git/config", "/.venv/secret.txt", "/tests/private.js", "/scripts/secret.txt",
                     "/assets/private.db", "/sample-data/private.sqlite3", "/sample-data/generate.py",
                     "/docs/ARCHITECTURE.md", "/assets/", "/docs/", "/sample-data/"):
            with self.subTest(path=path):
                status, body, _ = self.request(frontend, path)
                self.assertIn(status, (400, 404))
                self.assertNotIn(b"private", body)

    def test_traversal_absolute_targets_and_windows_paths_are_denied(self):
        frontend = self.frontend()
        for path in ("/../index.html", "/assets/%2e%2e/backend/api.py", "/%252e%252e/index.html",
                     "/assets/%5c../backend/api.py", "/app.js:secret", "/assets/%00file.txt",
                     "http://elsewhere.test/app.js", "/assets/%xx.js"):
            with self.subTest(path=path):
                status, _, _ = self.request(frontend, path)
                self.assertEqual(status, 400)

    def test_no_backend_returns_explicit_503_without_business_payload(self):
        status, body, _ = self.request(self.frontend(), "/api/v1/retail/simulate", "POST", b"{}")
        self.assertEqual(status, 503)
        payload = json.loads(body)
        self.assertEqual(payload["error"]["code"], "API_NOT_CONFIGURED")
        self.assertNotIn("items", payload)
        self.assertNotIn("status", payload)

    def test_proxy_preserves_write_body_path_and_tenant_and_idempotency_headers(self):
        upstream = self.upstream(payload=b' { "status" : "fixture" }\n')
        frontend = self.frontend(upstream)
        body = b' { "request_id" : "fixture", "raw": "\\u4e2d" }\n'
        for suffix in ("/retail/simulate", "/workbenches/transfer/save", "/proposals/proposal-001/execute"):
            status, payload, _ = self.request(frontend, "/api/v1" + suffix, "POST", body,
                                               {"Content-Type": "application/json", "X-Request-ID": "fixture-request",
                                                "X-Tenant-Id": "tenant-example", "Idempotency-Key": "action-key"})
            self.assertEqual(status, 200)
            self.assertEqual(payload, upstream.payload)
            path, received, headers = upstream.requests[-1]
            self.assertEqual(path, "/gateway/api/v1" + suffix)
            self.assertEqual(received, body)
            self.assertEqual(headers["X-Request-ID"], "fixture-request")
            self.assertEqual(headers["X-Tenant-Id"], "tenant-example")
            self.assertEqual(headers["Idempotency-Key"], "action-key")
        self.assertEqual(upstream.methods, ["POST"] * 3)

    def test_read_routes_preserve_query_and_tenant_without_mutating_requests(self):
        upstream = self.upstream()
        frontend = self.frontend(upstream)
        for suffix in ("/retail/overview?period=7&store_id=STORE-001", "/retail/simulation-options", "/risks/1",
                       "/risks", "/workbenches/transfer?risk_id=1", "/proposals", "/proposals/p-1/versions",
                       "/execution-tasks", "/data-center", "/work-items", "/cases",
                       "/hackathon/context?scenario_id=S01&branch_id=transfer_80", "/hackathon/proposals",
                       "/hackathon/overview", "/hackathon/tasks", "/hackathon/tasks/task-1",
                       "/hackathon/accounting", "/hackathon/agent-runs/run-1",
                       "/hackathon/materials/drafts/draft-1", "/hackathon/materials/material-1",
                       "/hackathon/materials/material-1/image", "/hackathon/cases/task-1"):
            status, _, _ = self.request(frontend, "/api/v1" + suffix, headers={"X-Tenant-Id": "isolated"})
            self.assertEqual(status, 200)
            path, body, headers = upstream.requests[-1]
            self.assertEqual(path, "/gateway/api/v1" + suffix)
            self.assertEqual(body, b"")
            self.assertEqual(headers["X-Tenant-Id"], "isolated")
        self.assertEqual(upstream.methods, ["GET"] * 22)

    def test_hackathon_write_routes_and_multipart_payload_are_forwarded(self):
        upstream = self.upstream(payload=b'{"contract_version":"hackathon.v1"}')
        frontend = self.frontend(upstream)
        paths = (
            "/hackathon/facts/query", "/hackathon/risks/assess", "/hackathon/proposals/compare",
            "/hackathon/proposals", "/hackathon/proposals/p-1/confirm", "/hackathon/tasks/t-1/channel-actions",
            "/hackathon/tasks/t-1/events", "/hackathon/replays/advance", "/hackathon/agent-runs",
            "/hackathon/materials/extract", "/hackathon/materials/d-1/confirm",
        )
        for suffix in paths:
            body = b"--test-boundary\r\nContent-Disposition: form-data; name=\"context\"\r\n\r\n{}\r\n--test-boundary--\r\n" if suffix.endswith("/materials/extract") else b"{}"
            content_type = "multipart/form-data; boundary=test-boundary" if suffix.endswith("/materials/extract") else "application/json"
            status, payload, _ = self.request(frontend, "/api/v1" + suffix, "POST", body,
                {"Content-Type": content_type, "X-Tenant-Id": "hackathon-demo", "Idempotency-Key": "action-1"})
            self.assertEqual(status, 200)
            self.assertEqual(payload, upstream.payload)
            path, received, headers = upstream.requests[-1]
            self.assertEqual(path, "/gateway/api/v1" + suffix)
            self.assertEqual(received, body)
            self.assertEqual(headers["X-Tenant-Id"], "hackathon-demo")
            self.assertEqual(headers["Idempotency-Key"], "action-1")
        self.assertEqual(upstream.methods, ["POST"] * len(paths))

    def test_upstream_errors_and_redirects_are_preserved_without_retry(self):
        upstream = self.upstream()
        frontend = self.frontend(upstream)
        for code in (302, 422, 429, 503, 504):
            upstream.status = code
            upstream.payload = f'{{"fixture_status":{code}}}'.encode()
            status, body, headers = self.request(frontend, "/api/v1/retail/simulate", "POST", b"{}")
            self.assertEqual((status, body), (code, upstream.payload))
            self.assertEqual(headers["Retry-After"], "5")
        self.assertEqual(len(upstream.requests), 5)

    def test_only_explicit_v12_routes_and_methods_are_forwarded(self):
        upstream = self.upstream()
        frontend = self.frontend(upstream)
        for path in ("/api/v1/demo/reset", "/api/v1/data-center/imports", "/api/v1/agent-runs",
                     "/api/v1/agent-runs/run-001/decisions", "/api/v1/retail/simulate/extra",
                     "/api/v1/workbenches/unknown/save", "/app.js"):
            self.assertEqual(self.request(frontend, path, "POST", b"{}")[0], 404)
        for path in ("/api/v1/health", "/api/v1/dashboard", "/api/v1/retail/simulate", "/api/v1/anything"):
            self.assertEqual(self.request(frontend, path)[0], 404)
        for method in ("PUT", "PATCH", "DELETE"):
            self.assertEqual(self.request(frontend, "/api/v1/retail/simulate", method, b"{}")[0], 501)
        self.assertEqual(self.request(frontend, "/api/v1/retail/overview", "HEAD")[0], 405)
        self.assertEqual(upstream.requests, [])

    def test_rejected_writes_consume_segmented_body_before_responding(self):
        upstream = self.upstream()
        cases = [("POST", "/api/v1/agent-runs/run-001/decisions", 404),
                 ("POST", "/assets/%2e%2e/backend/api.py", 400),
                 *[(method, "/api/v1/retail/simulate", 501) for method in ("PUT", "PATCH", "DELETE")]]
        for method, path, expected in cases:
            with self.subTest(method=method, path=path):
                frontend = self.frontend(upstream)
                handler = frontend.RequestHandlerClass
                events = Queue()
                original_setup, original_response = handler.setup, handler.send_response

                class ObservedReader:
                    def __init__(self, stream):
                        self.stream = stream

                    def read(self, length):
                        events.put(("body-read", length))
                        return self.stream.read(length)

                    def __getattr__(self, name):
                        return getattr(self.stream, name)

                def setup(instance):
                    original_setup(instance)
                    instance.rfile = ObservedReader(instance.rfile)

                def send_response(instance, code, message=None):
                    events.put(("response", code))
                    original_response(instance, code, message)

                handler.setup, handler.send_response = setup, send_response
                body = b'{"split":"body"}'
                connection = http.client.HTTPConnection("127.0.0.1", frontend.server_port, timeout=2)
                try:
                    connection.putrequest(method, path)
                    connection.putheader("Content-Length", str(len(body)))
                    # The body read, observed without replacing its socket, is
                    # the handshake for sending the rest. No sleeps or retries.
                    connection.endheaders(body[:1])
                    self.assertEqual(events.get(timeout=2), ("body-read", len(body)))
                    connection.send(body[1:])
                    response = connection.getresponse()
                    self.assertEqual(response.status, expected)
                    self.assertTrue(response.read())
                    self.assertEqual(events.get(timeout=2), ("response", expected))
                finally:
                    connection.close()
        self.assertEqual(upstream.requests, [])

    def test_request_limit_is_enforced_before_forwarding(self):
        upstream = self.upstream()
        frontend = self.frontend(upstream)
        status, body, _ = self.request(frontend, "/api/v1/retail/simulate", "POST", b"{}",
                                       {"Content-Length": str(MAX_BODY_BYTES + 1)})
        self.assertEqual(status, 413)
        self.assertEqual(json.loads(body)["error"]["code"], "BODY_TOO_LARGE")
        self.assertEqual(upstream.requests, [])

    def test_write_framing_limits_apply_before_route_or_method_rejection(self):
        upstream = self.upstream()
        frontend = self.frontend(upstream)
        cases = [([], 411), ([("Content-Length", "-1")], 400),
                 ([("Content-Length", "2"), ("Content-Length", "2")], 400),
                 ([("Content-Length", "2, 2")], 400),
                 ([("Transfer-Encoding", "chunked"), ("Content-Length", "0")], 400),
                 ([("Transfer-Encoding", "")], 400),
                 ([("Content-Length", str(MAX_BODY_BYTES + 1))], 413)]
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            for headers, expected in cases:
                if method != "POST" and not headers:
                    expected = 501  # These unsupported methods need no body.
                with self.subTest(method=method, headers=headers):
                    connection = http.client.HTTPConnection("127.0.0.1", frontend.server_port, timeout=2)
                    try:
                        connection.putrequest(method, "/api/v1/agent-runs")
                        for key, value in headers:
                            connection.putheader(key, value)
                        connection.endheaders()
                        response = connection.getresponse()
                        self.assertEqual(response.status, expected)
                        self.assertIn("error", json.loads(response.read()))
                    finally:
                        connection.close()
        self.assertEqual(upstream.requests, [])

    def test_incomplete_bodies_are_rejected_before_forwarding_or_method_dispatch(self):
        upstream = self.upstream()
        frontend = self.frontend(upstream)
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            with self.subTest(method=method):
                connection = http.client.HTTPConnection("127.0.0.1", frontend.server_port, timeout=2)
                try:
                    connection.putrequest(method, "/api/v1/retail/simulate")
                    connection.putheader("Content-Length", "10")
                    connection.endheaders(b"{}")
                    connection.sock.shutdown(socket.SHUT_WR)
                    response = connection.getresponse()
                    self.assertEqual(response.status, 400)
                    self.assertEqual(json.loads(response.read())["error"]["message"], "Incomplete request body.")
                finally:
                    connection.close()
        self.assertEqual(upstream.requests, [])

    def test_body_timeout_remains_bounded_on_rejected_writes(self):
        upstream = self.upstream()
        frontend = self.frontend(upstream, timeout=.05)
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            with self.subTest(method=method):
                connection = http.client.HTTPConnection("127.0.0.1", frontend.server_port, timeout=2)
                try:
                    connection.putrequest(method, "/api/v1/agent-runs")
                    connection.putheader("Content-Length", "2")
                    connection.endheaders()
                    response = connection.getresponse()
                    self.assertEqual(response.status, 408)
                    self.assertEqual(json.loads(response.read())["error"]["code"], "REQUEST_TIMEOUT")
                finally:
                    connection.close()
        self.assertEqual(upstream.requests, [])

    def test_valid_zero_and_maximum_length_bodies_are_preserved(self):
        upstream = self.upstream()
        frontend = self.frontend(upstream)
        for body in (b"", b"x" * MAX_BODY_BYTES):
            with self.subTest(length=len(body)):
                status, _, _ = self.request(frontend, "/api/v1/retail/simulate", "POST", body)
                self.assertEqual(status, 200)
                self.assertEqual(upstream.requests[-1][1], body)
        self.assertEqual(len(upstream.requests), 2)

    def test_invalid_request_framing_is_rejected(self):
        frontend = self.frontend()
        for headers, expected in (({}, 411), ({"Content-Length": "-1"}, 400),
                                  ({"Content-Length": "9" * 5000}, 413),
                                  ({"Transfer-Encoding": "chunked"}, 400)):
            connection = http.client.HTTPConnection("127.0.0.1", frontend.server_port, timeout=2)
            try:
                connection.putrequest("POST", "/api/v1/retail/simulate")
                for key, value in headers.items():
                    connection.putheader(key, value)
                connection.endheaders()
                response = connection.getresponse()
                self.assertEqual(response.status, expected)
                response.read()
            finally:
                connection.close()

    def test_network_failure_is_502(self):
        upstream = self.upstream(status=None)
        frontend = self.frontend(upstream)
        status, body, _ = self.request(frontend, "/api/v1/retail/simulate", "POST", b"{}")
        self.assertEqual(status, 502)
        self.assertEqual(json.loads(body)["error"]["code"], "UPSTREAM_UNAVAILABLE")
        self.assertEqual(len(upstream.requests), 1)

    def test_upstream_timeout_is_504_without_retry(self):
        upstream = self.upstream(delay=.2)
        frontend = self.frontend(upstream, timeout=.03)
        status, body, _ = self.request(frontend, "/api/v1/retail/simulate", "POST", b"{}")
        self.assertEqual(status, 504)
        self.assertEqual(json.loads(body)["error"]["code"], "UPSTREAM_TIMEOUT")
        self.assertEqual(len(upstream.requests), 1)

    def test_api_configuration_rejects_credentials_and_non_http_targets(self):
        for value in ("file:///tmp/api/v1", "/api/v1", "http://localhost:1234", "http://user:password@localhost/api/v1",
                      "http://localhost/api/v1?token=x", "http://localhost/api/v1#fragment",
                      "http://localhost/../api/v1", "http://localhost:0/api/v1"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_api_base(value)
        self.assertEqual(validate_api_base("https://example.test/gateway/api/v1/"), "https://example.test/gateway/api/v1")


if __name__ == "__main__":
    unittest.main()
