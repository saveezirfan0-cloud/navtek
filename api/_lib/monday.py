"""monday.com API wrapper.

This is deliberately the only module that touches the monday token. The portal
(phase 2) calls this service rather than monday directly, so the token stays
server side — see the security note at the end of the build brief.

Kept generic on purpose: brief §9 expects this wrapper to be reused as the
portal's backend.
"""

import json
import time

import httpx

from . import config


class MondayError(RuntimeError):
    """A GraphQL-level error from monday, with the raw errors attached."""

    def __init__(self, message, errors=None, query=None):
        super().__init__(message)
        self.errors = errors or []
        self.query = query


# One HTTP client per process, not per request. Every route builds a Monday()
# and a fresh httpx.Client pays a new TCP+TLS handshake to api.monday.com; the
# process outlives thousands of requests on a warm serverless instance, and
# these functions serve one request at a time, so sharing is safe.
_shared_client = httpx.Client(timeout=30)


class Monday:
    def __init__(self, token=None, url=None, version=None, timeout=30):
        self.token = token or config.MONDAY_TOKEN
        self.url = url or config.MONDAY_API_URL
        self.version = version or config.MONDAY_API_VERSION
        self._client = _shared_client if timeout == 30 else httpx.Client(timeout=timeout)

    # -- transport ---------------------------------------------------------

    def gql(self, query, variables=None, retries=3):
        """Run a query. Retries on 429 and 5xx with backoff.

        monday's complexity budget is per-minute; a burst of file drops will hit
        it, and the failure mode we want is "slower", not "lost order".
        """
        payload = {"query": query, "variables": variables or {}}
        headers = {
            "Authorization": self.token,
            "API-Version": self.version,
            "Content-Type": "application/json",
        }

        last_error = None
        for attempt in range(retries):
            response = self._client.post(self.url, json=payload, headers=headers)

            if response.status_code in (429, 500, 502, 503, 504):
                last_error = f"HTTP {response.status_code}"
                time.sleep(2**attempt)
                continue

            response.raise_for_status()
            body = response.json()

            if "errors" in body:
                messages = "; ".join(
                    e.get("message", str(e)) for e in body["errors"]
                )
                # Complexity exhaustion is retryable; a bad query is not.
                if "complexity" in messages.lower() and attempt < retries - 1:
                    last_error = messages
                    time.sleep(2**attempt)
                    continue
                raise MondayError(messages, body["errors"], query)

            return body["data"]

        raise MondayError(f"monday unavailable after {retries} attempts: {last_error}")

    def me(self):
        """Who the token belongs to. The cheapest possible auth check."""
        data = self.gql("query { me { name email } }")
        return data.get("me") or {}

    def board_name(self, board_id):
        data = self.gql(
            "query ($b: [ID!]) { boards (ids: $b) { id name } }",
            {"b": [str(board_id)]},
        )
        boards = data.get("boards") or []
        return boards[0]["name"] if boards else None

    # -- reads -------------------------------------------------------------

    def board_columns(self, board_id):
        """[{id, title, type, settings_str}] for a board.

        settings_str carries a status column's actual labels. The writer needs
        those because the labels on a live board are the truth — monday rejects
        the whole change_multiple_column_values mutation over one label it
        doesn't recognise, taking every other field down with it.
        """
        data = self.gql(
            "query ($b: [ID!]) { boards (ids: $b) { columns { id title type settings_str } } }",
            {"b": [str(board_id)]},
        )
        boards = data.get("boards") or []
        return boards[0]["columns"] if boards else []

    def board_groups(self, board_id):
        data = self.gql(
            "query ($b: [ID!]) { boards (ids: $b) { groups { id title } } }",
            {"b": [str(board_id)]},
        )
        boards = data.get("boards") or []
        return boards[0]["groups"] if boards else []

    def item(self, item_id):
        """One item with all column values (text + raw JSON)."""
        data = self.gql(
            """
            query ($i: [ID!]) {
              items (ids: $i) {
                id name group { id title }
                board { id }
                column_values { id type text value }
              }
            }
            """,
            {"i": [str(item_id)]},
        )
        items = data.get("items") or []
        return items[0] if items else None

    def find_by_column_value(self, board_id, column_id, value):
        """Exact-match lookup. Used for the opportunity_id 1:1 join (§3.4)."""
        data = self.gql(
            """
            query ($b: ID!, $c: String!, $v: [String]!) {
              items_page_by_column_values (
                board_id: $b, limit: 50,
                columns: [{column_id: $c, column_values: $v}]
              ) { items { id name group { id title } } }
            }
            """,
            {"b": str(board_id), "c": column_id, "v": [str(value)]},
        )
        page = data.get("items_page_by_column_values") or {}
        return page.get("items") or []

    def asset_urls(self, item_id, column_id):
        """Fresh public_urls for the files in one file column.

        These expire after an hour, so this is called at the moment of use and
        the result is never persisted — for the webhook, and again every time an
        installer taps a Vehicle List download in the portal (§6.3).
        """
        data = self.gql(
            """
            query ($i: [ID!]) {
              items (ids: $i) {
                column_values {
                  id
                  ... on FileValue {
                    files { ... on FileAssetValue { asset { id name public_url } } }
                  }
                }
              }
            }
            """,
            {"i": [str(item_id)]},
        )
        items = data.get("items") or []
        if not items:
            return []
        for column in items[0]["column_values"]:
            if column["id"] == column_id:
                return [f["asset"] for f in (column.get("files") or []) if f.get("asset")]
        return []

    def download(self, url):
        """Fetch asset bytes. Separate client — no monday auth header on S3."""
        with httpx.Client(timeout=config.ASSET_FETCH_TIMEOUT, follow_redirects=True) as c:
            response = c.get(url)
            response.raise_for_status()
            return response.content

    # -- writes ------------------------------------------------------------

    def set_columns(self, board_id, item_id, values):
        """change_multiple_column_values. `values` is {column_id: value}."""
        if not values:
            return None
        data = self.gql(
            """
            mutation ($b: ID!, $i: ID!, $v: JSON!) {
              change_multiple_column_values (board_id: $b, item_id: $i, column_values: $v) { id }
            }
            """,
            {"b": str(board_id), "i": str(item_id), "v": json.dumps(values)},
        )
        return data["change_multiple_column_values"]

    def rename(self, board_id, item_id, name):
        return self.set_columns(board_id, item_id, {"name": name})

    def create_item(self, board_id, group_id, name, values=None):
        data = self.gql(
            """
            mutation ($b: ID!, $g: String!, $n: String!, $v: JSON!) {
              create_item (board_id: $b, group_id: $g, item_name: $n, column_values: $v) { id }
            }
            """,
            {
                "b": str(board_id),
                "g": group_id,
                "n": name,
                "v": json.dumps(values or {}),
            },
        )
        return data["create_item"]["id"]

    def create_subitem(self, parent_item_id, name, values=None):
        data = self.gql(
            """
            mutation ($p: ID!, $n: String!, $v: JSON!) {
              create_subitem (parent_item_id: $p, item_name: $n, column_values: $v) {
                id board { id }
              }
            }
            """,
            {"p": str(parent_item_id), "n": name, "v": json.dumps(values or {})},
        )
        return data["create_subitem"]

    def subitems(self, item_id):
        data = self.gql(
            """
            query ($i: [ID!]) {
              items (ids: $i) {
                subitems { id name board { id } column_values { id type text value } }
              }
            }
            """,
            {"i": [str(item_id)]},
        )
        items = data.get("items") or []
        return items[0].get("subitems") or [] if items else []

    def post_update(self, item_id, body):
        data = self.gql(
            "mutation ($i: ID!, $b: String!) { create_update (item_id: $i, body: $b) { id } }",
            {"i": str(item_id), "b": body},
        )
        return data["create_update"]["id"]

    def create_column(self, board_id, title, column_type, settings=None, description=None):
        variables = {
            "b": str(board_id),
            "t": title,
            "ct": column_type,
            "d": description or "",
        }
        settings_arg = ""
        if settings is not None:
            variables["s"] = json.dumps(settings)
            settings_arg = ", defaults: $s"
        data = self.gql(
            f"""
            mutation ($b: ID!, $t: String!, $ct: ColumnType!, $d: String{
                ', $s: JSON' if settings is not None else ''}) {{
              create_column (board_id: $b, title: $t, column_type: $ct,
                             description: $d{settings_arg}) {{ id title type }}
            }}
            """,
            variables,
        )
        return data["create_column"]

    def webhooks(self, board_id):
        """Existing webhooks on a board, so we never register a duplicate."""
        data = self.gql(
            "query ($b: ID!) { webhooks (board_id: $b) { id event config } }",
            {"b": str(board_id)},
        )
        return data.get("webhooks") or []

    def create_webhook(self, board_id, url, event, config_json=None):
        variables = {"b": str(board_id), "u": url, "e": event}
        config_arg = ""
        if config_json is not None:
            variables["c"] = json.dumps(config_json)
            config_arg = ", config: $c"
        data = self.gql(
            f"""
            mutation ($b: ID!, $u: String!, $e: WebhookEventType!{
                ', $c: JSON' if config_json is not None else ''}) {{
              create_webhook (board_id: $b, url: $u, event: $e{config_arg}) {{ id board_id }}
            }}
            """,
            variables,
        )
        return data["create_webhook"]
