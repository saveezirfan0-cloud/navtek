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
    # Which candidate pair last worked, remembered across calls in a warm
    # function so the fallback costs one probe, not one per request.
    _working = None

    def __init__(self, url=None, key=None, timeout=15):
        if url or key:
            self.candidates = [{"name": "explicit",
                                "url": (url or "").rstrip("/"), "key": key or ""}]
        else:
            self.candidates = config.supabase_candidates()
            if Store._working is not None:
                # Put the known-good pair first.
                self.candidates.sort(key=lambda c: c["name"] != Store._working)

        first = self.candidates[0] if self.candidates else {"url": "", "key": "", "name": None}
        self.url, self.key, self.source = first["url"], first["key"], first["name"]
        self.enabled = bool(self.url and self.key)
        self._timeout = timeout
        self._client = httpx.Client(timeout=timeout) if self.enabled else None

    def _use(self, candidate):
        self.url, self.key, self.source = candidate["url"], candidate["key"], candidate["name"]
        self.enabled = bool(self.url and self.key)
        if self._client is None and self.enabled:
            self._client = httpx.Client(timeout=self._timeout)

    def _headers(self, prefer=None):
        """Auth headers, shaped to the key's generation.

        Legacy keys are JWTs and are sent both as `apikey` and as a Bearer
        token — the historical pattern. The new sb_secret_ keys are NOT JWTs:
        send one as `Authorization: Bearer` and Supabase tries to verify it as
        a JWT and rejects the whole request with 401, even though the `apikey`
        header alone is valid and grants full service access.

        That distinction is why a correct key, copied correctly from the
        correct project, was still "rejected" here. The key was never the
        problem; this header was.
        """
        headers = {"apikey": self.key, "Content-Type": "application/json"}
        if self.key.startswith("eyJ"):
            headers["Authorization"] = f"Bearer {self.key}"
        if prefer:
            headers["Prefer"] = prefer
        return headers

    # Set once if the database turns out to be unusable, so a broken key
    # produces one degraded run rather than an exception per call.
    degraded = None

    def _send(self, request):
        """Run a request; on an auth refusal, elect a working pair and retry.

        Only ping() used to try the other credential pairs, so /health could
        elect the working pair while a cold function instance served logins
        and lookups with the dead first pair — intermittent 401s that read as
        flaky passwords while the dashboard said the database was ready. Any
        401/403 now runs the same election once; `request` re-reads self.url
        and self._headers() when called, so the retry uses the elected pair.
        Costs nothing when only one pair is configured.
        """
        response = request()
        if response.status_code in (401, 403) and len(self.candidates) > 1:
            failed_pair = self.source
            if self.ping().get("ok") and self.source != failed_pair:
                response = request()
        return response

    def _get(self, table, params):
        """Read, and never raise.

        Reads used to raise on any error. Because the first thing an ingest
        does is a duplicate check, a bad Supabase key took down the whole
        order flow — monday never got written and the drop appeared to do
        nothing. The database is a ledger, not the point: losing it should
        cost the duplicate check and the history, never the order.

        Returning [] is the safe direction for every caller here. An unknown
        duplicate gets reprocessed (which rewrites the same values), an
        unknown previous parse skips the change diff, and no installer
        accounts means allocation is skipped rather than guessed.
        """
        if not self.enabled:
            return []
        try:
            response = self._send(lambda: self._client.get(
                f"{self.url}/rest/v1/{table}", params=params, headers=self._headers()
            ))
            if response.status_code >= 400:
                self.degraded = f"HTTP {response.status_code} reading {table}"
                return []
            return response.json()
        except Exception as exc:  # noqa: BLE001
            self.degraded = f"{type(exc).__name__} reading {table}"
            return []

    def _post(self, table, rows, prefer="return=representation"):
        """Write, and never raise. Same reasoning as _get."""
        if not self.enabled:
            return []
        try:
            response = self._send(lambda: self._client.post(
                f"{self.url}/rest/v1/{table}",
                content=json.dumps(rows, default=str),
                headers=self._headers(prefer),
            ))
            if response.status_code >= 400:
                self.degraded = f"HTTP {response.status_code} writing {table}"
                return []
            return response.json() if response.content else []
        except Exception as exc:  # noqa: BLE001
            self.degraded = f"{type(exc).__name__} writing {table}"
            return []

    def _patch(self, table, params, fields, prefer="return=representation"):
        """Update rows matching params. Never raises, like _get and _post."""
        if not self.enabled:
            return []
        try:
            response = self._send(lambda: self._client.patch(
                f"{self.url}/rest/v1/{table}",
                params=params,
                content=json.dumps(fields, default=str),
                headers=self._headers(prefer),
            ))
            if response.status_code >= 400:
                self.degraded = f"HTTP {response.status_code} updating {table}"
                return []
            return response.json() if response.content else []
        except Exception as exc:  # noqa: BLE001
            self.degraded = f"{type(exc).__name__} updating {table}"
            return []

    def _delete(self, table, params):
        if not self.enabled:
            return False
        try:
            response = self._send(lambda: self._client.delete(
                f"{self.url}/rest/v1/{table}", params=params, headers=self._headers()
            ))
            if response.status_code >= 400:
                self.degraded = f"HTTP {response.status_code} deleting from {table}"
                return False
            return True
        except Exception as exc:  # noqa: BLE001
            self.degraded = f"{type(exc).__name__} deleting from {table}"
            return False

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
            parts = key.split(".")
            if len(parts) != 3 or not parts[2]:
                return (
                    "a JWT with its signature missing — the paste lost the end "
                    "of the key. Copy the whole value again."
                )
            try:
                payload = parts[1] + "=" * (-len(parts[1]) % 4)
                role = _json.loads(base64.urlsafe_b64decode(payload)).get("role")
            except Exception:  # noqa: BLE001
                return "a JWT, but its contents could not be read"
            if role == "service_role":
                # A legacy key's HS256 signature is 43 base64url characters.
                # Shorter means the end of the key did not survive the paste —
                # the one corruption the payload check above cannot see,
                # because the readable half of the key is intact.
                if len(parts[2]) < 40:
                    return (
                        f"legacy service_role key, but its signature is cut "
                        f"short ({len(parts[2])} of 43 characters) — the paste "
                        f"lost the end of the key. Copy the whole value again."
                    )
                return "legacy service_role key (correct type)"
            return f"legacy {role or 'unknown'} key — wrong one. Use service_role or a Secret key."
        return (
            f"unrecognised format (starts {key[:3]!r}, {len(key)} chars). "
            "Expected a key beginning sb_secret_."
        )

    def project_mismatch(self):
        """Does the key belong to the project the URL points at?

        Legacy Supabase keys are JWTs whose payload carries the project ref,
        and the URL is https://<ref>.supabase.co — so a mismatched pair can be
        proven offline. This matters because a key from the wrong project is
        rejected in exactly the same way as a wrong or truncated key, and there
        is otherwise no way to tell them apart from the outside.
        """
        key, url = self.key or "", self.url or ""
        if not key.startswith("eyJ") or ".supabase.co" not in url:
            return None
        import base64
        import json as _json
        try:
            payload = key.split(".")[1]
            payload += "=" * (-len(payload) % 4)
            key_ref = _json.loads(base64.urlsafe_b64decode(payload)).get("ref")
        except Exception:  # noqa: BLE001
            return None
        url_ref = url.split("//", 1)[-1].split(".", 1)[0]
        if key_ref and url_ref and key_ref != url_ref:
            return (
                f"The key belongs to Supabase project '{key_ref}', but "
                f"SUPABASE_URL points at project '{url_ref}'. Take the URL and "
                f"the key from the same project."
            )
        if key_ref and key_ref == url_ref:
            return False   # proven to match
        return None

    def ping(self):
        """Try each candidate pair and keep the first that works.

        Returns the result for the working pair, or for the last one tried.

        Distinguishes three states the dashboard would otherwise collapse into
        one unhelpful "not connected": no credentials, credentials that don't
        work, and credentials that work against a database with no schema.
        """
        if not self.candidates:
            return {"ok": False, "state": "not_configured",
                    "detail": "SUPABASE_URL and SUPABASE_SERVICE_KEY are not set"}

        last = None
        for candidate in self.candidates:
            self._use(candidate)
            last = self._ping_once()
            last["tried"] = candidate["name"]
            if last["ok"]:
                Store._working = candidate["name"]
                return last
        if len(self.candidates) > 1:
            last["also_tried"] = [c["name"] for c in self.candidates]
        return last

    @staticmethod
    def _server_message(response):
        """Supabase's own explanation, out of a JSON error body or raw text."""
        try:
            body = response.json()
            if isinstance(body, dict):
                for field in ("message", "msg", "error_description", "error", "hint"):
                    if body.get(field):
                        return str(body[field])[:300]
        except Exception:  # noqa: BLE001
            pass
        text = (response.text or "").strip()
        return text[:300] or None

    def _ping_once(self):
        try:
            response = self._client.get(
                f"{self.url}/rest/v1/eorder_ingests",
                params={"select": "id", "limit": "1"},
                headers=self._headers(),
            )
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "state": "unreachable", "detail": f"{type(exc).__name__}: {exc}"}

        if response.status_code in (401, 403):
            # Supabase's own response body names the actual cause — "Invalid
            # API key", "Legacy API keys are disabled", a JWT error — which is
            # the difference between guessing and knowing. Discarding it here
            # is what made this failure cost days instead of minutes.
            server_said = self._server_message(response)
            lowered = (server_said or "").lower()
            # "Permission denied" is Postgres speaking, not the auth layer —
            # the key was ACCEPTED and then the service_role role was refused
            # table access because its grants are missing. Every key of every
            # generation fails identically until the grants are restored, which
            # is indistinguishable from a wrong key unless this is said.
            if "permission denied" in lowered:
                return {"ok": False, "state": "no_grants",
                        "key_looks_like": self.key_kind(),
                        "supabase_said": server_said,
                        "detail": (
                            "The key is fine — Supabase accepted it. The "
                            "database itself refused access: the service role "
                            "holds no grants on these tables, so every key "
                            "fails the same way. Run supabase/migrations/"
                            "0003_grants.sql in the Supabase SQL Editor; no "
                            "environment variable needs to change."
                        )}
            mismatch = self.project_mismatch()
            if mismatch:
                return {"ok": False, "state": "wrong_project",
                        "key_looks_like": self.key_kind(),
                        "supabase_said": server_said, "detail": mismatch}
            if "legacy" in lowered and ("disabled" in lowered or "expired" in lowered
                                        or "revoked" in lowered):
                detail = (
                    "This Supabase project has legacy API keys disabled, so a "
                    "service_role key is refused no matter how correctly it was "
                    "copied. Use the new Secret key instead: Supabase dashboard "
                    "→ Project Settings → API Keys → copy the sb_secret_… key "
                    "into SUPABASE_SECRET_KEY (SUPABASE_SERVICE_KEY also "
                    "works). Re-enabling legacy keys on that same page works "
                    "too."
                )
            else:
                detail = (
                    "Supabase rejected the key. It must be the SECRET key "
                    "(sb_secret_… or legacy service_role) — only that can read "
                    "these tables. If the type below is already correct and "
                    "from this project, the value is truncated, or the "
                    "project's legacy keys were disabled, rotated or revoked — "
                    "copy a fresh sb_secret_… key from Project Settings → API "
                    "Keys."
                )
            return {"ok": False, "state": "rejected",
                    "key_looks_like": self.key_kind(),
                    "project_match": "confirmed same project" if mismatch is False
                    else "could not be checked from the key",
                    "supabase_said": server_said,
                    "detail": detail}
        if response.status_code == 404:
            return {"ok": False, "state": "no_tables", "detail":
                    "Connected, but the eorder_ingests table does not exist. "
                    "Run supabase/migrations/0001_init.sql in the SQL Editor."}
        if response.status_code >= 400:
            return {"ok": False, "state": "error",
                    "detail": f"HTTP {response.status_code}: {response.text[:200]}"}
        return {"ok": True, "state": "ready", "key_looks_like": self.key_kind(),
                "using": self.source}

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

    def account_by_id(self, account_id):
        if not self.enabled or not account_id:
            return None
        rows = self._get(
            "installer_accounts",
            {"id": f"eq.{account_id}", "select": "*", "limit": "1"},
        )
        return rows[0] if rows else None

    def upsert_accounts(self, rows):
        return self._post(
            "installer_accounts",
            rows,
            prefer="resolution=merge-duplicates,return=representation",
        )

    def account_has_login(self, account_id):
        """Does any active installer login point at this account? Drives
        whether an SMS links to /portal or the magic link."""
        if not self.enabled or not account_id:
            return False
        rows = self._get(
            "app_users",
            {
                "installer_account_id": f"eq.{account_id}",
                "can_installer": "is.true",
                "active": "is.true",
                "select": "id",
                "limit": "1",
            },
        )
        return bool(rows)

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

    def delete_cached_job(self, monday_item_id):
        return self._delete(
            "jobs_cache", {"monday_item_id": f"eq.{monday_item_id}"}
        )

    def latest_event(self, monday_item_id, action):
        """The most recent portal event of one kind for an item, or None."""
        rows = self._get(
            "portal_events",
            {
                "monday_item_id": f"eq.{monday_item_id}",
                "action": f"eq.{action}",
                "select": "*",
                "order": "created_at.desc",
                "limit": "1",
            },
        )
        return rows[0] if rows else None

    # -- notifications -------------------------------------------------------
    #
    # The dedupe ledger behind every SMS and escalation: (item, kind) is
    # unique, so a webhook retry storm produces exactly one send. `kind`
    # carries the audience — "allocated:<account id>" — so a reallocated job
    # texts the NEW account once without re-texting the old one.

    def claim_notification(self, monday_item_id, kind, payload=None):
        """True if this (item, kind) was claimed NOW; False if it already was.

        A unique insert, not check-then-write: two concurrent webhook
        deliveries both pass a read check, only one wins an insert. Database
        down also returns False — an unsent SMS is recoverable (the daily
        sweep re-evaluates), a double text to a coordinator is not.
        """
        rows = self._post(
            "notifications",
            [{
                "monday_item_id": monday_item_id,
                "kind": kind,
                "payload": payload or {},
            }],
            prefer="resolution=ignore-duplicates,return=representation",
        )
        return bool(rows)

    def was_notified(self, monday_item_id, kind):
        rows = self._get(
            "notifications",
            {
                "monday_item_id": f"eq.{monday_item_id}",
                "kind": f"eq.{kind}",
                "select": "id",
                "limit": "1",
            },
        )
        return bool(rows)

    # -- app users & sessions ----------------------------------------------
    #
    # These back the web app's logins (0002_users.sql). Same never-raise
    # posture as the rest of the class: callers distinguish "no such user"
    # from "database down" via self.degraded, and index.py turns the latter
    # into a clear error rather than a silent login failure.

    def users_exist(self):
        """True, False, or None when the database can't answer."""
        if not self.enabled:
            return None
        self.degraded = None
        rows = self._get("app_users", {"select": "id", "limit": "1"})
        if self.degraded:
            return None
        return bool(rows)

    def user_by_email(self, email):
        rows = self._get(
            "app_users", {"email": f"eq.{email}", "select": "*", "limit": "1"}
        )
        return rows[0] if rows else None

    def user_by_id(self, user_id):
        rows = self._get(
            "app_users", {"id": f"eq.{user_id}", "select": "*", "limit": "1"}
        )
        return rows[0] if rows else None

    def list_users(self):
        return self._get("app_users", {"select": "*", "order": "created_at.asc"})

    def create_user(self, fields):
        rows = self._post("app_users", [fields])
        return rows[0] if rows else None

    def update_user(self, user_id, fields):
        rows = self._patch("app_users", {"id": f"eq.{user_id}"}, fields)
        return rows[0] if rows else None

    def create_session(self, user_id, token_sha256, expires_at, user_agent=None):
        rows = self._post(
            "app_sessions",
            [{
                "user_id": user_id,
                "token_sha256": token_sha256,
                "expires_at": expires_at,
                "user_agent": (user_agent or "")[:300] or None,
            }],
        )
        return rows[0] if rows else None

    def session_user(self, token_sha256):
        """The user behind a live session token hash, or None."""
        if not token_sha256:
            return None
        rows = self._get(
            "app_sessions",
            {
                "token_sha256": f"eq.{token_sha256}",
                "select": "expires_at,app_users(*)",
                "limit": "1",
            },
        )
        if not rows:
            return None
        session = rows[0]
        expires = str(session.get("expires_at") or "")
        try:
            from datetime import datetime, timezone
            when = datetime.fromisoformat(expires.replace("Z", "+00:00"))
            if when < datetime.now(timezone.utc):
                self._delete("app_sessions", {"token_sha256": f"eq.{token_sha256}"})
                return None
        except ValueError:
            return None
        user = session.get("app_users")
        if not user or not user.get("active"):
            return None
        return user

    def delete_session(self, token_sha256):
        return self._delete("app_sessions", {"token_sha256": f"eq.{token_sha256}"})

    def delete_user_sessions(self, user_id):
        return self._delete("app_sessions", {"user_id": f"eq.{user_id}"})
