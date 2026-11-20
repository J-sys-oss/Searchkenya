"""Online deployment entry point (Render, Railway, PythonAnywhere-style WSGI hosts, or any gunicorn server).

    gunicorn wsgi:app --workers 1 --threads 4 --bind 0.0.0.0:$PORT

Starts the administration site with a small sample website (Mama Njeri Fabrics) to monitor, so the
live system can be shown to visitors. Environment variables:
    ADMIN_PASSWORD   login password for user "admin"   (default: Demo-Pass-2026!)
    SK_SECRET        session signing key               (default: random each start)
Run ONE worker only: the sample website and the scheduler live inside that process.
"""
import os
import shutil
import tempfile
import threading
import time

from app import create_app, crawler
from app.auth import create_user
from app.db import connect, init_db, now
from mock_site.server import MockSite

USER = "admin"
PASSWORD = os.environ.get("ADMIN_PASSWORD", "Demo-Pass-2026!")
DATA = os.path.join(tempfile.gettempdir(), "searchkenya_data")
shutil.rmtree(DATA, ignore_errors=True)
os.makedirs(DATA)
DB = os.path.join(DATA, "searchkenya.db")

init_db(DB)
_conn = connect(DB)
create_user(_conn, USER, PASSWORD)

site = MockSite().start()          # the website being monitored, served on localhost inside this process


def _shop_reset():
    old = time.time() - 86400
    site.put("", "Mama Njeri Fabrics - Home", "Fabrics and tailoring in Nairobi", ["/prices", "/offers", "/contact", "/gallery"], when=old)
    site.put("prices", "Price list", "Kitenge 600 shillings per metre", ["/"], when=old)
    site.put("offers", "Festive offers", "Buy two kitenge and get one free until 31 October", ["/"], when=old)
    site.put("contact", "Contact us", "Shop 12, Moi Avenue, Nairobi", ["/"], when=old)
    site.put("gallery", "Gallery", "Photos of recent tailoring work", ["/"], when=old)


_shop_reset()
_cur = _conn.execute("INSERT INTO crawl_job(user_id,seed_url,crawl_depth,scheduled_at) VALUES(1,?,2,?)", (site.url(), now()))
_conn.commit()
crawler.run_job(DB, _cur.lastrowid, allow_private=True)
_conn.close()


def _shop_owner():
    """Repeats forever: the shop owner edits the site, the scheduler notices, then the shop is restored."""
    while True:
        time.sleep(60)
        site.put("prices", "Price list", "Kitenge 750 shillings per metre", ["/"])
        time.sleep(40)
        site.delete("offers")
        time.sleep(40)
        site.put("contact", "Contact us", "We have moved to Shop 40, Kimathi Street, Nairobi", ["/"])
        time.sleep(90)
        _shop_reset()


threading.Thread(target=_shop_owner, daemon=True).start()

app = create_app({"DB_PATH": DB, "ALLOW_PRIVATE_HOSTS": True, "SCHEDULER_INTERVAL": 15})
