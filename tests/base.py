import os, tempfile, time, unittest
from mock_site.server import MockSite
from app.db import init_db, connect, now
from app.auth import create_user

PASSWORD = "S3cure-pass!"


class SiteTestCase(unittest.TestCase):
    """Each test gets a fresh database file and a fresh mock website."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "test.db")
        init_db(self.db)
        self.conn = connect(self.db)
        create_user(self.conn, "admin", PASSWORD)
        self.site = MockSite().start()

    def tearDown(self):
        self.site.stop()
        self.conn.close()

    def make_job(self, url=None, depth=1):
        cur = self.conn.execute("INSERT INTO crawl_job(user_id,seed_url,crawl_depth,scheduled_at)"
                                " VALUES(1,?,?,?)", (url or self.site.url(), depth, now()))
        self.conn.commit()
        return cur.lastrowid

    def rows(self, sql, *a):
        return [dict(r) for r in self.conn.execute(sql, a)]

    def page(self, path):
        r = self.rows("SELECT * FROM indexed_page WHERE page_url=?", self.site.url(path))
        return r[0] if r else None

    def issues(self, kind=None):
        sql = "SELECT * FROM discrepancy_log" + (" WHERE issue_type=?" if kind else "")
        return self.rows(sql, *([kind] if kind else []))
