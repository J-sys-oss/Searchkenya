"""Integration tests: crawler + verification engine against the mock website."""
import time
from app import crawler
from tests.base import SiteTestCase


class TestCrawl(SiteTestCase):
    def setUp(self):
        super().setUp()
        self.site.put("", "Home", "welcome", links=["/a", "/b", "http://other-site.invalid/x"])
        self.site.put("a", "Page A", "alpha", links=["/deep"])
        self.site.put("b", "Page B", "beta")
        self.site.put("deep", "Deep", "deep page")

    def test_discovers_pages_within_depth(self):
        stats = crawler.run_job(self.db, self.make_job(depth=1), True)
        self.assertEqual(stats["new"], 3)                 # home, a, b  (not deep)
        self.assertIsNone(self.page("deep"))

    def test_depth_two_reaches_deep_page(self):
        crawler.run_job(self.db, self.make_job(depth=2), True)
        self.assertIsNotNone(self.page("deep"))

    def test_depth_zero_indexes_only_seed(self):
        crawler.run_job(self.db, self.make_job(depth=0), True)
        self.assertEqual(len(self.rows("SELECT * FROM indexed_page")), 1)

    def test_offsite_links_not_followed(self):
        crawler.run_job(self.db, self.make_job(depth=2), True)
        urls = [r["page_url"] for r in self.rows("SELECT page_url FROM indexed_page")]
        self.assertFalse(any("other-site" in u for u in urls))

    def test_job_status_done(self):
        jid = self.make_job()
        crawler.run_job(self.db, jid, True)
        self.assertEqual(self.rows("SELECT status FROM crawl_job WHERE job_id=?", jid)[0]["status"], "done")

    def test_new_pages_logged_and_resolved(self):
        crawler.run_job(self.db, self.make_job(), True)
        new = self.issues("unindexed_new")
        self.assertEqual(len(new), 3)
        self.assertTrue(all(i["resolved"] for i in new))

    def test_recrawl_is_idempotent_no_duplicates(self):
        jid = self.make_job()
        crawler.run_job(self.db, jid, True)
        crawler.run_job(self.db, jid, True)
        self.assertEqual(len(self.rows("SELECT * FROM indexed_page")), 3)
        self.assertEqual(len(self.issues("outdated_cache")), 0)

    def test_stored_fields_populated(self):
        crawler.run_job(self.db, self.make_job(), True)
        p = self.page("a")
        self.assertEqual(p["title"], "Page A")
        self.assertEqual(p["http_status"], 200)
        self.assertEqual(len(p["content_hash"]), 64)
        self.assertTrue(p["last_modified"])
        self.assertGreater(p["latency_ms"], 0)

    def test_stop_job(self):
        jid = self.make_job(depth=2)
        self.site.delay["a"] = 0.5
        import threading
        t = crawler.start_job_async(self.db, jid)
        time.sleep(0.2)
        crawler.stop_job(jid)
        t.join(5)
        self.assertEqual(self.rows("SELECT status FROM crawl_job WHERE job_id=?", jid)[0]["status"], "stopped")

    def test_unreachable_seed_does_not_crash(self):
        jid = self.make_job("http://127.0.0.1:9/nothing")
        stats = crawler.run_job(self.db, jid, True)
        self.assertEqual(stats["failed"], 1)
        self.assertEqual(self.rows("SELECT status FROM crawl_job WHERE job_id=?", jid)[0]["status"], "done")

    def test_unknown_job(self):
        self.assertIn("error", crawler.run_job(self.db, 9999, True))


class TestVerification(SiteTestCase):
    def setUp(self):
        super().setUp()
        self.t0 = time.time() - 1000
        self.site.put("", "Home", "welcome", links=["/a"], when=self.t0)
        self.site.put("a", "Page A", "price 100", when=self.t0)
        crawler.run_job(self.db, self.make_job(), True)
        self.pid = self.page("a")["page_id"]

    def test_unchanged_page_returns_304_path(self):
        self.assertEqual(crawler.verify_page(self.db, self.pid), "unchanged")
        self.assertEqual(self.issues("outdated_cache"), [])

    def test_changed_page_detected_and_reindexed(self):
        old_hash = self.page("a")["content_hash"]
        self.site.put("a", "Page A", "price 120", when=time.time())
        self.assertEqual(crawler.verify_page(self.db, self.pid), "updated")
        p = self.page("a")
        self.assertNotEqual(p["content_hash"], old_hash)
        self.assertIn("price 120", p["body_text"])
        issue = self.issues("outdated_cache")[0]
        self.assertEqual((issue["resolved"], issue["resolution"]), (1, "auto_reindexed"))

    def test_change_with_unchanged_timestamp_caught_by_hash(self):
        """Server that forgets to bump Last-Modified: the content hash still catches the change."""
        self.site.put("a", "Page A", "price 999", when=self.t0)
        self.assertEqual(crawler.verify_page(self.db, self.pid), "unchanged")  # 304: header says no change
        # a server that ignores conditional requests (always sends 200) is verified by hash:
        orig = crawler.fetch
        crawler.fetch = lambda url, if_modified_since=None, etag=None: orig(url)
        try:
            self.assertEqual(crawler.verify_page(self.db, self.pid), "updated")
        finally:
            crawler.fetch = orig

    def test_whitespace_only_change_is_not_a_discrepancy(self):
        self.site.put("a", "Page A", "price    100", when=time.time())
        self.assertEqual(crawler.verify_page(self.db, self.pid), "unchanged")
        self.assertEqual(self.issues("outdated_cache"), [])

    def test_deleted_page_marked_obsolete_and_logged(self):
        self.site.delete("a")
        self.assertEqual(crawler.verify_page(self.db, self.pid), "obsolete")
        self.assertEqual(self.page("a")["index_status"], "obsolete")
        self.assertEqual(len(self.issues("broken_link")), 1)

    def test_purge_obsolete_removes_from_search_and_resolves(self):
        self.site.delete("a")
        crawler.verify_page(self.db, self.pid)
        self.assertEqual(crawler.purge_obsolete(self.db), 1)
        p = self.page("a")
        self.assertEqual(p["index_status"], "removed")
        self.assertIsNone(p["body_text"])
        self.assertEqual(self.issues("broken_link")[0]["resolution"], "de_indexed")

    def test_server_error_keeps_record_flags_pending_update(self):
        orig = crawler.fetch
        crawler.fetch = lambda *a, **k: {"status": 500, "last_modified": None, "etag": None, "body": b"",
                                         "ctype": "", "latency": 1.0, "error": None, "final_url": ""}
        try:
            self.assertEqual(crawler.verify_page(self.db, self.pid), "error")
        finally:
            crawler.fetch = orig
        self.assertEqual(self.page("a")["index_status"], "pending_update")

    def test_network_failure_handled(self):
        self.conn.execute("UPDATE indexed_page SET page_url='http://127.0.0.1:9/x' WHERE page_id=?", (self.pid,))
        self.conn.commit()
        self.assertEqual(crawler.verify_page(self.db, self.pid), "error")

    def test_verify_unknown_page(self):
        with self.assertRaises(KeyError):
            crawler.verify_page(self.db, 424242)

    def test_page_that_returns_after_deletion_is_restored(self):
        self.site.delete("a")
        crawler.verify_page(self.db, self.pid)
        self.site.put("a", "Page A", "back again", when=time.time())
        crawler.verify_page(self.db, self.pid)
        self.assertEqual(self.page("a")["index_status"], "indexed")

    def test_reconcile_end_to_end(self):
        self.site.put("a", "Page A", "changed", when=time.time())
        self.site.put("", "Home", "welcome", when=self.t0)
        out = crawler.reconcile(self.db)
        self.assertEqual(out["updated"], 1)
        self.assertEqual(out["unchanged"], 1)
        self.assertEqual(out["obsolete"], 0)
