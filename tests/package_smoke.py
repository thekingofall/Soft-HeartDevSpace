"""Launch a built executable with an isolated home and check its bundled assets."""
import argparse
import http.client
import json
from pathlib import Path
import subprocess
import time
from urllib.parse import urlsplit, parse_qs


def main(executable, home):
    if home.exists():
        raise ValueError("Use a new disposable home directory.")
    args = [str(executable), "--no-browser", "--home", str(home)]
    process = subprocess.Popen(args, creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        end = time.monotonic() + 30
        record_path = home / "dashboard.json"
        while not record_path.exists() and time.monotonic() < end:
            if process.poll() is not None:
                raise AssertionError("Packaged application exited during startup.")
            time.sleep(.25)
        record = json.loads(record_path.read_text())
        url = urlsplit(record["url"])
        key = parse_qs(url.query)["key"][0]

        def request(path, post=False):
            connection = http.client.HTTPConnection("127.0.0.1", url.port, timeout=5)
            headers = {"Cookie": f"heartdevspace_{url.port}={key}", "X-Heart-Session": key,
                       "Origin": f"http://127.0.0.1:{url.port}", "Content-Type": "application/json"}
            connection.request("POST" if post else "GET", path, "{}" if post else None, headers)
            response = connection.getresponse()
            result = response.status, response.read()
            connection.close()
            return result

        for path in ("/", "/app.js", "/app.css", "/logo.svg", "/api/state"):
            code, content = request(path)
            assert code == 200 and content, path
        assert (home / "runtime/watch.ps1").is_file()
        assert (home / "runtime/control.ps1").is_file()
        second = subprocess.run(args, creationflags=subprocess.CREATE_NO_WINDOW, timeout=15)
        assert second.returncode == 0
        assert json.loads(record_path.read_text())["pid"] == process.pid
        assert request("/api/quit", post=True)[0] == 200
        assert process.wait(timeout=10) == 0
        print("PASS: packaged launch, HTTP assets, deployed workers, single-instance reuse, clean quit")
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", type=Path, required=True)
    parser.add_argument("--home", type=Path, required=True)
    arguments = parser.parse_args()
    main(arguments.exe.resolve(), arguments.home.resolve())
