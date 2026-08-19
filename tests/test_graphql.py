"""Static checks on the GraphQL we send to monday.

Two mistakes here are invisible until a webhook fires in production and are
indistinguishable from a broken parse in the monday Update, so they are worth
catching in a test run instead:

  * an unused variable declaration — monday rejects the whole document
  * `[String!]` where `items_page_by_column_values` wants `[String]!` —
    a nullable list of non-null strings, versus a non-null list of nullable
    strings. Easy to transpose, and it failed live.
"""

import pathlib
import re

LIB = pathlib.Path(__file__).resolve().parent.parent / "api" / "_lib"


def documents():
    """Yield (filename, document, whole file text).

    The file text comes along because two mutations assemble their document
    conditionally — the variable is declared in the f-string and used in a
    sibling string — so a per-document usage check reports them as unused when
    they are not.
    """
    for path in LIB.glob("*.py"):
        if path.name == "eorder_parser.py":
            continue
        text = path.read_text()
        for match in re.findall(r'"""(.*?)"""', text, re.S) + re.findall(r'gql\(\s*"([^"]+)"', text):
            if "query " in match or "mutation " in match:
                yield path.name, match, text


def test_no_declared_variable_is_left_unused():
    """monday rejects a document that declares a variable it never uses.

    This is what took down the whole setup page once: a `$n` declared and
    passed but never referenced, which made every call using it fail.
    """
    for name, doc, whole in documents():
        declared = set(re.findall(r"\$(\w+)\s*:", doc))
        used = set(re.findall(r"\$(\w+)(?!\s*:)", whole))
        assert not (declared - used), f"{name}: unused variable {declared - used}"


def test_column_values_uses_a_non_null_list_of_nullable_strings():
    for name, doc, _ in documents():
        if "items_page_by_column_values" not in doc:
            continue
        assert "[String!]" not in doc, (
            f"{name}: column_values expects [String]!, not [String!]"
        )
        assert "[String]!" in doc, f"{name}: column_values variable is not typed"
