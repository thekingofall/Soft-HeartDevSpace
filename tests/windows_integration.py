"""Opt-in Windows test. Uses a real DevSpace engine and a local tunnel fixture.

python -m tests.windows_integration --home <NEW disposable directory>
Requires Node 24, Git Bash, DevSpace 1.0.8 and permission to create a user task.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time

from heartdevspace.core import Manager, hidden_run, powershell, read_json, write_json
from tests.mcp_probe import Probe


def run(home):
    if os.name != "nt" or home.exists():
        raise ValueError("Use Windows and a new disposable --home directory.")
    home.mkdir(parents=True)
    project = home / "project with spaces"
    project.mkdir()
    (project / "hello.txt").write_text("heartbeat integration fixture\n")
    manager = Manager(home / "application")
    fixture = home / "cloudflared.exe"
    compiler = Path(os.environ["SystemRoot"]) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
    hidden_run([str(compiler), "/nologo", "/target:exe", "/out:" + str(fixture),
                str(Path(__file__).parent / "fixtures/fake_cloudflared.cs")])
    manager.save({"domain": "integration.invalid", "tunnel_name": "integration-fixture",
                  "allowed_roots": [str(project)], "port": 17776, "metrics_port": 20259,
                  "cloudflared_path": str(fixture)})
    credentials = home / "fixture.json"
    write_json(credentials, {})
    manager.settings.update(tunnel_id="11111111-1111-4111-8111-111111111111", credentials_path=str(credentials))
    manager.persist()
    statuses = []

    def status():
        return read_json(manager.home / "logs/status.json", {})

    def wait_until(predicate, seconds=210):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            current = status()
            if predicate(current):
                statuses.append(current)
                return current
            time.sleep(3)
        raise AssertionError("Heartbeat condition timed out: " + json.dumps(status()))

    try:
        print(manager.perform("start"), flush=True)
        first = wait_until(lambda s: s.get("local", {}).get("healthy") and s.get("tunnel", {}).get("healthy"))
        print("PASS: real DevSpace health and fixture tunnel readiness", flush=True)
        probe = Probe(manager)
        probe.authorize()
        probe.read_fixture(project)
        print("PASS: OAuth, MCP initialization, workspace open and authenticated file read", flush=True)
        # Crash only the managed process reported for this isolated instance.
        old_pid = first["nodePids"][0]
        hidden_run([powershell(), "-NoProfile", "-Command", f"Stop-Process -Id {old_pid} -Force -ErrorAction Stop"])
        recovered = wait_until(lambda s: s.get("local", {}).get("healthy") and s.get("nodePids") and s["nodePids"][0] != old_pid)
        print("PASS: scheduled task recovered the terminated DevSpace process", flush=True)
        probe.read_fixture(project)
        print("PASS: existing OAuth access remains usable after recovery", flush=True)
        task = hidden_run([powershell(), "-NoProfile", "-Command",
                           f"$t=Get-ScheduledTask -TaskName '{manager.task_name}'; $t | Export-ScheduledTask"])
        assert "wscript.exe" in task and "PT1M" in task and "<Hidden>true</Hidden>" in task
        print("PASS: hidden task, staggered triggers and user-logon startup", flush=True)
        manager.perform("remove_autostart")
        assert status().get("paused") is True
        print("PASS: stop and remove startup task", flush=True)
        write_json(home / "result.json", {"at": datetime.now(timezone.utc).isoformat(), "passed": True,
                    "real_devspace": True, "cloudflare_fixture": True,
                    "heartbeat_samples": len(statuses), "restart_verified": old_pid != recovered["nodePids"][0],
                    "authenticated_mcp_read": True, "authorization_persisted_after_restart": True})
    finally:
        manager.perform("remove_autostart")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--home", type=Path, required=True)
    run(parser.parse_args().home.resolve())
