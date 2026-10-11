"""One-shot synthetic DeepSeek trial with a conservative local budget ledger.

No keys, requests, source text, or responses are stored. Reservations are never
refunded, including failures and interrupted calls. This ledger limits this
application's trials; it cannot limit the provider account's global bill.
"""
import hashlib
import json
import socket
import sqlite3
import ssl
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from . import providers
from .analysis import SHANGHAI

MAGIC = "qq-radar.deepseek-budget.v1"
PRICE_DATE = "2026-10-11"
RESERVATION_MICROS = 1000000
MAX_REQUEST_BYTES = 100000
MAX_RESPONSE_BYTES = 100000
SCHEMA = """
CREATE TABLE ledger_metadata (magic TEXT PRIMARY KEY);
CREATE TABLE api_calls (
 id TEXT PRIMARY KEY, month TEXT NOT NULL, request_hash TEXT NOT NULL,
 reserved_micros INTEGER NOT NULL CHECK(reserved_micros=1000000),
 status TEXT NOT NULL CHECK(status IN ('reserved','succeeded','failed')),
 error_code TEXT, created_at INTEGER NOT NULL, usage_json TEXT,
 UNIQUE(month,request_hash));
PRAGMA user_version=1;
"""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Do not replay the POST or forward its Authorization to a redirect."""

    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def _calendar(as_of):
    value = int(time.time() * 1000) if as_of is None else as_of
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError("INVALID_API_AS_OF")
    try:
        now = (datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(milliseconds=value)).astimezone(SHANGHAI)
    except (OverflowError, ValueError):
        raise ValueError("INVALID_API_AS_OF") from None
    return value, now


def _clock(as_of):
    value, now = _calendar(as_of)
    if now.date().isoformat() != PRICE_DATE:
        raise ValueError("PRICE_RECHECK_REQUIRED")
    return value, f"{now.year:04d}-{now.month:02d}"


def budget_status(ledger_path, *, monthly_budget_cny=20, as_of=None):
    """Read this application's monthly reservations without sending or writing.

    A missing ledger represents zero local reservations. Reading does not
    require a current price quotation, since it cannot authorize a new call.
    """
    if not isinstance(monthly_budget_cny, int) or isinstance(monthly_budget_cny, bool) or not 1 <= monthly_budget_cny <= 20:
        raise ValueError("INVALID_MONTHLY_BUDGET")
    _, now = _calendar(as_of)
    month = f"{now.year:04d}-{now.month:02d}"
    counts = {"reserved": 0, "succeeded": 0, "failed": 0}
    report = {"month": month, "monthly_limit_cny": monthly_budget_cny, "monthly_reserved_cny": 0,
              "remaining_cny": monthly_budget_cny, "counts": counts}
    database = None
    try:
        path = Path(ledger_path).resolve()
        if not path.exists():
            return report
        database = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)
        # Keep the gate and aggregate in one read snapshot; no writes or schema
        # initialization are performed by this read-only connection.
        database.execute("BEGIN")
        _ledger_gate(database)
        total = 0
        for status, count, reserved in database.execute("SELECT status,COUNT(*),SUM(reserved_micros) FROM api_calls "
                                                        "WHERE month=? GROUP BY status", (month,)):
            counts[status] = count
            total += reserved
        report["monthly_reserved_cny"] = total // RESERVATION_MICROS
        report["remaining_cny"] = max(0, monthly_budget_cny - report["monthly_reserved_cny"])
        return report
    except (ValueError, TypeError, OSError, sqlite3.Error, RuntimeError) as exc:
        if isinstance(exc, ValueError) and str(exc) == "UNRECOGNIZED_BUDGET_DATABASE":
            raise ValueError("UNRECOGNIZED_BUDGET_DATABASE") from None
        raise ValueError("BUDGET_DATABASE_ERROR") from None
    finally:
        if database is not None:
            database.close()


def _ledger_gate(database):
    tables = {row[0] for row in database.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if tables != {"ledger_metadata", "api_calls"} or database.execute("PRAGMA user_version").fetchone()[0] != 1:
        raise ValueError("UNRECOGNIZED_BUDGET_DATABASE")
    if [row[0] for row in database.execute("SELECT magic FROM ledger_metadata")] != [MAGIC]:
        raise ValueError("UNRECOGNIZED_BUDGET_DATABASE")
    columns = {row[1] for row in database.execute("PRAGMA table_info(api_calls)")}
    if columns != {"id", "month", "request_hash", "reserved_micros", "status", "error_code", "created_at", "usage_json"}:
        raise ValueError("UNRECOGNIZED_BUDGET_DATABASE")
    # A marker alone must not make an empty unrelated schema trusted.
    unique = []
    for index in database.execute("PRAGMA index_list(api_calls)").fetchall():
        if index[2]:
            # Parameter binding is supported by the table-valued PRAGMA.
            unique.append(tuple(row[0] for row in database.execute("SELECT name FROM pragma_index_info(?) ORDER BY seqno", (index[1],))))
    if ("month", "request_hash") not in unique or ("id",) not in unique:
        raise ValueError("UNRECOGNIZED_BUDGET_DATABASE")
    if database.execute("SELECT 1 FROM api_calls WHERE reserved_micros IS NULL OR reserved_micros<>? "
                        "OR status IS NULL OR status NOT IN ('reserved','succeeded','failed') LIMIT 1", (RESERVATION_MICROS,)).fetchone():
        raise ValueError("UNRECOGNIZED_BUDGET_DATABASE")


def _connect(path):
    database = None
    try:
        path = Path(path).resolve()
        existed = path.exists()
        path.parent.mkdir(parents=True, exist_ok=True)
        database = sqlite3.connect(path, timeout=5)
        tables = {row[0] for row in database.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        version = database.execute("PRAGMA user_version").fetchone()[0]
        if not tables and version == 0 and not existed:
            # A second initializer waits here and then sees the first schema.
            database.execute("BEGIN IMMEDIATE")
            try:
                tables = {row[0] for row in database.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                version = database.execute("PRAGMA user_version").fetchone()[0]
                if not tables and version == 0:
                    # executescript commits an existing transaction; execute
                    # each statement instead to retain the initialization lock.
                    for statement in SCHEMA.split(";"):
                        if statement.strip():
                            database.execute(statement)
                    database.execute("INSERT INTO ledger_metadata VALUES (?)", (MAGIC,))
                _ledger_gate(database)
                database.commit()
            except BaseException:
                database.rollback()
                raise
        else:
            _ledger_gate(database)
        return database
    except (ValueError, TypeError, OSError, sqlite3.Error, RuntimeError) as exc:
        if database is not None:
            database.close()
        if isinstance(exc, ValueError) and str(exc) == "UNRECOGNIZED_BUDGET_DATABASE":
            raise ValueError("UNRECOGNIZED_BUDGET_DATABASE") from None
        raise ValueError("BUDGET_DATABASE_ERROR") from None
    except BaseException:
        if database is not None:
            database.close()
        raise


def _reserve(database, month, request_hash, clock, monthly_budget_cny):
    try:
        database.execute("BEGIN IMMEDIATE")
        if database.execute("SELECT 1 FROM api_calls WHERE month=? AND request_hash=?", (month, request_hash)).fetchone():
            raise ValueError("DUPLICATE_API_REQUEST")
        total = database.execute("SELECT COALESCE(SUM(reserved_micros),0) FROM api_calls WHERE month=?", (month,)).fetchone()[0]
        if total + RESERVATION_MICROS > monthly_budget_cny * RESERVATION_MICROS:
            raise ValueError("MONTHLY_BUDGET_EXCEEDED")
        identity = str(uuid4())
        database.execute("INSERT INTO api_calls(id,month,request_hash,reserved_micros,status,created_at) "
                         "VALUES (?,?,?,?,'reserved',?)", (identity, month, request_hash, RESERVATION_MICROS, clock))
        database.commit()
        return identity, (total + RESERVATION_MICROS) // RESERVATION_MICROS
    except BaseException:
        database.rollback()
        raise


def _finish(database, identity, status, error=None, usage=None):
    # usage has already been normalized by providers.validate_response.
    with database:
        database.execute("UPDATE api_calls SET status=?,error_code=?,usage_json=? WHERE id=? AND status='reserved'",
                         (status, error, json.dumps(usage, sort_keys=True, separators=(",", ":")) if usage is not None else None, identity))


def _send(request_preview, api_key, body, timeout_seconds):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                        urllib.request.HTTPSHandler(context=ssl.create_default_context()), NoRedirect())
    request = urllib.request.Request(providers.ENDPOINT, data=body, method="POST",
                                     headers={"Content-Type": "application/json", "Authorization": "Bearer " + api_key})
    try:
        with opener.open(request, timeout=timeout_seconds) as response:
            if response.getcode() != 200:
                raise ValueError("DEEPSEEK_HTTP_ERROR")
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        exc.close()
        raise ValueError("DEEPSEEK_HTTP_ERROR") from None
    except (urllib.error.URLError, OSError, socket.timeout, ssl.SSLError):
        raise ValueError("DEEPSEEK_NETWORK_ERROR") from None
    if not isinstance(raw, bytes) or len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError("DEEPSEEK_RESPONSE_INVALID")
    try:
        response = providers._loads(raw.decode("utf-8", errors="strict"), "DEEPSEEK_RESPONSE_INVALID")
        return providers.validate_response(response, request_preview)
    except (ValueError, UnicodeError):
        raise ValueError("DEEPSEEK_RESPONSE_INVALID") from None


def call(request_preview, api_key, ledger_path, *, monthly_budget_cny=20, timeout_seconds=30, as_of=None):
    """Send one synthetic Flash trial after a durable, nonrefundable CNY 1 reserve.

    ``as_of`` is for tests, not a CLI price-date override. No retries or actual
    usage refunds occur. Failed requests with the same hash cannot be resent in
    the same Beijing month through this ledger.
    """
    # Freeze the preview before deriving both request bytes and response
    # citations, so caller mutations cannot change the reserved request.
    request_preview = providers._loads(providers._json(request_preview, "INVALID_PROVIDER_REQUEST_PREVIEW"),
                                      "INVALID_PROVIDER_REQUEST_PREVIEW")
    providers._preview(request_preview)
    if request_preview["request"]["model"] != "deepseek-flash":
        raise ValueError("TRIAL_FLASH_ONLY")
    if (not isinstance(api_key, str) or not 1 <= len(api_key) <= 4096
            or any(not 33 <= ord(char) <= 126 for char in api_key)):
        raise ValueError("INVALID_API_KEY")
    if not isinstance(monthly_budget_cny, int) or isinstance(monthly_budget_cny, bool) or not 1 <= monthly_budget_cny <= 20:
        raise ValueError("INVALID_MONTHLY_BUDGET")
    if not isinstance(timeout_seconds, int) or isinstance(timeout_seconds, bool) or not 1 <= timeout_seconds <= 60:
        raise ValueError("INVALID_API_TIMEOUT")
    clock, month = _clock(as_of)
    try:
        body = providers._json(request_preview["request"], "INVALID_PROVIDER_REQUEST_PREVIEW").encode("utf-8", errors="strict")
    except UnicodeError:
        raise ValueError("INVALID_PROVIDER_REQUEST_PREVIEW") from None
    if len(body) > MAX_REQUEST_BYTES:
        raise ValueError("API_REQUEST_TOO_LARGE")
    request_hash = hashlib.sha256(body).hexdigest()
    database = _connect(ledger_path)
    identity = None
    try:
        identity, monthly_reserved = _reserve(database, month, request_hash, clock, monthly_budget_cny)
        try:
            result = _send(request_preview, api_key, body, timeout_seconds)
        except ValueError as exc:
            code = str(exc) if str(exc) in {"DEEPSEEK_HTTP_ERROR", "DEEPSEEK_NETWORK_ERROR", "DEEPSEEK_RESPONSE_INVALID"} else "DEEPSEEK_REQUEST_FAILED"
            _finish(database, identity, "failed", code)
            raise ValueError(code) from None
        except Exception:
            _finish(database, identity, "failed", "DEEPSEEK_REQUEST_FAILED")
            raise ValueError("DEEPSEEK_REQUEST_FAILED") from None
        _finish(database, identity, "succeeded", usage=result["usage"])
        return {**result, "mode": "synthetic-api", "sent": True, "allowed_to_send": False,
                "budget": {"month": month, "reserved_cny": 1, "monthly_reserved_cny": monthly_reserved,
                           "monthly_limit_cny": monthly_budget_cny}}
    except (sqlite3.Error, OSError):
        # A committed reservation remains charged even if outcome recording
        # fails. It may remain 'reserved', deliberately blocking a repeat.
        raise ValueError("BUDGET_DATABASE_ERROR") from None
    finally:
        database.close()
