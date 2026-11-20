"""One-command demo: starts a small test website AND the administration site, already filled with data.

    python demo.py          then open  http://127.0.0.1:5000   (login shown in the terminal)

While it runs, the test website changes by itself (a price is edited, a page is deleted, a new page
appears) and the background scheduler reconciles the index, so you can watch the dashboard update live.
Uses a throw-away database (demo_data/demo.db); your real searchkenya.db is never touched.
"""
import os
import shutil
import threading
import time

from app import create_app, crawler
from app.auth import create_user
from app.db import connect, init_db, now
from mock_site.server import MockSite

USER, PASSWORD = "admin", "Demo-Pass-2026!"
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "demo_data")
shutil.rmtree(DATA, ignore_errors=True)
os.makedirs(DATA)
DB = os.path.join(DATA, "demo.db")

init_db(DB)
conn = connect(DB)
create_user(conn, USER, PASSWORD)

# ---- a fictitious shop website that the crawler will index
site = MockSite().start()
old = time.time() - 86400
site.put("", "Mama Njeri Fabrics - Home", "Fabrics and tailoring in Nairobi", ["/prices", "/offers", "/contact", "/gallery"], when=old)
site.put("prices", "Price list", "Kitenge 600 shillings per metre", ["/"], when=old)
site.put("offers", "Festive offers", "Buy two kitenge and get one free until 31 October", ["/"], when=old)
site.put("contact", "Contact us", "Shop 12, Moi Avenue, Nairobi", ["/"], when=old)
site.put("gallery", "Gallery", "Photos of recent tailoring work", ["/"], when=old)

cur = conn.execute("INSERT INTO crawl_job(user_id,seed_url,crawl_depth,scheduled_at) VALUES(1,?,2,?)", (site.url(), now()))
conn.commit()
crawler.run_job(DB, cur.lastrowid, allow_private=True)      # allow_private: the test site is on localhost
conn.close()


def shop_owner():
    """Simulates the shop owner changing the website while the system watches it."""
    time.sleep(25)
    site.put("prices", "Price list", "Kitenge 750 shillings per metre", ["/"])
    print("  [demo] shop owner raised the prices        -> watch it appear as 'Obsolete Content Cached / Auto-Reindexed'")
    time.sleep(25)
    site.delete("offers")
    print("  [demo] shop owner deleted the offers page  -> watch it become Obsolete / Broken Link")
    time.sleep(25)
    site.put("contact", "Contact us", "We have moved to Shop 40, Kimathi Street, Nairobi", ["/"])
    print("  [demo] shop owner changed the contact page -> search for 'Kimathi' after it is re-indexed")


threading.Thread(target=shop_owner, daemon=True).start()

app = create_app({"DB_PATH": DB, "ALLOW_PRIVATE_HOSTS": True, "SCHEDULER_INTERVAL": 10})
PORT = int(os.environ.get("PORT", 5000))
print(f"""
==============================================================
  SearchKenya Indexing Management - DEMO
  Open:      http://127.0.0.1:{PORT}
  Username:  {USER}
  Password:  {PASSWORD}
  Test site: {site.base}   (the website being monitored)
  Stop with  Ctrl+C
==============================================================""")
app.run(host="127.0.0.1", port=PORT, debug=False)
