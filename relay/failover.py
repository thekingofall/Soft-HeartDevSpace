"""Select a healthy tunnel for a fixed HTTPS endpoint. Run from a systemd timer."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import time
import urllib.request


def choose(state, health, now):
    current = state.get("active", "cloudflare")
    failures = state.get("failures", 0) + 1 if not health[current] else 0
    primary_passes = state.get("primary_passes", 0) + 1 if health["cloudflare"] else 0
    target = current
    other = "frp" if current == "cloudflare" else "cloudflare"
    if failures >= 2 and health[other]:
        target = other
    elif current == "frp" and primary_passes >= 3 and now - state.get("switched_at", 0) >= 60:
        target = "cloudflare"
    return dict(active=target, failures=0 if target != current else failures,
                primary_passes=primary_passes,
                switched_at=now if target != current else state.get("switched_at", 0))


def probe(url):
    try:
        request = urllib.request.Request(url, headers={"Cache-Control": "no-cache", "User-Agent": "HeartDevSpaceRelay/0.2"})
        with urllib.request.urlopen(request, timeout=4) as response:
            body = json.loads(response.read(4096))
            return response.status == 200 and body.get("ok") is True and body.get("name") == "devspace"
    except Exception:
        return False


def atomic(path, text):
    path = Path(path)
    stage = path.with_suffix(path.suffix + ".new")
    stage.write_text(text, encoding="utf-8")
    os.replace(stage, path)


def switch(config, active):
    route = Path(config["route_file"])
    previous = route.read_text()
    port = int(config["ports"][active])
    if not 1024 <= port <= 65535:
        raise ValueError("Invalid loopback upstream port")
    atomic(route, 'set $heart_backend http://127.0.0.1:%d;\nset $heart_transport %s;\n' % (port, active))
    reload_attempted = False
    try:
        subprocess.run(config["validate_command"], check=True, capture_output=True, timeout=10)
        reload_attempted = True
        subprocess.run(config["reload_command"], check=True, capture_output=True, timeout=10)
    except Exception:
        atomic(route, previous)
        if reload_attempted:
            # A timed-out reload may have applied the route. Reapply the previous one.
            subprocess.run(config["validate_command"], check=True, capture_output=True, timeout=10)
            subprocess.run(config["reload_command"], check=True, capture_output=True, timeout=10)
        raise


def load_state(config):
    path = Path(config["state_file"])
    try:
        state = json.loads(path.read_text()) if path.exists() else {}
    except (ValueError, OSError):
        state = {}
    match = re.search(r'^set \$heart_transport (cloudflare|frp);$', Path(config["route_file"]).read_text(), re.M)
    if not match:
        raise ValueError("Active route file has no recognized transport")
    active = match.group(1)
    if state.get("active") != active:
        # A crash may occur before or after nginx reload. Apply the stored route
        # again so the live worker and the route file agree in either case.
        state = dict(active=active, switched_at=time.time(), reload_required=True)
    return state


def main():
    import fcntl
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text())
    state_path = Path(config["state_file"])
    with open(str(state_path) + ".lock", "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        state = load_state(config)
        if state.pop("reload_required", False):
            switch(config, state["active"])
        with ThreadPoolExecutor(max_workers=2) as pool:
            checks = {name: pool.submit(probe, url) for name, url in config["health_urls"].items()}
            health = {name: job.result() for name, job in checks.items()}
        updated = choose(state, health, time.time())
        if updated["active"] != state.get("active", "cloudflare"):
            switch(config, updated["active"])
        updated.update(health=health, checked_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
        atomic(state_path, json.dumps(updated) + "\n")
        print(json.dumps(updated))


if __name__ == "__main__":
    main()
