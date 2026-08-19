"""Make the suite hermetic before any app module is imported.

api/index.py and api/_lib/config.py read the environment at import time. A
developer (or CI) with real credentials exported — PORTAL_SHARED_SECRET
especially — silently changes what several tests exercise: the endpoint-guard
tests start passing because of _authorise()'s portal-secret check rather than
the session/setup-key guards they claim to test. Scrub everything the app
reads before test modules import it.
"""

import os

for name in (
    "MONDAY_TOKEN", "MONDAY_API_URL", "MONDAY_API_VERSION",
    "SUPABASE_URL", "SUPABASE_SERVICE_KEY", "SUPABASE_SECRET_KEY",
    "SUPABASE_URL_2", "SUPABASE_SERVICE_KEY_2",
    "PORTAL_SHARED_SECRET", "SETUP_KEY", "COLUMN_IDS",
    "ORDERS_BOARD_ID", "INSTALLERS_BOARD_ID", "WRITE_ORDER_TYPE",
):
    os.environ.pop(name, None)
