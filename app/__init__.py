"""Flask application factory for the Automated Indexing Management & Real-Time Crawling System."""
import os
import secrets
from functools import wraps

from flask import (Flask, abort, flash, jsonify, redirect, render_template, request,
                   session, url_for, Response)

from . import auth, crawler, reports
from .db import connect, init_db, now


def create_app(config=None):
    app = Flask(__name__)
    app.config.update(
        DB_PATH=os.environ.get("SK_DB", "searchkenya.db"),
        SECRET_KEY=os.environ.get("SK_SECRET") or secrets.token_hex(32),
        ALLOW_PRIVATE_HOSTS=os.environ.get("SK_ALLOW_PRIVATE", "0") == "1",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        RUN_JOBS_ASYNC=True,
        SCHEDULER_INTERVAL=0,          # seconds; 0 disables the background re-verification loop
    )
    if config:
        app.config.update(config)
    init_db(app.config["DB_PATH"])

    if app.config["SCHEDULER_INTERVAL"] and not app.config.get("TESTING"):
        crawler.Scheduler(app.config["DB_PATH"], app.config["SCHEDULER_INTERVAL"]).start()

    def db():
        return connect(app.config["DB_PATH"])

    # ---------- security helpers ----------
    def csrf_token():
        if "_csrf" not in session:
            session["_csrf"] = secrets.token_hex(16)
        return session["_csrf"]

    app.jinja_env.globals["csrf_token"] = csrf_token

    @app.before_request
    def csrf_protect():
        if request.method == "POST" and not app.config.get("WTF_CSRF_DISABLED"):
            sent = request.form.get("_csrf", "")
            if not sent or not secrets.compare_digest(sent, session.get("_csrf", "")):
                abort(400, "Invalid or missing CSRF token")

    @app.after_request
    def headers(resp):
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self'; script-src 'self'"
        return resp

    def login_required(f):
        @wraps(f)
        def wrapper(*a, **kw):
            if "user_id" not in session:
                return redirect(url_for("login"))
            return f(*a, **kw)
        return wrapper

    # ---------- authentication (Figure 2.3.1) ----------
    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            conn = db()
            user, err = auth.login(conn, request.form.get("username", "").strip(),
                                   request.form.get("password", ""))
            conn.close()
            if user:
                session.clear()
                session["user_id"], session["username"] = user["user_id"], user["username"]
                return redirect(url_for("dashboard"))
            flash(err, "error")
        return render_template("login.html")

    @app.route("/logout", methods=["POST"])
    def logout():
        session.clear()
        return redirect(url_for("login"))

    # ---------- dashboard (Figure 2.2.2) ----------
    @app.route("/")
    @login_required
    def dashboard():
        conn = db()
        s = reports.stats(conn)
        logs = conn.execute("""SELECT d.*, p.page_url FROM discrepancy_log d
                               JOIN indexed_page p ON p.page_id=d.page_id
                               ORDER BY d.log_id DESC LIMIT 25""").fetchall()
        conn.close()
        return render_template("dashboard.html", s=s, logs=logs)

    @app.route("/api/stats")
    @login_required
    def api_stats():
        conn = db()
        s = reports.stats(conn)
        conn.close()
        return jsonify(s)

    # ---------- crawl queue & index management (Figure 2.2.1) ----------
    @app.route("/queue")
    @login_required
    def queue():
        conn = db()
        pages = conn.execute("SELECT * FROM indexed_page WHERE index_status!='removed'"
                             " ORDER BY page_id DESC LIMIT 200").fetchall()
        jobs = conn.execute("SELECT * FROM crawl_job ORDER BY job_id DESC LIMIT 20").fetchall()
        conn.close()
        return render_template("queue.html", pages=pages, jobs=jobs)

    @app.route("/queue/add", methods=["POST"])
    @login_required
    def add_seed():
        try:
            url = crawler.validate_url(request.form.get("seed_url"), app.config["ALLOW_PRIVATE_HOSTS"])
            depth = int(request.form.get("crawl_depth", 1))
            if not 0 <= depth <= 3:
                raise ValueError("Crawl depth must be between 0 and 3")
        except (crawler.InvalidURL, ValueError) as e:
            flash(str(e), "error")
            return redirect(url_for("queue"))
        conn = db()
        cur = conn.execute("INSERT INTO crawl_job(user_id,seed_url,crawl_depth,scheduled_at,status)"
                           " VALUES(?,?,?,?,'pending')", (session["user_id"], url, depth, now()))
        conn.commit()
        job_id = cur.lastrowid
        conn.close()
        if app.config["RUN_JOBS_ASYNC"]:
            crawler.start_job_async(app.config["DB_PATH"], job_id)
        flash(f"Seed URL queued (job #{job_id})", "ok")
        return redirect(url_for("queue"))

    @app.route("/jobs/<int:job_id>/run", methods=["POST"])
    @login_required
    def run_job(job_id):
        crawler.run_job(app.config["DB_PATH"], job_id, app.config["ALLOW_PRIVATE_HOSTS"])
        return redirect(url_for("queue"))

    @app.route("/jobs/<int:job_id>/stop", methods=["POST"])
    @login_required
    def stop_job(job_id):
        crawler.stop_job(job_id)
        flash(f"Stop requested for job #{job_id}", "ok")
        return redirect(url_for("queue"))

    @app.route("/pages/<int:page_id>/recrawl", methods=["POST"])
    @login_required
    def recrawl(page_id):
        try:
            result = crawler.verify_page(app.config["DB_PATH"], page_id)
        except KeyError:
            abort(404)
        flash(f"Page #{page_id} re-verified: {result}", "ok")
        return redirect(url_for("queue"))

    @app.route("/pages/<int:page_id>/remove", methods=["POST"])
    @login_required
    def remove_page(page_id):
        conn = db()
        if not conn.execute("SELECT 1 FROM indexed_page WHERE page_id=?", (page_id,)).fetchone():
            conn.close()
            abort(404)
        conn.execute("UPDATE indexed_page SET index_status='removed', body_text=NULL WHERE page_id=?", (page_id,))
        conn.execute("UPDATE discrepancy_log SET resolved=1, resolution='de_indexed'"
                     " WHERE page_id=? AND resolved=0", (page_id,))
        conn.commit()
        conn.close()
        flash(f"Page #{page_id} removed from the index", "ok")
        return redirect(url_for("queue"))

    @app.route("/reconcile", methods=["POST"])
    @login_required
    def reconcile():
        out = crawler.reconcile(app.config["DB_PATH"])
        flash("Reconciliation finished: " + ", ".join(f"{k} {v}" for k, v in out.items()), "ok")
        return redirect(url_for("dashboard"))

    # ---------- analytics & audit report (Figure 2.2.3) ----------
    @app.route("/report")
    @login_required
    def report():
        conn = db()
        s = reports.generate_report(conn)
        conn.close()
        return render_template("report.html", s=s)

    @app.route("/export/csv")
    @login_required
    def export_csv():
        conn = db()
        data = reports.export_csv(conn)
        conn.close()
        return Response(data, mimetype="text/csv",
                        headers={"Content-Disposition": "attachment; filename=discrepancy_log.csv"})

    @app.route("/export/pdf")
    @login_required
    def export_pdf():
        conn = db()
        data = reports.export_pdf(conn)
        conn.close()
        return Response(data, mimetype="application/pdf",
                        headers={"Content-Disposition": "attachment; filename=audit_report.pdf"})

    # ---------- search over the index (demonstrates accuracy of results) ----------
    @app.route("/search")
    @login_required
    def search():
        q = request.args.get("q", "").strip()
        results = []
        if q:
            conn = db()
            esc = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")   # treat % and _ literally
            like = f"%{esc}%"
            results = conn.execute("""SELECT page_url,title,last_crawled FROM indexed_page
                                      WHERE index_status='indexed'
                                        AND (title LIKE ? ESCAPE '\\' OR body_text LIKE ? ESCAPE '\\')
                                      LIMIT 50""", (like, like)).fetchall()
            conn.close()
        return render_template("search.html", q=q, results=results)

    return app
