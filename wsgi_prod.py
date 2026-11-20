"""Real (non-demo) deployment entry point: an empty index where you add your own domains.

    gunicorn wsgi_prod:app --workers 1 --threads 4 --bind 0.0.0.0:$PORT

Environment variables:
    ADMIN_PASSWORD   password for user "admin" (required, min 8 characters)
    SK_SECRET        session signing key (set a long random value)
    SK_DB            database file path (default: searchkenya.db next to this file)
    SK_INTERVAL      seconds between automatic re-verification runs (default 60)
    SK_ALLOW_PRIVATE set to 1 only if you must crawl local/private addresses (default 0 = blocked)
"""
import os
import sqlite3
import sys

from app import create_app
from app.auth import create_user
from app.db import connect, init_db

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("SK_DB", os.path.join(HERE, "searchkenya.db"))
PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
if len(PASSWORD) < 8:
    sys.exit("Set the ADMIN_PASSWORD environment variable (at least 8 characters) before starting.")

init_db(DB)
_conn = connect(DB)
try:
    create_user(_conn, "admin", PASSWORD)
except sqlite3.IntegrityError:
    pass                                   # admin already exists in a kept database
_conn.close()

app = create_app({
    "DB_PATH": DB,
    "ALLOW_PRIVATE_HOSTS": os.environ.get("SK_ALLOW_PRIVATE", "0") == "1",
    "SCHEDULER_INTERVAL": int(os.environ.get("SK_INTERVAL", "60")),
})
