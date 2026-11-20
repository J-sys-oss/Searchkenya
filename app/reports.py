"""SystemReport class: generateReport(), exportCSV(), exportPDF()."""
import csv
import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

from .db import now

CATEGORY_LABELS = {"outdated_cache": "Outdated Cached Pages",
                   "unindexed_new": "Unindexed New URLs",
                   "broken_link": "Broken Links (404)"}


def stats(conn):
    q = lambda sql, *a: conn.execute(sql, a).fetchone()[0]
    total = q("SELECT COUNT(*) FROM indexed_page WHERE last_crawled IS NOT NULL")
    pending = q("SELECT COUNT(*) FROM indexed_page WHERE index_status IN ('pending','pending_update')") \
        + q("SELECT COUNT(*) FROM crawl_job WHERE status='pending'")
    open_disc = q("SELECT COUNT(*) FROM discrepancy_log WHERE resolved=0")
    all_disc = q("SELECT COUNT(*) FROM discrepancy_log")
    live = q("SELECT COUNT(*) FROM indexed_page WHERE index_status!='removed'")
    clean = q("SELECT COUNT(*) FROM indexed_page WHERE index_status='indexed'")
    # Freshness index accuracy = share of non-removed records whose index copy is verified current.
    freshness = round(100.0 * clean / live, 1) if live else 100.0
    avg_lat = conn.execute("SELECT AVG(latency_ms) FROM indexed_page WHERE latency_ms IS NOT NULL").fetchone()[0]
    cats = {k: q("SELECT COUNT(*) FROM discrepancy_log WHERE issue_type=?", k) for k in CATEGORY_LABELS}
    cat_total = sum(cats.values())
    breakdown = [{"key": k, "label": CATEGORY_LABELS[k], "count": v,
                  "pct": round(100.0 * v / cat_total) if cat_total else 0} for k, v in cats.items()]
    breakdown.sort(key=lambda c: -c["count"])
    return {"total_crawled": total, "pending": pending, "open_discrepancies": open_disc,
            "all_discrepancies": all_disc, "freshness": freshness,
            "avg_latency_ms": round(avg_lat or 0, 1), "categories": breakdown}


def generate_report(conn):
    s = stats(conn)
    conn.execute("INSERT INTO system_report(created_at,discrepancy_count,freshness_score) VALUES(?,?,?)",
                 (now(), s["all_discrepancies"], s["freshness"]))
    conn.commit()
    return s


def _csv_safe(v):
    """Neutralise spreadsheet formula injection (cells starting with = + - @)."""
    v = "" if v is None else str(v)
    return "'" + v if v[:1] in ("=", "+", "-", "@") else v


def export_csv(conn):
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["log_id", "detected_at", "page_url", "issue_type", "detail", "resolved", "resolution"])
    for r in conn.execute("""SELECT d.*, p.page_url FROM discrepancy_log d
                             JOIN indexed_page p ON p.page_id=d.page_id ORDER BY d.log_id"""):
        w.writerow([r["log_id"], r["detected_at"], _csv_safe(r["page_url"]), r["issue_type"],
                    _csv_safe(r["detail"]), "yes" if r["resolved"] else "no", r["resolution"] or ""])
    return out.getvalue()


def export_pdf(conn):
    s = stats(conn)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, title="System Analytics & Audit Report")
    st = getSampleStyleSheet()
    els = [Paragraph("SearchKenya Ltd - Crawl Efficiency Report", st["Title"]),
           Paragraph(f"Generated: {now()} UTC", st["Normal"]), Spacer(1, 14)]
    kv = [["Total pages crawled", s["total_crawled"]], ["Pending queue", s["pending"]],
          ["Open discrepancies", s["open_discrepancies"]],
          ["Total discrepancies logged", s["all_discrepancies"]],
          ["Average crawl latency", f"{s['avg_latency_ms']} ms"],
          ["Freshness index accuracy", f"{s['freshness']}%"]]
    t = Table(kv, colWidths=[260, 180])
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                           ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#E1E8F2"))]))
    els += [t, Spacer(1, 16), Paragraph("Top Discrepancy Categories", st["Heading2"])]
    rows = [["Category", "Count", "Share"]] + [[c["label"], c["count"], f"{c['pct']}%"] for c in s["categories"]]
    t2 = Table(rows, colWidths=[260, 90, 90])
    t2.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F3A5F")),
                            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white)]))
    els.append(t2)
    doc.build(els)
    return buf.getvalue()
