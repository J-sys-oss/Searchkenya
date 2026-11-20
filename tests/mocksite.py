"""A controllable local website used as ground truth for testing the crawler."""
import hashlib, threading
from email.utils import formatdate
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

class MockSite:
    def __init__(self):
        self.pages, self.mtime = {}, {}
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.port = self.server.server_address[1]
        self.base = f"http://127.0.0.1:{self.port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
    def set(self, path, html, ts=1_700_000_000):
        self.pages[path] = html; self.mtime[path] = ts
    def delete(self, path):
        self.pages.pop(path, None)
    def stop(self):
        self.server.shutdown(); self.server.server_close()
    def _handler(self):
        site = self
        class H(BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def do_GET(self):
                body = site.pages.get(self.path)
                if body is None:
                    self.send_response(404); self.send_header("Content-Length", "0"); self.end_headers(); return
                etag = '"%s"' % hashlib.md5(body.encode()).hexdigest()
                lm = formatdate(site.mtime[self.path], usegmt=True)
                if self.headers.get("If-None-Match") == etag:
                    self.send_response(304); self.end_headers(); return
                data = body.encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html"); self.send_header("ETag", etag)
                self.send_header("Last-Modified", lm); self.send_header("Content-Length", str(len(data)))
                self.end_headers(); self.wfile.write(data)
        return H
def page(title, links=(), extra=""):
    return f"<html><head><title>{title}</title></head><body>{extra}" + "".join(f'<a href="{l}">l</a>' for l in links) + "</body></html>"
