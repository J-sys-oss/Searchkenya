"""System tests: complete administrator scenarios through the web interface (Flask test client)."""
import re
import time
import unittest

from app import create_app, crawler
from tests.base import SiteTestCase, PASSWORD


class WebCase(SiteTestCase):
    def setUp(self):
        super().setUp()
        self.app = create_app({"DB_PATH": self.db, "TESTING": True, "ALLOW_PRIVATE_HOSTS": True,
                               "RUN_JOBS_ASYNC": False, "WTF_CSRF_DISABLED": True})
        self.c = self.app.test_client()

    def login(self, user="admin", pw=PASSWORD):
        return self.c.post("/login", data={"username": user, "password": pw})

    def token(self):
        self.c.get("/login")
        with self.c.session_transaction() as s:
            return s.get("_csrf")

    def seed_site(self):
        self.site.put("", "Kenya Coffee", "Best coffee in Nairobi", links=["/menu"], when=time.time() - 500)
        self.site.put("menu", "Menu", "Espresso 200 shillings", when=time.time() - 500)

    def crawl_via_ui(self, depth=1):
        r = self.c.post("/queue/add", data={"seed_url": self.site.url(), "crawl_depth": depth})
        jid = self.rows("SELECT MAX(job_id) m FROM crawl_job")[0]["m"]
        crawler.run_job(self.db, jid, True)
        return r, jid


class TestAccess(WebCase):
    def test_login_valid_opens_dashboard(self):
        r = self.login()
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.c.get("/").status_code, 200)

    def test_login_wrong_password_refused(self):
        r = self.login(pw="wrong-password")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"Invalid username or password", r.data)
        self.assertEqual(self.c.get("/").status_code, 302)

    def test_login_empty_fields_refused(self):
        r = self.c.post("/login", data={"username": "", "password": ""})
        self.assertIn(b"Invalid username or password", r.data)

    def test_protected_routes_require_login(self):
        for url in ("/", "/queue", "/report", "/api/stats", "/search", "/export/csv", "/export/pdf"):
            r = self.c.get(url)
            self.assertEqual(r.status_code, 302, url)
            self.assertIn("/login", r.headers["Location"], url)

    def test_five_failures_lock_account(self):
        for _ in range(5):
            self.login(pw="bad")
        r = self.login()
        self.assertIn(b"locked", r.data.lower())
        self.assertEqual(self.c.get("/").status_code, 302)

    def test_logout_ends_session(self):
        self.login()
        self.c.post("/logout")
        self.assertEqual(self.c.get("/queue").status_code, 302)

    def test_post_without_csrf_token_rejected(self):
        app = create_app({"DB_PATH": self.db, "TESTING": True, "RUN_JOBS_ASYNC": False})   # CSRF enabled
        c = app.test_client()
        c.get("/login")
        with c.session_transaction() as s:
            tok = s["_csrf"]
        self.assertEqual(c.post("/login", data={"username": "admin", "password": PASSWORD}).status_code, 400)
        self.assertEqual(c.post("/login", data={"username": "admin", "password": PASSWORD, "_csrf": "forged"}).status_code, 400)
        self.assertEqual(c.post("/login", data={"username": "admin", "password": PASSWORD, "_csrf": tok}).status_code, 302)

    def test_security_headers_present(self):
        r = self.c.get("/login")
        self.assertEqual(r.headers["X-Frame-Options"], "DENY")
        self.assertEqual(r.headers["X-Content-Type-Options"], "nosniff")
        self.assertIn("default-src 'self'", r.headers["Content-Security-Policy"])


class TestSeedAndQueue(WebCase):
    def setUp(self):
        super().setUp()
        self.seed_site()
        self.login()

    def test_add_seed_form_crawls_and_lists_pages(self):
        r, _ = self.crawl_via_ui()
        self.assertEqual(r.status_code, 302)
        html = self.c.get("/queue").data.decode()
        self.assertIn(self.site.url("menu"), html)
        self.assertIn("indexed", html.lower())

    def test_invalid_seed_urls_rejected(self):
        for bad in ("javascript:alert(1)", "ftp://x.co.ke", "not a url", ""):
            self.c.post("/queue/add", data={"seed_url": bad, "crawl_depth": 1})
        self.assertEqual(self.rows("SELECT COUNT(*) n FROM crawl_job")[0]["n"], 0)

    def test_invalid_depth_rejected(self):
        self.c.post("/queue/add", data={"seed_url": self.site.url(), "crawl_depth": 99})
        self.c.post("/queue/add", data={"seed_url": self.site.url(), "crawl_depth": "abc"})
        self.assertEqual(self.rows("SELECT COUNT(*) n FROM crawl_job")[0]["n"], 0)

    def test_private_addresses_blocked_in_production_mode(self):
        app = create_app({"DB_PATH": self.db, "TESTING": True, "RUN_JOBS_ASYNC": False, "WTF_CSRF_DISABLED": True})
        c = app.test_client()
        c.post("/login", data={"username": "admin", "password": PASSWORD})
        c.post("/queue/add", data={"seed_url": "http://169.254.169.254/latest/meta-data", "crawl_depth": 0})
        c.post("/queue/add", data={"seed_url": "http://localhost:8080/", "crawl_depth": 0})
        self.assertEqual(self.rows("SELECT COUNT(*) n FROM crawl_job")[0]["n"], 0)

    def test_recrawl_button_updates_changed_page(self):
        self.crawl_via_ui()
        pid = self.page("menu")["page_id"]
        self.site.put("menu", "Menu", "Espresso 250 shillings", when=time.time())
        self.c.post(f"/pages/{pid}/recrawl")
        self.assertIn("250 shillings", self.page("menu")["body_text"])

    def test_remove_button_deindexes_page(self):
        self.crawl_via_ui()
        pid = self.page("menu")["page_id"]
        self.c.post(f"/pages/{pid}/remove")
        self.assertEqual(self.page("menu")["index_status"], "removed")
        self.assertNotIn("Menu", self.c.get("/search?q=espresso").data.decode().replace("Menu</", ""))

    def test_unknown_page_returns_404(self):
        self.assertEqual(self.c.post("/pages/9999/recrawl").status_code, 404)
        self.assertEqual(self.c.post("/pages/9999/remove").status_code, 404)

    def test_stop_button_sets_flag(self):
        _, jid = self.crawl_via_ui()
        self.assertEqual(self.c.post(f"/jobs/{jid}/stop").status_code, 302)


class TestSearchAccuracy(WebCase):
    def setUp(self):
        super().setUp()
        self.seed_site()
        self.login()
        self.crawl_via_ui()

    def test_search_finds_indexed_content(self):
        self.assertIn("Menu", self.c.get("/search?q=espresso").data.decode())

    def test_search_reflects_edit_after_reconcile(self):
        self.site.put("menu", "Menu", "Espresso 250 shillings", when=time.time())
        self.c.post("/reconcile")
        self.assertIn("Menu", self.c.get("/search?q=250").data.decode())
        self.assertNotIn(self.site.url("menu"), self.c.get("/search?q=200+shillings").data.decode())

    def test_deleted_page_leaves_search_after_reconcile(self):
        """Core business problem from Section 1.1: obsolete pages must stop appearing in results."""
        self.assertIn(self.site.url("menu"), self.c.get("/search?q=espresso").data.decode())
        self.site.delete("menu")
        self.c.post("/reconcile")
        self.assertNotIn(self.site.url("menu"), self.c.get("/search?q=espresso").data.decode())

    def test_search_wildcard_characters_are_literal(self):
        self.assertNotIn(self.site.url("menu"), self.c.get("/search?q=%25").data.decode())

    def test_script_in_crawled_title_never_reaches_page_as_markup(self):
        self.site.put("evil", "<script>alert(1)</script>", "payload", when=time.time())
        self.site.put("", "Kenya Coffee", "root", links=["/evil"], when=time.time())
        self.c.post("/queue/add", data={"seed_url": self.site.url(), "crawl_depth": 1})
        crawler.run_job(self.db, self.rows("SELECT MAX(job_id) m FROM crawl_job")[0]["m"], True)
        for url in ("/queue", "/search?q=payload"):
            self.assertNotIn("<script>alert(1)</script>", self.c.get(url).data.decode())

    def test_templates_escape_stored_markup(self):
        """Even if hostile markup reached the database, the templates output it as inert text."""
        self.conn.execute("UPDATE indexed_page SET title='<script>alert(1)</script>' WHERE page_url=?",
                          (self.site.url("menu"),))
        self.conn.commit()
        html = self.c.get("/search?q=espresso").data.decode()
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)

    def test_repeated_recrawl_of_deleted_page_logs_once(self):
        self.site.delete("menu")
        pid = self.page("menu")["page_id"]
        for _ in range(3):
            self.c.post(f"/pages/{pid}/recrawl")
        self.assertEqual(len(self.issues("broken_link")), 1)

    def test_deindexed_page_returns_to_search_when_crawled_again(self):
        pid = self.page("menu")["page_id"]
        self.c.post(f"/pages/{pid}/remove")
        self.assertNotIn(self.site.url("menu"), self.c.get("/search?q=espresso").data.decode())
        crawler.run_job(self.db, self.rows("SELECT MAX(job_id) m FROM crawl_job")[0]["m"], True)
        self.assertIn(self.site.url("menu"), self.c.get("/search?q=espresso").data.decode())

    def test_unreachable_host_recorded_as_pending_not_obsolete(self):
        """A network failure is not proof that a page is gone, so it must not de-index the page."""
        jid = self.make_job("http://127.0.0.1:9/x")
        crawler.run_job(self.db, jid, True)
        r = self.rows("SELECT * FROM indexed_page WHERE page_url='http://127.0.0.1:9/x'")[0]
        self.assertEqual((r["index_status"], r["http_status"]), ("pending", 0))


class TestDashboardAndReports(WebCase):
    def setUp(self):
        super().setUp()
        self.site.put("", "Home", "welcome", links=["/ok", "/gone"], when=time.time() - 500)
        self.site.put("ok", "OK page", "fine", when=time.time() - 500)
        self.login()
        self.crawl_via_ui()

    def test_dashboard_counts_after_crawl_with_broken_link(self):
        s = self.c.get("/api/stats").get_json()
        self.assertEqual(s["total_crawled"], 3)
        self.assertEqual(s["open_discrepancies"], 1)           # the 404 link
        self.assertEqual(s["all_discrepancies"], 3)            # two newly indexed pages + one broken link

    def test_dashboard_page_renders_log(self):
        html = self.c.get("/").data.decode()
        self.assertIn("Broken Link (404/410)", html)
        self.assertIn("Missing Page in Index", html)

    def test_live_stats_change_without_reload(self):
        before = self.c.get("/api/stats").get_json()
        self.site.delete("ok")
        self.c.post("/reconcile")
        after = self.c.get("/api/stats").get_json()
        self.assertNotEqual(before, after)

    def test_csv_export(self):
        r = self.c.get("/export/csv")
        self.assertEqual(r.mimetype, "text/csv")
        lines = r.data.decode().strip().splitlines()
        self.assertTrue(lines[0].startswith("log_id,detected_at,page_url,issue_type"))
        self.assertEqual(len(lines) - 1, self.rows("SELECT COUNT(*) n FROM discrepancy_log")[0]["n"])

    def test_pdf_export_is_valid_pdf(self):
        r = self.c.get("/export/pdf")
        self.assertEqual(r.mimetype, "application/pdf")
        self.assertTrue(r.data.startswith(b"%PDF"))
        self.assertGreater(len(r.data), 1000)

    def test_report_saves_snapshot(self):
        self.assertEqual(self.c.get("/report").status_code, 200)
        snap = self.rows("SELECT * FROM system_report")[0]
        self.assertEqual(snap["discrepancy_count"], self.rows("SELECT COUNT(*) n FROM discrepancy_log")[0]["n"])

    def test_reconcile_button_reports_outcome(self):
        r = self.c.post("/reconcile", follow_redirects=True)
        self.assertIn(b"Reconciliation finished", r.data)


if __name__ == "__main__":
    unittest.main()
