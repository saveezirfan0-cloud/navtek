"""Standalone diagnostic.

Deliberately imports nothing but the standard library, and is a separate Vercel
function from api/index.py. That is the whole point: when the main function
fails at import — a missing dependency, a file that didn't make it into the
repository — every route it serves returns a bare HTTP 500 with no body,
because the crash happens before any error handler exists to explain it.

This one still answers. Open /api/py/diag.
"""

import json
import os
import sys
from http.server import BaseHTTPRequestHandler

# Third-party packages the app needs, and what breaks without each.
REQUIRED = {
    "openpyxl": "reading eOrder spreadsheets",
    "fastapi": "every API route",
    "httpx": "talking to monday and Supabase",
    "pydantic": "fastapi's request handling",
}

# Modules that must be present in api/_lib for the app to import at all.
EXPECTED_LIB = [
    "__init__.py", "bootstrap.py", "columns.py", "config.py",
    "eorder_parser.py", "ingest.py", "installers.py", "mapping.py",
    "monday.py", "portal.py", "store.py",
]


def _actually_set(value):
    """Same judgement the app makes: whitespace or bare quotes are NOT set.

    This module deliberately imports nothing from the app, so the one rule it
    shares with config._clean_secret is duplicated here — env_present saying
    "present" for a value the app treats as absent sends the debugger the
    wrong way, which is the exact failure this endpoint exists to prevent.
    """
    value = (value or "").strip()
    if len(value) > 1 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1].strip()
    return bool(value)


def _packages():
    out = {}
    for name, why in REQUIRED.items():
        try:
            module = __import__(name)
            out[name] = {
                "ok": True,
                "version": getattr(module, "__version__", "unknown"),
            }
        except Exception as exc:  # noqa: BLE001
            out[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}", "needed_for": why}
    return out


def _lib_files():
    here = os.path.dirname(os.path.abspath(__file__))
    lib = os.path.join(here, "_lib")
    if not os.path.isdir(lib):
        return {
            "ok": False,
            "error": "api/_lib is not in the deployment at all",
            "looked_in": lib,
            "api_dir_contains": sorted(os.listdir(here))[:40],
        }
    present = sorted(f for f in os.listdir(lib) if f.endswith(".py"))
    missing = [f for f in EXPECTED_LIB if f not in present]
    return {
        "ok": not missing,
        "present": present,
        "missing": missing,
        "sizes": {f: os.path.getsize(os.path.join(lib, f)) for f in present},
    }


def _import_app():
    """Try what api/index.py does, and report the first failure verbatim."""
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    steps = {}
    for module in ("_lib.config", "_lib.columns", "_lib.monday", "_lib.mapping",
                   "_lib.eorder_parser", "_lib.store", "_lib.bootstrap",
                   "_lib.installers", "_lib.portal", "_lib.ingest"):
        try:
            __import__(module)
            steps[module] = "ok"
        except Exception as exc:  # noqa: BLE001
            steps[module] = f"{type(exc).__name__}: {exc}"
    return steps


def _verdict(packages, lib, imports):
    bad_packages = [n for n, v in packages.items() if not v["ok"]]
    if bad_packages:
        return (
            f"Missing Python package(s): {', '.join(bad_packages)}. "
            "requirements.txt is not being installed — check it is at the top "
            "level of the repository (and that api/requirements.txt exists), "
            "then redeploy."
        )
    if not lib.get("ok"):
        missing = lib.get("missing") or []
        return (
            f"Missing from api/_lib: {', '.join(missing)}. "
            "Upload the missing file(s) to GitHub — folders whose name starts "
            "with an underscore are easy to miss in a drag-and-drop upload."
            if missing else lib.get("error", "api/_lib is not deployed")
        )
    broken = {k: v for k, v in imports.items() if v != "ok"}
    if broken:
        first = next(iter(broken.items()))
        return f"{first[0]} fails to import — {first[1]}"
    return "Everything imports. If routes still fail, the fault is at runtime, not startup — check the Logs tab in Vercel."


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        packages = _packages()
        lib = _lib_files()
        imports = _import_app()

        payload = {
            "python": sys.version.split()[0],
            "packages": packages,
            "lib_files": lib,
            "imports": imports,
            "verdict": _verdict(packages, lib, imports),
            "env_present": sorted(
                k for k in (
                    "MONDAY_TOKEN", "SUPABASE_URL", "SUPABASE_SERVICE_KEY",
                    "SUPABASE_SECRET_KEY", "SUPABASE_URL_2",
                    "SUPABASE_SERVICE_KEY_2",
                    "SETUP_KEY", "COLUMN_IDS", "ORDERS_BOARD_ID",
                    "INSTALLERS_BOARD_ID", "PORTAL_SHARED_SECRET",
                ) if _actually_set(os.environ.get(k))
            ),
        }

        body = json.dumps(payload, indent=2).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
