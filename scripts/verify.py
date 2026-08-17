"""Acceptance gate for extraction.

    python scripts/verify.py samples/

Runs the parser over every sample it can find and asserts the values in
fixtures/expected.json. A missing sample is reported as MISSING and fails the
run — a gate that quietly passes because the file it was guarding disappeared is
worse than no gate.

Also asserts two invariants that hold across every file regardless of order type:

  · vehicles is always empty. TN's template ships red example rows (a Kenworth
    K900, VIN 65F45678643132, "Bin 1") in all five files including orders with
    no vehicles, and nobody deletes them. Unfiltered, that publishes a truck
    that does not exist onto an installer's job sheet (§8.2).

  · ACV is only populated for new-revenue order reasons. A number here on a
    renewal inflates a new-business target with revenue that isn't new (§4.1).
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "api"))

from _lib.eorder_parser import ACV_ORDER_REASONS, parse  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
EXPECTED_PATH = os.path.join(HERE, "..", "fixtures", "expected.json")

GREEN, RED, YELLOW, DIM, RESET = (
    "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"
)


def check(sample_dir):
    with open(EXPECTED_PATH) as handle:
        expected_all = {
            k: v for k, v in json.load(handle).items() if not k.startswith("_")
        }

    failures, missing = [], []

    for filename, expected in expected_all.items():
        path = os.path.join(sample_dir, filename)
        if not os.path.exists(path):
            missing.append(filename)
            print(f"{YELLOW}MISSING{RESET}  {filename}")
            continue

        try:
            parsed = parse(path)
        except Exception as exc:  # noqa: BLE001
            failures.append((filename, f"parse raised {type(exc).__name__}: {exc}"))
            print(f"{RED}ERROR{RESET}    {filename}")
            continue

        problems = []

        for key, want in expected.items():
            if key.startswith("_"):
                continue
            got = parsed.get(key)
            if isinstance(want, float) and isinstance(got, (int, float)):
                if abs(got - want) > 0.01:
                    problems.append(f"{key}: expected {want}, got {got}")
            elif got != want:
                problems.append(f"{key}: expected {want!r}, got {got!r}")

        want_sites = expected.get("_expect_multi_site_count")
        if want_sites is not None:
            got_sites = len(parsed.get("multi_site") or [])
            if got_sites != want_sites:
                problems.append(f"multi_site: expected {want_sites} sites, got {got_sites}")

        # --- cross-file invariants ---
        if parsed.get("vehicles"):
            problems.append(
                f"vehicles is not empty ({len(parsed['vehicles'])}) — "
                "TEMPLATE_VEHICLES filtering has regressed"
            )

        reason = str(parsed.get("order_reason") or "").strip().lower()
        qualifies = reason in {r.strip().lower() for r in ACV_ORDER_REASONS}
        if parsed.get("acv") is not None and not qualifies:
            problems.append(
                f"ACV populated on a non-new-revenue order reason "
                f"({parsed.get('order_reason')})"
            )
        if parsed.get("acv") == 0:
            problems.append("ACV is 0 — should be empty, not zero")

        if problems:
            failures.append((filename, problems))
            print(f"{RED}FAIL{RESET}     {filename}")
            for problem in problems:
                print(f"           {problem}")
        else:
            print(f"{GREEN}ok{RESET}       {filename}  {DIM}"
                  f"{parsed.get('order_reason')}{RESET}")

    print()
    if missing:
        print(f"{YELLOW}{len(missing)} sample(s) missing from {sample_dir}{RESET}")
        for filename in missing:
            print(f"  {filename}")
    if failures:
        print(f"{RED}{len(failures)} file(s) failed{RESET}")

    if not failures and not missing:
        print(f"{GREEN}All {len(expected_all)} samples pass.{RESET}")

    # The Upsell branch is unproven no matter what this run says.
    print(f"\n{DIM}Note: no Upsell sample is in this set. That ACV branch is "
          f"untested (brief §4.1).{RESET}")

    return 1 if (failures or missing) else 0


if __name__ == "__main__":
    directory = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "..", "samples")
    sys.exit(check(directory))
