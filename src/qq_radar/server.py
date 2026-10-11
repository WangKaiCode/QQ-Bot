"""Read-only loopback viewer for synthetic databases. Not a deployment server."""
import json
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit
from uuid import uuid4

from .domain import timestamp_ms
from .storage import connect, context, detail, report, search

ASSETS = Path(__file__).parent / "web"
STATIC = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"),
          "/style.css": ("style.css", "text/css")}


def create_server(db_path, port=8765):
    db_path = Path(db_path).resolve()
    with_db = connect(db_path, readonly=True)
    try:
        if with_db.execute("SELECT 1 FROM messages WHERE namespace != 'synthetic.v1' LIMIT 1").fetchone():
            raise ValueError("SYNTHETIC_ONLY")
    finally:
        with_db.close()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass  # Do not put search terms or source IDs into terminal logs.

        def send_body(self, status, value, content_type="application/json"):
            body = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type + "; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'none'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            self.end_headers()
            self.wfile.write(body)

        def error(self, status, code):
            self.send_body(status, {"code": code, "request_id": str(uuid4())})

        def do_POST(self):
            self.error(405, "READ_ONLY")

        def do_GET(self):
            origins = {f"http://127.0.0.1:{self.server.server_port}", f"http://localhost:{self.server.server_port}"}
            if "http://" + self.headers.get("Host", "") not in origins:
                self.error(403, "INVALID_HOST")
                return
            if self.headers.get("Origin") not in (None, *origins) or self.headers.get("Sec-Fetch-Site") == "cross-site":
                self.error(403, "INVALID_ORIGIN")
                return
            parsed = urlsplit(self.path)
            if parsed.path in STATIC:
                filename, mime = STATIC[parsed.path]
                self.send_body(200, (ASSETS / filename).read_bytes(), mime)
                return
            db = None
            try:
                params = parse_qs(parsed.query, keep_blank_values=True, max_num_fields=20)
                def param(name, default=None):
                    values = params.get(name, [default])
                    if len(values) != 1:
                        raise ValueError("DUPLICATE_PARAMETER")
                    return values[0]
                def configured_topic():
                    from .analysis import load_rules, validate_keywords
                    selected = next((dict(item) for item in load_rules()["topics"] if item["id"] == param("topic", "ai")), None)
                    if selected is None:
                        raise ValueError("UNKNOWN_TOPIC")
                    if "keywords" in params:
                        selected["keywords"] = validate_keywords(param("keywords").split(","))
                    return selected
                db = connect(db_path, readonly=True)
                route = parsed.path
                if route == "/api/v1/health":
                    result = {"mode": "synthetic", "readonly": True, "retention_active": False}
                elif route == "/api/v1/topics":
                    from .analysis import load_rules
                    result = load_rules()["topics"]
                elif route == "/api/v1/analysis/preview":
                    from .analysis import preview
                    topic = configured_topic()
                    since, until = param("since"), param("until")
                    result = preview(db, param("account"), param("group"), topic, param("kind", "hourly"),
                                     timestamp_ms(since) if since else None, timestamp_ms(until) if until else None)
                elif route == "/api/v1/outbound/preview":
                    from .outbound import prepare
                    since, until = param("since"), param("until")
                    result = prepare(db, param("account"), param("group"), configured_topic(),
                                     timestamp_ms(since) if since else None, timestamp_ms(until) if until else None)
                elif route == "/api/v1/retention/preview":
                    from .retention import preview
                    as_of = param("as_of")
                    result = preview(db, param("account"), param("group"), timestamp_ms(as_of) if as_of else None,
                                     int(param("limit", "20")), int(param("offset", "0")))
                elif route == "/api/v1/conversations":
                    result = [dict(row) for row in db.execute(
                        "SELECT account_id, group_id, count(*) AS message_count FROM messages GROUP BY account_id,group_id ORDER BY account_id,group_id")]
                elif route == "/api/v1/messages":
                    account, group = param("account"), param("group")
                    if not account or not group:
                        raise ValueError("MISSING_SCOPE")
                    limit, offset = int(param("limit", "20")), int(param("offset", "0"))
                    if not 1 <= limit <= 100:
                        raise ValueError("INVALID_LIMIT")
                    since, until = param("since"), param("until")
                    rows = search(db, account, group, param("keyword", ""), timestamp_ms(since) if since else None,
                                  timestamp_ms(until) if until else None, limit + 1, offset)
                    result = {"items": rows[:limit], "next_offset": offset + limit if len(rows) > limit else None}
                elif route.startswith("/api/v1/messages/"):
                    parts = route.split("/")
                    mid = unquote(parts[4])
                    if len(parts) == 5:
                        result = detail(db, mid)
                    elif len(parts) == 6 and parts[5] == "context":
                        result = context(db, mid, int(param("radius", "2")))
                    else:
                        raise KeyError("NOT_FOUND")
                elif route == "/api/v1/imports":
                    result = [dict(row) for row in db.execute("SELECT * FROM import_batches ORDER BY started_at DESC,id LIMIT 50")]
                elif route.startswith("/api/v1/imports/") and len(route.split("/")) == 5:
                    result = report(db, unquote(route.split("/")[4]))
                else:
                    raise KeyError("NOT_FOUND")
                self.send_body(200, result)
            except KeyError:
                self.error(404, "NOT_FOUND")
            except ValueError:
                self.error(400, "INVALID_QUERY")
            except (sqlite3.Error, OSError):
                self.error(503, "STORAGE_UNAVAILABLE")
            finally:
                if db is not None:
                    db.close()

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    return server


def serve(db_path, port):
    server = create_server(db_path, port)
    print(f"合成数据来源阅读：http://127.0.0.1:{server.server_port} （Ctrl+C 停止）", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
