"""The diagnostic must know about every module it is diagnosing.

api/diag.py is what answers when api/index.py cannot import — a missing file,
a dependency that did not install. It lists the modules it expects, and that
list had drifted: eight of them, including the one added the day the Python
function went down, were absent. A file missing from the deployment would have
been reported as "everything present" while every route returned a bare 500.
"""

import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "api"))

_spec = importlib.util.spec_from_file_location(
    "vercel_diag", os.path.join(ROOT, "api", "diag.py"))
diag = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(diag)


def _actual_lib_modules():
    lib = os.path.join(ROOT, "api", "_lib")
    return sorted(f for f in os.listdir(lib) if f.endswith(".py"))


def test_every_lib_module_is_one_diag_would_miss_if_it_vanished():
    """Add a module to api/_lib and this fails until diag knows about it."""
    assert sorted(diag.EXPECTED_LIB) == _actual_lib_modules()


def test_diag_reports_the_lib_directory_as_complete():
    result = diag._lib_files()
    assert result["ok"] is True, result.get("missing")
    assert result["missing"] == []


def test_the_import_walk_covers_every_module_too():
    """A module present but broken is the other half of the failure — the
    walk has to actually import it for its error to be reported."""
    import inspect

    source = inspect.getsource(diag._import_app)
    for name in _actual_lib_modules():
        if name == "__init__.py":
            continue
        assert f'_lib.{name[:-3]}' in source, f"diag never imports {name}"


def test_diag_imports_nothing_from_the_app():
    """Its whole value is answering when the app cannot. An import of the app
    at module level would take the diagnostic down with the thing it
    diagnoses."""
    with open(os.path.join(ROOT, "api", "diag.py"), encoding="utf-8") as handle:
        head = handle.read().split("def ", 1)[0]
    assert "from _lib" not in head and "import _lib" not in head
