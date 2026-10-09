"""Minimal stdlib HTTP server for the click-counter demo."""
import html
import sqlite3
from contextlib import closing
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

PAGE_TEMPLATE = """\
<!doctype html>
<html>
<head><title>Click Counter</title></head>
<body>
<h1>Clicks: {count}</h1>
<form method="POST" action="/click">
  <button type="submit">Click me</button>
</form>
<p id="update-status"></p>
<table border="1" cellpadding="4">
  <tr><th>ID</th><th>Clicked At</th></tr>
  {rows}
</table>
</body>
</html>
"""


class CounterServer(HTTPServer):
    def __init__(self, server_address, handler_cls, db_path):
        super().__init__(server_address, handler_cls)
        self.db_path = db_path


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/":
            self.send_response(404)
            self.end_headers()
            return

        with closing(sqlite3.connect(self.server.db_path)) as conn:
            (count,) = conn.execute("SELECT COUNT(*) FROM clicks").fetchone()
            rows = conn.execute(
                "SELECT id, clicked_at FROM clicks ORDER BY id DESC"
            ).fetchall()

        rows_html = "\n  ".join(
            f"<tr><td>{row_id}</td><td>{html.escape(clicked_at)}</td></tr>"
            for row_id, clicked_at in rows
        )
        body = PAGE_TEMPLATE.format(count=count, rows=rows_html).encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != "/click":
            self.send_response(404)
            self.end_headers()
            return

        with closing(sqlite3.connect(self.server.db_path)) as conn:
            conn.execute(
                "INSERT INTO clicks (clicked_at) VALUES (?)",
                (datetime.now().isoformat(),),
            )
            conn.commit()

        self.send_response(303)
        self.send_header("Location", "/")
        self.end_headers()

    def log_message(self, format, *args):
        pass


def create_server(db_path, port=8765):
    server = CounterServer(("127.0.0.1", port), Handler, db_path)
    print(f"Serving click counter at http://127.0.0.1:{port}/ (db: {db_path})")
    return server


def run_server(db_path, port=8765):
    server = create_server(db_path, port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
