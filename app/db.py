"""Database layer: SQLite schema that implements the ERD in Figure 2.5.1.

Tables: USER, CRAWL_JOB, INDEXED_PAGE, DISCREPANCY_LOG (plus SYSTEM_REPORT
from the class diagram so that generated reports are kept for audit).
"""
import sqlite3
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS user (
    user_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    password      TEXT NOT NULL,              -- salted hash, never plain text
    role          TEXT NOT NULL DEFAULT 'admin',
    failed_logins INTEGER NOT NULL DEFAULT 0,
    locked_until  TEXT
);
CREATE TABLE IF NOT EXISTS crawl_job (
    job_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL REFERENCES user(user_id),
    seed_url     TEXT NOT NULL,
    crawl_depth  INTEGER NOT NULL DEFAULT 1,
    scheduled_at TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'pending'   -- pending|running|done|failed|stopped
);
CREATE TABLE IF NOT EXISTS indexed_page (
    page_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id        INTEGER REFERENCES crawl_job(job_id),
    page_url      TEXT NOT NULL UNIQUE,
    title         TEXT,
    content_hash  TEXT,
    last_modified TEXT,
    http_status   INTEGER,
    index_status  TEXT NOT NULL DEFAULT 'pending',  -- pending|indexed|pending_update|obsolete|removed
    last_crawled  TEXT,
    latency_ms    REAL,
    body_text     TEXT
);
CREATE TABLE IF NOT EXISTS discrepancy_log (
    log_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    page_id     INTEGER NOT NULL REFERENCES indexed_page(page_id),
    issue_type  TEXT NOT NULL,      -- outdated_cache|unindexed_new|broken_link
    detail      TEXT,
    detected_at TEXT NOT NULL,
    resolved    INTEGER NOT NULL DEFAULT 0,
    resolution  TEXT
);
CREATE TABLE IF NOT EXISTS system_report (
    report_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at        TEXT NOT NULL,
    discrepancy_count INTEGER NOT NULL,
    freshness_score   REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_page_status ON indexed_page(index_status);
CREATE INDEX IF NOT EXISTS idx_disc_page   ON discrepancy_log(page_id);
"""


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def connect(path):
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(path):
    conn = connect(path)
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()
