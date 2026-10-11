"""Synthetic loopback transport checks; no QQ, external network or data files."""
import contextlib
import http.client
import io
import json
from pathlib import Path
import socket
import sys
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from qq_radar import probe_server

TOKEN = "synthetic-token-32-characters-for-http"
CONFIG = {"account": "100001", "allowed_groups": ["200001"], "token": TOKEN}


def event(**changes):
    value = {"self_id": 100001, "post_type": "message", "message_type": "group", "group_id": 200001,
             "message_id": -42, "user_id": 300001, "time": 1791640800,
             "sender": {"nickname": "synthetic-private-nickname"},
             "message": [{"type": "text", "data": {"text": "synthetic-private-body"}}]}
    value.update(changes)
    return json.dumps(value).encode("utf-8")


class ProbeServerTests(unittest.TestCase):
    def setUp(self):
        self.server = probe_server.create_server({**CONFIG, "max_bytes": 1024})
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        self.thread.start()
        self.addCleanup(self.cleanup_server)

    def cleanup_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(self, method="GET", path="/status", data=None, headers=None, auth=True):
        default = {"Authorization": "Bearer " + TOKEN} if auth else {}
        if data is not None:
            default["Content-Type"] = "application/json"
        default.update(headers or {})
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        try:
            connection.request(method, path, body=data, headers=default)
            response = connection.getresponse()
            body = response.read()
            return response.status, dict(response.getheaders()), json.loads(body) if body else None
        finally:
            connection.close()

    def raw(self, lines, body=b""):
        with socket.create_connection(("127.0.0.1", self.server.server_port), timeout=3) as client:
            client.sendall(("\r\n".join(lines) + "\r\n\r\n").encode("ascii") + body)
            response = b""
            while True:
                chunk = client.recv(4096)
                if not chunk:
                    break
                response += chunk
        return int(response.split(b" ", 2)[1]), response

    def lines(self):
        return ["POST /events HTTP/1.1", f"Host: 127.0.0.1:{self.server.server_port}",
                "Authorization: Bearer " + TOKEN, "Content-Type: application/json"]

    def test_auth_required_constant_time_and_no_url_credentials(self):
        for path in ("/status", "/events", "/detail/private", "/status?token=" + TOKEN):
            status, _, result = self.request(path=path, auth=False)
            self.assertEqual(status, 401)
            self.assertEqual(result, {"code": "UNAUTHORIZED"})
        status, _, _ = self.request(headers={"Authorization": "Bearer wrong"})
        self.assertEqual(status, 401)
        with patch("qq_radar.probe_server.hmac.compare_digest", wraps=__import__("hmac").compare_digest) as compare:
            self.assertEqual(self.request()[0], 200)
            compare.assert_called_once()

    def test_strict_host_origin_cross_site_and_security_headers(self):
        for headers in ({"Host": "evil.test"}, {"Host": "localhost"}, {"Origin": "http://evil.test"},
                        {"Origin": f"http://localhost:{self.server.server_port + 1}"}, {"Sec-Fetch-Site": "cross-site"}):
            self.assertEqual(self.request(headers=headers)[0], 403)
        status, headers, result = self.request(headers={"Host": f"localhost:{self.server.server_port}",
                                                       "Origin": f"http://127.0.0.1:{self.server.server_port}"})
        self.assertEqual(status, 200)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertIn("default-src 'none'", headers["Content-Security-Policy"])
        self.assertNotIn("Access-Control-Allow-Origin", headers)

    def test_scope_dedup_conflict_and_response_never_echo(self):
        for data, expected in ((event(group_id=200002), "excluded"), (event(message_type="private"), "excluded"),
                               (event(), "accepted"), (event(), "matched"), (event(message="changed body"), "conflicts")):
            status, _, result = self.request("POST", "/events", data)
            self.assertEqual(status, 200)
            self.assertEqual(result["status"], expected)
            encoded = json.dumps(result)
            for private in ("local_id", "100001", "200001", "300001", "synthetic-private", "changed body"):
                self.assertNotIn(private, encoded)
        snapshot = self.request()[2]
        self.assertEqual(snapshot["counts"]["accepted"], 1)
        self.assertEqual(snapshot["counts"]["excluded"], 2)
        self.assertNotIn("synthetic-private", json.dumps(snapshot))

    def test_invalid_event_content_type_and_limits_static(self):
        self.assertEqual(self.request("POST", "/events", b"private invalid json")[0], 400)
        self.assertEqual(self.request("POST", "/events", event(), {"Content-Type": "text/plain"})[0], 400)
        status, _, value = self.request("POST", "/events", b"x" * 1025)
        self.assertEqual((status, value), (413, {"code": "REQUEST_LIMIT"}))
        self.assertEqual(self.request("POST", "/events", event(message_id=True))[0], 400)

    def test_reject_duplicate_invalid_missing_lengths_and_transfer_encoding(self):
        for extra in (["Content-Length: 2", "Content-Length: 2"], ["Content-Length: -1"],
                      ["Content-Length: +2"], ["Content-Length: 2, 2"], [],
                      ["Content-Length: 2", "Transfer-Encoding: chunked"]):
            with self.subTest(extra=extra):
                self.assertEqual(self.raw(self.lines() + extra, b"{}")[0], 400)
        for extra in (["Host: evil.test", "Content-Length: 2"], ["Origin: http://evil.test", "Origin: http://evil.test", "Content-Length: 2"]):
            self.assertEqual(self.raw(self.lines() + extra, b"{}")[0], 403)

    def test_short_socket_timeout_incomplete_body_not_retained(self):
        with patch.object(probe_server, "REQUEST_TIMEOUT", 0.05):
            status, response = self.raw(self.lines() + ["Content-Length: 100"], b"{")
        self.assertEqual(status, 400)
        self.assertNotIn(b"synthetic-private", response)
        self.assertEqual(self.server.probe.snapshot()["retained_messages"], 0)

    def test_continuous_small_chunks_cannot_extend_total_body_deadline(self):
        stop = threading.Event()
        with patch.object(probe_server, "REQUEST_TIMEOUT", 0.08), socket.create_connection(
                ("127.0.0.1", self.server.server_port), timeout=0.5) as client:
            request = ("\r\n".join(self.lines() + ["Content-Length: 100"]) + "\r\n\r\n").encode("ascii")
            client.sendall(request)
            def drip():
                while not stop.wait(0.015):
                    try:
                        client.sendall(b" ")
                    except OSError:
                        break
            sender = threading.Thread(target=drip, daemon=True)
            sender.start()
            try:
                response = client.recv(4096)
                self.assertIn(b" 400 ", response.split(b"\r\n", 1)[0])
            finally:
                stop.set()
                sender.join(timeout=0.5)
        self.assertEqual(self.server.probe.snapshot()["retained_messages"], 0)

    def test_eight_connections_bound_workers_then_recover_after_release(self):
        clients = []
        try:
            for _ in range(8):
                clients.append(socket.create_connection(("127.0.0.1", self.server.server_port), timeout=0.5))
            deadline = time.monotonic() + 0.5
            while time.monotonic() < deadline:
                with self.server._socket_lock:
                    active = len(self.server._active_sockets)
                if active == 8:
                    break
                threading.Event().wait(0.005)
            self.assertEqual(active, 8)
            with socket.create_connection(("127.0.0.1", self.server.server_port), timeout=0.5) as ninth:
                try:
                    rejected = ninth.recv(1) == b""
                except (ConnectionResetError, ConnectionAbortedError):
                    rejected = True
                self.assertTrue(rejected)
        finally:
            for client in clients:
                client.close()
        deadline = time.monotonic() + 0.5
        while time.monotonic() < deadline:
            with self.server._socket_lock:
                active = len(self.server._active_sockets)
            if active == 0:
                break
            threading.Event().wait(0.005)
        self.assertEqual(active, 0)
        self.assertEqual(self.request()[0], 200)

    def test_closed_probe_and_server_close_clear_content(self):
        self.request("POST", "/events", event())
        self.server.probe.close()
        self.assertEqual(self.request("POST", "/events", event())[0], 410)
        snapshot = self.request()[2]
        self.assertTrue(snapshot["closed"])
        self.assertEqual(snapshot["retained_bytes"], 0)
        self.server.shutdown()
        self.thread.join(timeout=2)
        self.server.server_close()
        self.assertTrue(self.server.probe.snapshot()["closed"])

    def test_unknown_paths_methods_and_no_detail_endpoint(self):
        self.assertEqual(self.request(path="/detail/private")[0], 404)
        self.assertEqual(self.request(path="/status?token=" + TOKEN)[0], 404)
        for method, path in (("POST", "/status"), ("GET", "/events"), ("PUT", "/events"),
                             ("OPTIONS", "/status"), ("BOGUS", "/events")):
            status, _, result = self.request(method, path)
            self.assertEqual((status, result), (405, {"code": "METHOD_NOT_ALLOWED"}))

    def test_serve_timer_shutdown_and_static_output_only(self):
        with patch.object(probe_server, "create_server") as create, patch.object(probe_server.threading, "Timer") as timer:
            create.return_value.server_port = 8766
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                probe_server.serve({**CONFIG, "duration_seconds": 20})
            self.assertEqual(timer.call_args.args, (20, create.return_value.shutdown))
            timer.return_value.start.assert_called_once()
            timer.return_value.cancel.assert_called_once()
            create.return_value.server_close.assert_called_once()
            self.assertNotIn(TOKEN, output.getvalue())
            self.assertNotIn("100001", output.getvalue())

    def test_failed_startup_output_still_closes_server(self):
        with patch.object(probe_server, "create_server") as create, patch.object(probe_server.threading, "Timer") as timer:
            with patch("builtins.print", side_effect=BrokenPipeError), self.assertRaises(BrokenPipeError):
                probe_server.serve(CONFIG)
            timer.return_value.cancel.assert_called_once()
            create.return_value.server_close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
