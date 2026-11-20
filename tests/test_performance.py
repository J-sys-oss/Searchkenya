"""Performance and accuracy tests on a 100-page site whose changes are known exactly."""
import time
import unittest

from app import create_app, crawler
from tests.base import SiteTestCase, PASSWORD

N = 100


class TestScale(SiteTestCase):
    def build(self):
        links = [f"/p{i}" for i in range(1, N)]
        self.site.put("", "Home", "directory of pages", links=links, when=time.time() - 1000)
        for i in range(1, N):
            self.site.put(f"p{i}", f"Page {i}", f"original content number {i}", when=time.time() - 1000)

    def initial_crawl(self):
        self.build()
        jid = self.make_job(depth=1)
        t0 = time.perf_counter()
        stats = crawler.run_job(self.db, jid, True)
        return stats, time.perf_counter() - t0

    def test_hundred_page_crawl_completes_quickly(self):
        stats, secs = self.initial_crawl()
        self.assertEqual(stats["new"], N)
        self.assertEqual(self.rows("SELECT COUNT(*) n FROM indexed_page WHERE index_status='indexed'")[0]["n"], N)
        self.assertLess(secs, 60)
        print(f"\n[PERF] initial crawl of {N} pages: {secs:.2f} s ({N/secs:.0f} pages/s)")

    def test_known_changes_detected_exactly(self):
        """20 pages edited, 10 deleted, 5 new pages published and linked from the home page."""
        self.initial_crawl()
        t = time.time()
        for i in range(1, 21):
            self.site.put(f"p{i}", f"Page {i}", f"REVISED content number {i}", when=t)
        for i in range(21, 31):
            self.site.delete(f"p{i}")
        for i in range(N, N + 5):
            self.site.put(f"p{i}", f"Page {i}", f"brand new page {i}", when=t)
        links = [f"/p{i}" for i in range(1, N + 5)]
        self.site.put("", "Home", "directory of pages updated", links=links, when=t)   # home changes too

        stats = crawler.run_job(self.db, self.make_job(depth=1), True)
        # edited pages (20) + the home page (1) = 21 updates; 10 broken; 5 new
        self.assertEqual((stats["updated"], stats["failed"], stats["new"]), (21, 10, 5))
        unchanged_flagged = self.rows("SELECT COUNT(*) n FROM discrepancy_log WHERE issue_type='outdated_cache'")[0]["n"]
        self.assertEqual(unchanged_flagged, 21)            # none of the 69 untouched pages was flagged
        self.assertEqual(self.rows("SELECT COUNT(*) n FROM indexed_page WHERE index_status='indexed'")[0]["n"], 95)
        print(f"\n[ACC] updated={stats['updated']} failed={stats['failed']} new={stats['new']} "
              f"outdated_cache_logs={unchanged_flagged}")

    def test_stale_index_vs_reconciled_index(self):
        """Share of search results that point to stale or dead pages, before and after reconciliation."""
        self.initial_crawl()
        t = time.time()
        for i in range(1, 21):
            self.site.put(f"p{i}", f"Page {i}", f"REVISED content number {i}", when=t)
        for i in range(21, 31):
            self.site.delete(f"p{i}")

        def wrong_results():
            rows = self.rows("SELECT page_url, body_text FROM indexed_page WHERE index_status='indexed'")
            bad = 0
            for r in rows:
                path = r["page_url"].replace(self.site.base, "").lstrip("/")
                live = self.site.pages.get(path)
                if live is None or ("REVISED" in live[0]) != ("REVISED" in (r["body_text"] or "")):
                    bad += 1
            return bad, len(rows)

        bad_before, total_before = wrong_results()
        t0 = time.perf_counter()
        out = crawler.reconcile(self.db)
        secs = time.perf_counter() - t0
        bad_after, total_after = wrong_results()
        self.assertEqual(bad_before, 30)                    # 20 stale + 10 dead
        self.assertEqual(bad_after, 0)
        self.assertEqual((out["updated"], out["obsolete"], out["purged"]), (20, 10, 10))
        print(f"\n[ACC] before reconcile: {bad_before}/{total_before} wrong; after: {bad_after}/{total_after}; "
              f"reconcile took {secs:.2f} s")

    def test_reverification_of_unchanged_site_is_cheap(self):
        self.initial_crawl()
        hits0 = self.site.hits
        t0 = time.perf_counter()
        out = crawler.reconcile(self.db)
        secs = time.perf_counter() - t0
        self.assertEqual(out["unchanged"], N)
        self.assertEqual(self.rows("SELECT COUNT(*) n FROM discrepancy_log WHERE issue_type!='unindexed_new'")[0]["n"], 0)
        print(f"\n[PERF] re-verify {N} unchanged pages: {secs:.2f} s, {self.site.hits-hits0} requests")

    def test_latency_recorded_for_every_page(self):
        self.initial_crawl()
        n = self.rows("SELECT COUNT(*) n FROM indexed_page WHERE latency_ms>0")[0]["n"]
        self.assertEqual(n, N)

    def test_dashboard_and_search_response_time(self):
        self.initial_crawl()
        app = create_app({"DB_PATH": self.db, "TESTING": True, "WTF_CSRF_DISABLED": True})
        c = app.test_client()
        c.post("/login", data={"username": "admin", "password": PASSWORD})
        for url in ("/", "/queue", "/api/stats", "/search?q=content"):
            t0 = time.perf_counter()
            r = c.get(url)
            ms = (time.perf_counter() - t0) * 1000
            self.assertEqual(r.status_code, 200)
            self.assertLess(ms, 1000, url)
            print(f"\n[PERF] GET {url}: {ms:.0f} ms")


if __name__ == "__main__":
    unittest.main()
