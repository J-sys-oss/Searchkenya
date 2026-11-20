"""Unit tests: URL validation, hashing, HTML parsing, authentication, CSV safety."""
import unittest
from app import crawler, auth, reports
from tests.base import SiteTestCase, PASSWORD


class TestURLValidation(unittest.TestCase):
    def test_valid_http_and_https(self):
        self.assertEqual(crawler.validate_url("https://example.co.ke/a", True), "https://example.co.ke/a")
        self.assertEqual(crawler.validate_url("http://127.0.0.1:8000/x", True), "http://127.0.0.1:8000/x")

    def test_fragment_removed(self):
        self.assertEqual(crawler.validate_url("http://127.0.0.1/a#top", True), "http://127.0.0.1/a")

    def test_rejects_bad_scheme(self):
        for bad in ["ftp://x.com", "file:///etc/passwd", "javascript:alert(1)", "example.co.ke", ""]:
            with self.assertRaises(crawler.InvalidURL, msg=bad):
                crawler.validate_url(bad, True)

    def test_rejects_none_and_overlong(self):
        with self.assertRaises(crawler.InvalidURL):
            crawler.validate_url(None, True)
        with self.assertRaises(crawler.InvalidURL):
            crawler.validate_url("http://a.com/" + "x" * 3000, True)

    def test_blocks_private_hosts_by_default(self):
        for bad in ["http://127.0.0.1/", "http://localhost/", "http://10.0.0.5/", "http://169.254.169.254/"]:
            with self.assertRaises(crawler.InvalidURL, msg=bad):
                crawler.validate_url(bad, allow_private=False)


class TestHashAndParse(unittest.TestCase):
    def test_hash_ignores_whitespace(self):
        self.assertEqual(crawler.content_hash("a  b\n c"), crawler.content_hash("a b c"))

    def test_hash_detects_change(self):
        self.assertNotEqual(crawler.content_hash("price 100"), crawler.content_hash("price 120"))

    def test_hash_handles_empty(self):
        self.assertEqual(len(crawler.content_hash("")), 64)
        self.assertEqual(len(crawler.content_hash(None)), 64)

    def test_parse_title_text_links(self):
        html = ('<html><head><title> My Shop </title><script>var x=1;</script></head><body>'
                '<p>Hello</p><a href="/p/1#frag">one</a><a href="https://other.com/z">two</a>'
                '<a href="mailto:a@b.com">mail</a></body></html>')
        title, text, links = crawler.parse_html(html, "http://site.co.ke/index")
        self.assertEqual(title, "My Shop")
        self.assertIn("Hello", text)
        self.assertNotIn("var x", text)
        self.assertEqual(links, ["http://site.co.ke/p/1", "https://other.com/z"])

    def test_parse_malformed_html_does_not_crash(self):
        title, text, links = crawler.parse_html("<html><b>unclosed <a href='/x'>", "http://s.com/")
        self.assertEqual(links, ["http://s.com/x"])


class TestAuth(SiteTestCase):
    def test_password_is_hashed(self):
        stored = self.rows("SELECT password FROM user")[0]["password"]
        self.assertNotIn(PASSWORD, stored)
        self.assertTrue(stored.startswith(("scrypt:", "pbkdf2:")))

    def test_short_password_rejected(self):
        with self.assertRaises(ValueError):
            auth.create_user(self.conn, "bob", "short")

    def test_duplicate_username_rejected(self):
        import sqlite3
        with self.assertRaises(sqlite3.IntegrityError):
            auth.create_user(self.conn, "admin", "another-pass1")

    def test_login_success(self):
        user, err = auth.login(self.conn, "admin", PASSWORD)
        self.assertIsNone(err)
        self.assertEqual(user["username"], "admin")

    def test_login_wrong_password_and_unknown_user_same_message(self):
        _, e1 = auth.login(self.conn, "admin", "wrong")
        _, e2 = auth.login(self.conn, "ghost", "wrong")
        self.assertEqual(e1, e2)

    def test_lockout_after_five_failures(self):
        for _ in range(5):
            auth.login(self.conn, "admin", "bad")
        user, err = auth.login(self.conn, "admin", PASSWORD)   # correct password, but locked
        self.assertIsNone(user)
        self.assertIn("locked", err.lower())

    def test_success_resets_failure_counter(self):
        for _ in range(3):
            auth.login(self.conn, "admin", "bad")
        auth.login(self.conn, "admin", PASSWORD)
        self.assertEqual(self.rows("SELECT failed_logins FROM user")[0]["failed_logins"], 0)

    def test_sql_injection_username_fails_safely(self):
        user, _ = auth.login(self.conn, "admin' OR '1'='1", "x")
        self.assertIsNone(user)


class TestCSVSafety(unittest.TestCase):
    def test_formula_prefix_neutralised(self):
        for v in ["=1+1", "+cmd", "-2", "@SUM(A1)"]:
            self.assertTrue(reports._csv_safe(v).startswith("'"))
        self.assertEqual(reports._csv_safe("normal"), "normal")
        self.assertEqual(reports._csv_safe(None), "")


if __name__ == "__main__":
    unittest.main()
