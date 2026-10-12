"""A session-protected loopback dashboard; no external web service required."""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import http.client
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import threading
import time
from urllib.parse import parse_qs, urlsplit
import webbrowser

from .core import Manager, PACKAGE, read_json, write_json


class Dashboard(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, manager, port=0):
        self.manager = manager
        self.session = secrets.token_hex(32)
        super().__init__(("127.0.0.1", port), Handler)
        self.origin = f"http://127.0.0.1:{self.server_port}"
        self.cookie_name = f"heartdevspace_{self.server_port}"


class Handler(BaseHTTPRequestHandler):
    server: Dashboard

    def log_message(self, *args):
        # Request URLs can contain the initial session token.
        pass

    def send_data(self, status, data, content_type="application/json", cookie=False):
        raw = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type + "; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'")
        if cookie:
            self.send_header("Set-Cookie", f"{self.server.cookie_name}={self.server.session}; HttpOnly; SameSite=Strict; Path=/")
        self.end_headers()
        try:
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def authorized(self, bootstrap=False):
        if self.headers.get("Host") != self.server.origin.removeprefix("http://"):
            return False
        if bootstrap:
            key = parse_qs(urlsplit(self.path).query).get("key", [""])[0]
            if secrets.compare_digest(key, self.server.session):
                return True
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
            supplied = cookie.get(self.server.cookie_name)
            return supplied is not None and secrets.compare_digest(supplied.value, self.server.session)
        except Exception:
            return False

    def do_GET(self):
        path = urlsplit(self.path).path
        if not self.authorized(bootstrap=path == "/"):
            return self.send_data(403, {"error": "Open Soft-HeartDevSpace on this computer to start a dashboard session."})
        if path == "/api/state":
            return self.send_data(200, self.server.manager.snapshot())
        if path == "/api/logs":
            return self.send_data(200, {"text": self.server.manager.logs()})
        files = {"/": "index.html", "/app.js": "app.js", "/app.css": "app.css", "/logo.svg": "logo.svg"}
        if path not in files:
            return self.send_data(404, {"error": "Not found"})
        data = (PACKAGE / "web" / files[path]).read_bytes()
        content_type = {"/": "text/html", "/app.js": "text/javascript", "/app.css": "text/css", "/logo.svg": "image/svg+xml"}[path]
        if path == "/":
            data = data.replace(b"__SESSION__", self.server.session.encode("ascii"))
        self.send_data(200, data, content_type, cookie=path == "/")

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 65536 or self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                return self.send_data(400, {"error": "Send a JSON request smaller than 64 KiB."})
            # Consume bounded bodies before rejection so Windows can deliver the
            # error response without resetting a socket with unread input.
            self.connection.settimeout(5)
            raw = self.rfile.read(length)
            if not self.authorized() or self.headers.get("Origin") != self.server.origin or not secrets.compare_digest(self.headers.get("X-Heart-Session", ""), self.server.session):
                return self.send_data(403, {"error": "Dashboard session expired. Reopen the application."})
            body = json.loads(raw)
            if not isinstance(body, dict):
                raise ValueError("Expected a JSON object.")
            path = urlsplit(self.path).path
            if path == "/api/settings":
                message = self.server.manager.save(body)
                return self.send_data(200, {"message": message})
            if path == "/api/action":
                self.server.manager.start_job(body.get("action"))
                return self.send_data(202, {"message": "Operation started."})
            if path == "/api/owner-password":
                return self.send_data(200, {"password": self.server.manager.owner_password()})
            if path == "/api/quit":
                if self.server.manager.job["running"]:
                    raise ValueError("Wait for the current operation to finish.")
                self.send_data(200, {"message": "Dashboard closed. Background heartbeat retains its current setting."})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            self.send_data(404, {"error": "Not found"})
        except (ValueError, TypeError, OSError, RuntimeError) as error:
            self.send_data(400, {"error": str(error)[:4000]})


def existing_dashboard(home):
    """Reuse only an authenticated, live loopback dashboard from this home."""
    try:
        record = read_json(home / "dashboard.json", {})
        url = urlsplit(record.get("url", ""))
        key = parse_qs(url.query).get("key", [""])[0]
        if url.scheme != "http" or url.hostname != "127.0.0.1" or not url.port or len(key) != 64:
            return None
        connection = http.client.HTTPConnection("127.0.0.1", url.port, timeout=1)
        try:
            connection.request("GET", "/api/state", headers={"Cookie": f"heartdevspace_{url.port}=" + key})
            response = connection.getresponse()
            state = json.loads(response.read())
            if response.status == 200 and state.get("settings", {}).get("home") == str(home):
                return record["url"]
        finally:
            connection.close()
    except (OSError, ValueError, http.client.HTTPException):
        pass
    return None


def main(argv=None):
    parser = argparse.ArgumentParser(description="Soft-HeartDevSpace local dashboard")
    parser.add_argument("--home", type=Path, default=Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Soft-HeartDevSpace")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)
    args.home = args.home.resolve()
    handle = None
    if os.name == "nt":
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
        kernel.CreateMutexW.restype = ctypes.c_void_p
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        name = "Local\\SoftHeartDashboard-" + hashlib.sha256(str(args.home).lower().encode()).hexdigest()[:24]
        handle = kernel.CreateMutexW(None, False, name)
        if not handle:
            raise OSError("Unable to initialize the control panel.")
        if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
            kernel.CloseHandle(handle)
            for _ in range(10):
                url = existing_dashboard(args.home)
                if url:
                    if not args.no_browser:
                        webbrowser.open(url)
                    return
                time.sleep(0.3)
            raise RuntimeError("The control panel is already starting. Reopen it in a few seconds.")
    try:
        serve(args)
    finally:
        if handle:
            kernel.CloseHandle(handle)


def serve(args):
    manager = Manager(args.home)
    server = Dashboard(manager, args.port)
    url = server.origin + "/?key=" + server.session
    write_json(manager.home / "dashboard.json", {"url": url, "pid": os.getpid()})
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever(poll_interval=0.25)
    finally:
        server.server_close()
        if read_json(manager.home / "dashboard.json", {}).get("pid") == os.getpid():
            (manager.home / "dashboard.json").unlink(missing_ok=True)


if __name__ == "__main__":
    main()
