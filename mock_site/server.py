"""A controllable local website used as the test target for the crawler.

Pages can be added, edited and deleted while the server runs, so tests can
reproduce exactly the failures SearchKenya reported: new pages missing from the
index, edited pages left stale, and deleted pages still indexed.
Honours If-Modified-Since (returns 304) like a well-behaved real web server.
"""
import threading
import time
from email.utils import formatdate, parsedate_to_datetime

from flask import Flask, Response, request
from werkzeug.serving import make_server


class MockSite:
    def __init__(self, port=0):
        self.pages = {}                 # path -> (html, mtime_epoch)
        self.delay = {}                 # path -> artificial latency (seconds)
        self.hits = 0
        self.app = Flask("mock")
        self.app.add_url_rule("/", "serve", self._serve, defaults={"path": ""})
        self.app.add_url_rule("/<path:path>", "serve", self._serve)
        self._srv = make_server("127.0.0.1", port, self.app, threaded=True)
        self.port = self._srv.server_port
        self.base = f"http://127.0.0.1:{self.port}"
        self._t = threading.Thread(target=self._srv.serve_forever, daemon=True)

    # --- lifecycle ---
    def start(self):
        self._t.start()
        return self

    def stop(self):
        self._srv.shutdown()

    # --- content control ---
    def put(self, path, title, body, links=(), when=None):
        """Create or edit a page. `when` lets tests control the modification time."""
        a = "".join(f'<a href="{l}">{l}</a> ' for l in links)
        html = f"<html><head><title>{title}</title></head><body><h1>{title}</h1><p>{body}</p>{a}</body></html>"
        self.pages[path.lstrip("/")] = (html, when if when is not None else time.time())

    def delete(self, path):
        self.pages.pop(path.lstrip("/"), None)

    def url(self, path=""):
        return f"{self.base}/{path.lstrip('/')}"

    # --- request handling ---
    def _serve(self, path):
        self.hits += 1
        if path in self.delay:
            time.sleep(self.delay[path])
        if path not in self.pages:
            return Response("Not found", status=404)
        html, mtime = self.pages[path]
        ims = request.headers.get("If-Modified-Since")
        if ims:
            try:
                if int(mtime) <= int(parsedate_to_datetime(ims).timestamp()):
                    return Response(status=304)
            except (TypeError, ValueError):
                pass
        return Response(html, mimetype="text/html",
                        headers={"Last-Modified": formatdate(mtime, usegmt=True)})
