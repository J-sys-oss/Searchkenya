"""Crawling, timestamp verification and indexing engine.

Maps to the design models:
  * CrawlJob.startCrawl()/stopCrawl()        -> run_job(), stop flag
  * IndexedPage.verifyTimestamp()            -> verify_page()
  * IndexedPage.updateIndex()                -> _upsert_page()
  * IndexedPage.purgeObsolete()              -> purge_obsolete()
"""
import hashlib
import ipaddress
import socket
import threading
import time
from collections import deque
from urllib.parse import urljoin, urlparse, urldefrag

import requests
from bs4 import BeautifulSoup

from .db import connect, now

USER_AGENT = "SearchKenyaBot/1.0 (+indexing-management)"
TIMEOUT = 8
MAX_BYTES = 2_000_000
MAX_PAGES_PER_JOB = 200

_stop_flags = {}          # job_id -> threading.Event


class InvalidURL(ValueError):
    pass


def validate_url(url, allow_private=False):
    """Accept only well-formed http(s) URLs; optionally block private/loopback
    targets so the crawler cannot be abused to probe internal services (SSRF)."""
    url = (url or "").strip()
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise InvalidURL("URL must start with http:// or https:// and contain a host")
    if len(url) > 2048:
        raise InvalidURL("URL too long")
    if not allow_private:
        try:
            for info in socket.getaddrinfo(p.hostname, None):
                ip = ipaddress.ip_address(info[4][0])
                if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                    raise InvalidURL("Private or internal addresses are not allowed")
        except socket.gaierror:
            raise InvalidURL("Host name could not be resolved")
    return urldefrag(url)[0]


def content_hash(text):
    """Normalise whitespace then SHA-256, so cosmetic spacing changes do not count."""
    norm = " ".join((text or "").split())
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


def parse_html(raw, base_url):
    soup = BeautifulSoup(raw, "html.parser")
    for t in soup(["script", "style", "noscript"]):
        t.decompose()
    title = (soup.title.string.strip() if soup.title and soup.title.string else "")
    text = soup.get_text(" ", strip=True)
    links = []
    for a in soup.find_all("a", href=True):
        href = urldefrag(urljoin(base_url, a["href"]))[0]
        if urlparse(href).scheme in ("http", "https"):
            links.append(href)
    return title, text, links


def fetch(url, if_modified_since=None, etag=None):
    """GET with conditional headers. Returns dict with status, headers, body, latency."""
    headers = {"User-Agent": USER_AGENT}
    if if_modified_since:
        headers["If-Modified-Since"] = if_modified_since
    if etag:
        headers["If-None-Match"] = etag
    start = time.perf_counter()
    try:
        r = requests.get(url, headers=headers, timeout=TIMEOUT, stream=True, allow_redirects=True)
        body = r.raw.read(MAX_BYTES, decode_content=True)
        latency = (time.perf_counter() - start) * 1000
        ctype = r.headers.get("Content-Type", "")
        return {"status": r.status_code, "last_modified": r.headers.get("Last-Modified"),
                "etag": r.headers.get("ETag"), "body": body, "ctype": ctype,
                "latency": latency, "error": None, "final_url": r.url}
    except requests.RequestException as e:
        return {"status": 0, "last_modified": None, "etag": None, "body": b"", "ctype": "",
                "latency": (time.perf_counter() - start) * 1000, "error": str(e), "final_url": url}


def _log(conn, page_id, issue, detail, resolved=False, resolution=None):
    conn.execute("INSERT INTO discrepancy_log(page_id,issue_type,detail,detected_at,resolved,resolution)"
                 " VALUES(?,?,?,?,?,?)", (page_id, issue, detail, now(), int(resolved), resolution))


def _recover(conn, page_id):
    """A page that failed verification earlier has now been fetched successfully: close its open entries."""
    conn.execute("UPDATE discrepancy_log SET resolved=1, resolution='recovered'"
                 " WHERE page_id=? AND resolved=0 AND issue_type='outdated_cache'", (page_id,))


def _decode(res):
    try:
        return res["body"].decode("utf-8", errors="replace")
    except Exception:
        return ""


def _upsert_page(conn, job_id, url, res, title, text):
    """updateIndex(): create or refresh the index record for a URL."""
    row = conn.execute("SELECT page_id FROM indexed_page WHERE page_url=?", (url,)).fetchone()
    h = content_hash(text)
    if row:
        conn.execute("""UPDATE indexed_page SET job_id=COALESCE(?,job_id), title=?, content_hash=?,
                        last_modified=?, http_status=?, index_status='indexed', last_crawled=?,
                        latency_ms=?, body_text=? WHERE page_id=?""",
                     (job_id, title, h, res["last_modified"], res["status"], now(),
                      res["latency"], text[:20000], row["page_id"]))
        return row["page_id"]
    cur = conn.execute("""INSERT INTO indexed_page(job_id,page_url,title,content_hash,last_modified,
                          http_status,index_status,last_crawled,latency_ms,body_text)
                          VALUES(?,?,?,?,?,?,'indexed',?,?,?)""",
                       (job_id, url, title, h, res["last_modified"], res["status"], now(),
                        res["latency"], text[:20000]))
    return cur.lastrowid


def verify_page(db_path, page_id):
    """verifyTimestamp(): re-check one indexed page against the live site.

    Strategy (Section 2.3.2 flowchart): conditional GET using If-Modified-Since.
      304 -> unchanged, only refresh last_crawled
      200 -> compare SHA-256 content hash; differs => outdated cache => auto re-index
      404/410 -> broken link => mark obsolete and log
      other / network error -> keep record, flag pending_update, log
    Returns one of: 'unchanged', 'updated', 'obsolete', 'error'.
    """
    conn = connect(db_path)
    try:
        p = conn.execute("SELECT * FROM indexed_page WHERE page_id=?", (page_id,)).fetchone()
        if p is None:
            raise KeyError(page_id)
        res = fetch(p["page_url"], if_modified_since=p["last_modified"])
        st = res["status"]
        if st == 304:
            conn.execute("UPDATE indexed_page SET last_crawled=?, latency_ms=?, http_status=200,"
                         " index_status='indexed' WHERE page_id=?", (now(), res["latency"], page_id))
            _recover(conn, page_id)
            conn.commit()
            return "unchanged"
        if st in (404, 410):
            already = p["index_status"] in ("obsolete", "removed")     # log the failure once, not on every re-check
            conn.execute("UPDATE indexed_page SET http_status=?, last_crawled=?, latency_ms=?,"
                         " index_status=? WHERE page_id=?",
                         (st, now(), res["latency"], "removed" if p["index_status"] == "removed" else "obsolete", page_id))
            if not already:
                _log(conn, page_id, "broken_link", f"HTTP {st} returned for indexed URL")
            conn.commit()
            return "obsolete"
        if st != 200:
            already = p["index_status"] == "pending_update"          # log the failure once, not on every re-check
            conn.execute("UPDATE indexed_page SET http_status=?, last_crawled=?, index_status='pending_update'"
                         " WHERE page_id=?", (st, now(), page_id))
            if not already:
                _log(conn, page_id, "outdated_cache",
                     f"Could not verify page (status {st or 'network error'}): {res['error'] or ''}")
            conn.commit()
            return "error"
        title, text, _ = parse_html(_decode(res), p["page_url"])
        if content_hash(text) == p["content_hash"]:
            conn.execute("UPDATE indexed_page SET last_crawled=?, latency_ms=?, last_modified=?,"
                         " http_status=200, index_status='indexed' WHERE page_id=?",
                         (now(), res["latency"], res["last_modified"] or p["last_modified"], page_id))
            _recover(conn, page_id)
            conn.commit()
            return "unchanged"
        # content changed -> stale index record detected, resolve automatically
        _log(conn, page_id, "outdated_cache", "Live content differs from indexed copy",
             resolved=True, resolution="auto_reindexed")
        _upsert_page(conn, None, p["page_url"], res, title, text)
        _recover(conn, page_id)
        conn.commit()
        return "updated"
    finally:
        conn.close()


def run_job(db_path, job_id, allow_private=False):
    """startCrawl(): breadth-first crawl of one seed, same host only, up to crawl_depth."""
    conn = connect(db_path)
    stop = _stop_flags.setdefault(job_id, threading.Event())
    stop.clear()
    try:
        job = conn.execute("SELECT * FROM crawl_job WHERE job_id=?", (job_id,)).fetchone()
        if job is None:
            return {"error": "no such job"}
        conn.execute("UPDATE crawl_job SET status='running' WHERE job_id=?", (job_id,))
        conn.commit()
        seed = job["seed_url"]
        host = urlparse(seed).netloc
        queue = deque([(seed, 0)])
        seen = {seed}
        stats = {"crawled": 0, "new": 0, "updated": 0, "failed": 0}
        while queue and not stop.is_set() and stats["crawled"] < MAX_PAGES_PER_JOB:
            url, depth = queue.popleft()
            existing = conn.execute("SELECT * FROM indexed_page WHERE page_url=?", (url,)).fetchone()
            res = fetch(url)
            stats["crawled"] += 1
            if res["status"] != 200 or (res["ctype"] and "html" not in res["ctype"].lower()):
                stats["failed"] += 1
                if existing is None:
                    cur = conn.execute("INSERT INTO indexed_page(job_id,page_url,http_status,index_status,"
                                       "last_crawled,latency_ms) VALUES(?,?,?,?,?,?)",
                                       (job_id, url, res["status"],
                                        "obsolete" if res["status"] in (404, 410) else "pending",
                                        now(), res["latency"]))
                    pid = cur.lastrowid
                else:
                    pid = existing["page_id"]
                    conn.execute("UPDATE indexed_page SET http_status=?, last_crawled=?, index_status=?"
                                 " WHERE page_id=?", (res["status"], now(),
                                 "obsolete" if res["status"] in (404, 410) else "pending_update", pid))
                if res["status"] in (404, 410) and (existing is None or existing["index_status"] not in ("obsolete", "removed")):
                    _log(conn, pid, "broken_link", f"HTTP {res['status']} found while crawling")
                conn.commit()
                continue
            title, text, links = parse_html(_decode(res), url)
            if existing is None:
                pid = _upsert_page(conn, job_id, url, res, title, text)
                _log(conn, pid, "unindexed_new", "URL was missing from the index", True, "indexed_by_crawl")
                stats["new"] += 1
            elif existing["content_hash"] != content_hash(text):
                pid = _upsert_page(conn, job_id, url, res, title, text)
                _log(conn, pid, "outdated_cache", "Indexed copy differed from live page",
                     True, "auto_reindexed")
                stats["updated"] += 1
            else:
                _upsert_page(conn, job_id, url, res, title, text)
            conn.commit()
            if depth < job["crawl_depth"]:
                for link in links:
                    if urlparse(link).netloc == host and link not in seen:
                        seen.add(link)
                        queue.append((link, depth + 1))
        status = "stopped" if stop.is_set() else "done"
        conn.execute("UPDATE crawl_job SET status=? WHERE job_id=?", (status, job_id))
        conn.commit()
        return stats
    except Exception as e:  # never leave a job stuck in 'running'
        conn.execute("UPDATE crawl_job SET status='failed' WHERE job_id=?", (job_id,))
        conn.commit()
        return {"error": str(e)}
    finally:
        conn.close()


def stop_job(job_id):
    """stopCrawl()"""
    _stop_flags.setdefault(job_id, threading.Event()).set()


def start_job_async(db_path, job_id):
    t = threading.Thread(target=run_job, args=(db_path, job_id), daemon=True)
    t.start()
    return t


def purge_obsolete(db_path):
    """purgeObsolete(): remove obsolete pages from the searchable index (keeps the audit log)."""
    conn = connect(db_path)
    try:
        rows = conn.execute("SELECT page_id FROM indexed_page WHERE index_status='obsolete'").fetchall()
        for r in rows:
            conn.execute("UPDATE indexed_page SET index_status='removed', body_text=NULL WHERE page_id=?",
                         (r["page_id"],))
            conn.execute("UPDATE discrepancy_log SET resolved=1, resolution='de_indexed'"
                         " WHERE page_id=? AND resolved=0", (r["page_id"],))
        conn.commit()
        return len(rows)
    finally:
        conn.close()


def reconcile(db_path):
    """Reconciliation pass: re-verify every page that is not clean, then purge obsolete ones."""
    conn = connect(db_path)
    ids = [r["page_id"] for r in conn.execute(
        "SELECT page_id FROM indexed_page WHERE index_status IN ('pending','pending_update','indexed')")]
    conn.close()
    out = {"unchanged": 0, "updated": 0, "obsolete": 0, "error": 0}
    for pid in ids:
        out[verify_page(db_path, pid)] += 1
    out["purged"] = purge_obsolete(db_path)
    return out


class Scheduler(threading.Thread):
    """Real-time behaviour: periodically re-verifies indexed pages in the background."""

    def __init__(self, db_path, interval=60):
        super().__init__(daemon=True)
        self.db_path, self.interval = db_path, interval
        self._stop_evt = threading.Event()

    def run(self):
        while not self._stop_evt.wait(self.interval):
            try:
                reconcile(self.db_path)
            except Exception:
                pass

    def stop(self):
        self._stop_evt.set()
