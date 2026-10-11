"""Authenticated loopback-only, memory-only OneBot event receiver."""
import hmac
import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .onebot import Probe

REQUEST_TIMEOUT = 2


def create_server(config, port=0):
    if isinstance(port, bool) or not isinstance(port, int) or not 0 <= port <= 65535:
        raise ValueError("INVALID_PORT")
    probe = Probe(config)
    expected_token = config["token"].encode("utf-8")
    max_bytes = config.get("max_bytes", 1048576)

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            self.request.settimeout(REQUEST_TIMEOUT)
            super().setup()

        def log_message(self, *_):
            pass

        def respond(self, status, value):
            self.close_connection = True
            body = json.dumps(value, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            for name, value in (("Content-Type", "application/json; charset=utf-8"),
                                ("Content-Length", str(len(body))), ("Cache-Control", "no-store"),
                                ("X-Content-Type-Options", "nosniff"), ("Connection", "close"),
                                ("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'; base-uri 'none'")):
                self.send_header(name, value)
            self.end_headers()
            if self.command != "HEAD":
                try:
                    self.wfile.write(body)
                except (OSError, TimeoutError):
                    pass

        def failure(self, status, code):
            self.respond(status, {"code": code})

        def gate(self):
            hosts = {f"localhost:{self.server.server_port}", f"127.0.0.1:{self.server.server_port}"}
            host = self.headers.get_all("Host", [])
            if len(host) != 1 or host[0] not in hosts:
                self.failure(403, "INVALID_HOST")
                return False
            origins = self.headers.get_all("Origin", [])
            sites = self.headers.get_all("Sec-Fetch-Site", [])
            if len(origins) > 1 or (origins and origins[0] not in {"http://" + item for item in hosts}) or len(sites) > 1 or "cross-site" in sites:
                self.failure(403, "INVALID_ORIGIN")
                return False
            auth = self.headers.get_all("Authorization", [])
            supplied = b""
            if len(auth) == 1 and auth[0].startswith("Bearer ") and len(auth[0]) <= 263:
                try:
                    supplied = auth[0][7:].encode("utf-8")
                except UnicodeError:
                    pass
            if not hmac.compare_digest(supplied, expected_token):
                self.failure(401, "UNAUTHORIZED")
                return False
            return True

        def handle_method(self):
            if not self.gate():
                return
            if self.path not in ("/status", "/events"):
                self.failure(404, "NOT_FOUND")
                return
            if self.command == "GET" and self.path == "/status":
                self.respond(200, probe.snapshot())
                return
            if self.command != "POST" or self.path != "/events":
                self.failure(405, "METHOD_NOT_ALLOWED")
                return
            if self.headers.get_all("Transfer-Encoding", []):
                self.failure(400, "UNSUPPORTED_TRANSFER_ENCODING")
                return
            lengths = self.headers.get_all("Content-Length", [])
            if len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdigit() or len(lengths[0]) > 10:
                self.failure(400, "INVALID_CONTENT_LENGTH")
                return
            length = int(lengths[0])
            if length > max_bytes:
                self.failure(413, "REQUEST_LIMIT")
                return
            types = self.headers.get_all("Content-Type", [])
            if len(types) != 1 or types[0].split(";", 1)[0].strip().lower() != "application/json":
                self.failure(400, "INVALID_CONTENT_TYPE")
                return
            try:
                deadline = time.monotonic() + REQUEST_TIMEOUT
                parts, received = [], 0
                while received < length:
                    remaining_time = deadline - time.monotonic()
                    if remaining_time <= 0:
                        raise TimeoutError()
                    self.request.settimeout(remaining_time)
                    part = self.rfile.read1(min(65536, length - received))
                    if not part:
                        break
                    parts.append(part)
                    received += len(part)
                body = b"".join(parts)
            except (OSError, TimeoutError):
                self.failure(400, "BODY_READ_FAILED")
                return
            if len(body) != length:
                self.failure(400, "INCOMPLETE_BODY")
                return
            token = self.headers["Authorization"][7:]
            result = probe.receive(body, token)
            result.pop("local_id", None)
            reason = result.get("reason")
            status = 410 if result["status"] == "stopped" else 401 if reason == "UNAUTHORIZED" else 413 if reason in ("REQUEST_LIMIT", "SESSION_LIMIT") else 400 if result["status"] == "rejected" else 200
            self.respond(status, result)

        do_GET = do_POST = do_HEAD = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_TRACE = do_CONNECT = handle_method

        def send_error(self, code, message=None, explain=None):
            # Base parser failures must not echo request paths or arbitrary text.
            if code == 501 and getattr(self, "headers", None) is not None:
                if self.gate():
                    self.failure(405, "METHOD_NOT_ALLOWED")
            else:
                self.failure(400, "INVALID_HTTP_REQUEST")

    class Server(ThreadingHTTPServer):
        daemon_threads = True
        allow_reuse_address = False

        def __init__(self, *args, **kwargs):
            self._workers = threading.BoundedSemaphore(8)
            self._active_sockets = set()
            self._socket_lock = threading.Lock()
            super().__init__(*args, **kwargs)

        def process_request(self, request, client_address):
            if not self._workers.acquire(blocking=False):
                self.shutdown_request(request)
                return
            with self._socket_lock:
                self._active_sockets.add(request)
            try:
                super().process_request(request, client_address)
            except Exception:
                with self._socket_lock:
                    self._active_sockets.discard(request)
                self._workers.release()
                raise

        def process_request_thread(self, request, client_address):
            try:
                super().process_request_thread(request, client_address)
            finally:
                with self._socket_lock:
                    self._active_sockets.discard(request)
                self._workers.release()

        def handle_error(self, request, client_address):
            pass  # Never log request content, addresses or exceptions.

        def server_close(self):
            probe.close()
            with self._socket_lock:
                requests = list(self._active_sockets)
            for request in requests:
                try:
                    request.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
            super().server_close()

    try:
        server = Server(("127.0.0.1", port), Handler)
    except Exception:
        probe.close()
        raise
    server.probe = probe
    return server


def serve(config, port=8766):
    server = create_server(config, port)
    timer = threading.Timer(config.get("duration_seconds", 3600), server.shutdown)
    timer.daemon = True
    try:
        timer.start()
        print(f"OneBot local memory probe: http://127.0.0.1:{server.server_port}")
        server.serve_forever(poll_interval=0.1)
    except KeyboardInterrupt:
        pass
    finally:
        timer.cancel()
        server.server_close()
