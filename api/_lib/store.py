"""Supabase persistence.

PostgREST over httpx rather than the supabase-py SDK — this runs in a serverless
function where cold-start size matters and we need five tables, not an ORM.

Every call here is optional to the critical path. If Supabase is down the order
still gets written to monday; we lose the audit row and the dedupe check. That
ordering is deliberate: monday is what the business runs on.
"""

import hashlib
import json

import httpx

from . import config


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Store:
    def __init__(self, url=None, key=None, timeout=15):
        self.url = (url or config.SUPABASE_URL).rstrip("/")
        self.key = key or config.SUPABASE_SERVICE_KEY
        self.enabled = bool(self.url and self.key)
        self._client = httpx.Client(timeout=timeout) if self.enabled else None

    def _headers(self, prefer=None):
        headers = {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
        }
        if prefer:
            headers["Prefer"] = prefer
        return headers

    def _get(self, table, params):
        if not self.enabled:
            return []
        response = self._client.get(
            f"{self.url}/rest/v1/{table}", params=params, headers=self._headers()
        )
        response.raise_for_status()
        return response.json()

    def _post(self, table, rows, prefer="return=representation"):
        if not self.enabled:
            return []
        response = self._client.post(
            f"{self.url}/rest/v1/{table}",
            content=json.dumps(rows, default=str),
            headers=self._headers(prefer),
        )
        response.raise_for_status()
        return response.json() if response.content else []

    def key_kind(self):
        """Classify the configured key without revealing it.

        "Rejected" is ambiguous — it could be the wrong key or a bad one. The
        key's own prefix says which, and legacy JWTs carry their role in the
        payload, so this can name the mistake without printing a secret.
        """
        key = self.key or ""
        if not key:
            return "not set"
        if key.startswith("sb_secret_"):
            return "secret key (correct type)"
        if key.startswith("sb_publishable_"):
            return "PUBLISHABLE key — wrong one. Copy the Secret key instead."
        if key.startswith("eyJ"):
            import base64
            import json as _json
            try:
                payload = key.split(".")[1]
                payload += "=" * (-len(payload) % 4)
                role = _json.loads(base64.urlsafe_b64decode(payload)).get("role")
            except Exception:  # noqa: BLE001
                return "a JWT, but its contents could not be read"
            if role == "service_role":
                return "legacy service_role key (correct type)"
            return f"legacy {role or 'unknown'} key — wrong one. Use service_role or a Secret key."
        return (
            f"unrecognised format (starts {key[:3]!r}, {len(key)} chars). "
            "Expected a key beginning sb_secret_."
        )

    def ping(self):
        """Is the database actually reachable and are the tables there?

        Distinguishes three states the dashboard would otherwise collapse into
        one unhelpful "not connected": no credentials, credentials that don't
        work, and credentials that work against a database with no schema.
        """
        if not self.enabled:
            return {"ok": False, "state": "not_configured",
                    "detail": "SUPABASE_URL or SUPABASE_SERVICE_KEY is not set"}
        try:
            response = self._client.get(
                f"{self.url}/rest/v1/eorder_ingests",
                params={"select": "id", "limit": "1"},
                headers=self._headers(),
            )
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "state": "unreachable", "detail": f"{type(exc).__name__}: {exc}"}

        if response.status_code in (401, 403):
            return {"ok": False, "state": "rejected",
                    "key_looks_like": self.key_kind(),
                    "detail":
                    "Supabase rejected the key. It must be the SECRET key "
                    "(sb_secret_… or legacy service_role) — only that can read "
                    "these tables. If the type below is already correct, the "
                    "value is truncated or from a different project."}
        if response.status_code == 404:
            return {"ok": False, "state": "no_tables", "detail":
                    "Connected, but the eorder_ingests table does not exist. "
                    "Run supabase/migrations/0001_init.sql in the SQL Editor."}
        if response.status_code >= 400:
            return {"ok": False, "state": "error",
                    "detail": f"HTTP {response.status_code}: {response.text[:200]}"}
        return {"ok": True, "state": "ready", "key_looks_like": self.key_kind()}

    # -- idempotency -------------------------------------------------------

    def already_ingested(self, opportunity_id, file_sha):
        """True if this exact file has been read for this order before.

        Acceptance criterion 2: same file dropped twice must not duplicate.
        """
        if not self.enabled or not opportunity_id:
            return False
        rows = self._get(
            "eorder_ingests",
            {
                "opportunity_id": f"eq.{opportunity_id}",
                "file_sha256": f"eq.{file_sha}",
                "select": "id",
                "limit": "1",
            },
        )
        return bool(rows)

    def previous_parse(self, opportunity_id):
        """The most recent successful parse for this order, for change diffing."""
        if not self.enabled or not opportunity_id:
            return None
        rows = self._get(
            "eorder_ingests",
            {
                "opportunity_id": f"eq.{opportunity_id}",
                "status": "neq.failed",
                "select": "parsed",
                "order": "created_at.desc",
                "limit": "1",
            },
        )
        return rows[0]["parsed"] if rows else None

    def record_ingest(self, **fields):
        try:
            return self._post("eorder_ingests", [fields])
        except httpx.HTTPError:
            # Audit failure must never fail an order.
            return []

    def recent_ingests(self, limit=20):
        return self._get("eorder_ingests", {
            "select": "*", "order": "created_at.desc", "limit": str(limit),
        })

    def record_unknown_order_reason(self, order_reason, opportunity_id, file_name):
        """Brief §4.1 — an unrecognised order reason silently produces no ACV."""
        try:
            return self._post(
                "unknown_order_reasons",
                [{
                    "order_reason": order_reason,
                    "opportunity_id": opportunity_id,
                    "file_name": file_name,
                }],
                prefer="return=minimal",
            )
        except httpx.HTTPError:
            return []

    # -- installer accounts ------------------------------------------------

    def installer_accounts(self, active_only=True):
        params = {"select": "*"}
        if active_only:
            params["active"] = "is.true"
        return self._get("installer_accounts", params)

    def account_by_token(self, token):
        if not self.enabled or not token:
            return None
        rows = self._get(
            "installer_accounts",
            {"portal_token": f"eq.{token}", "active": "is.true", "select": "*", "limit": "1"},
        )
        return rows[0] if rows else None

    def upsert_accounts(self, rows):
        return self._post(
            "installer_accounts",
            rows,
            prefer="resolution=merge-duplicates,return=representation",
        )

    # -- portal ------------------------------------------------------------

    def record_event(self, monday_item_id, action, **fields):
        try:
            return self._post(
                "portal_events",
                [{"monday_item_id": monday_item_id, "action": action, **fields}],
                prefer="return=minimal",
            )
        except httpx.HTTPError:
            return []

    def cache_job(self, monday_item_id, data, **fields):
        try:
            return self._post(
                "jobs_cache",
                [{"monday_item_id": monday_item_id, "data": data, **fields}],
                prefer="resolution=merge-duplicates,return=minimal",
            )
        except httpx.HTTPError:
            return []

    def cached_jobs(self, installer_account_id):
        return self._get(
            "jobs_cache",
            {"installer_account_id": f"eq.{installer_account_id}", "select": "*"},
        )
