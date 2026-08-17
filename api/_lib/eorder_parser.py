"""PLACEHOLDER — replace with the reference implementation.

`eorder_parser.py` from the build pack goes here UNCHANGED. Do not rewrite it
and do not port it while adding features at the same time; two of its behaviours
are load-bearing and non-obvious, and both are documented in its own docstring:

  1. load_workbook_tolerant() strips a non-standard <customWorkbookViews> GUID
     that hard-fails strict xlsx parsers. Excel opens these files fine. Do not
     "fix" this by asking the team to re-save.

  2. find() locates every value by searching for its LABEL and reading a cell at
     an offset. Do not convert to hardcoded cell references — TN revises the
     template and hardcoded refs break silently.

The rest of this service depends only on the public surface below. If you do
port it to another language, keep these names and the key set documented in
api/_lib/mapping.py under PARSER CONTRACT, and make scripts/verify.py pass.
"""

ACV_ORDER_REASONS = {
    "New Business", "New Customer", "Add-On", "Add on",
    "Add to Fleet", "ATF", "Upsell",
}


def parse(source):
    raise NotImplementedError(
        "api/_lib/eorder_parser.py is a placeholder. Copy the reference "
        "implementation from the build pack into this path."
    )


def load_workbook_tolerant(source):
    raise NotImplementedError
