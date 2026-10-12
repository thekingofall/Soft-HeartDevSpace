"""Configuration, Windows integration, and bounded background jobs."""
from __future__ import annotations

import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import subprocess
import threading
import uuid
from urllib.parse import urlsplit

from . import __version__

PACKAGE = Path(__file__).resolve().parent
DEVSPACE_VERSION = "1.0.8"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def read_json(path: Path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    stage = path.with_name(path.name + ".new")
    stage.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(stage, path)


def normalize_domain(value: str) -> str:
    value = value.strip().lower()
    if not value:
        raise ValueError("Enter your public hostname, for example dev.example.com.")
    if "://" in value:
        url = urlsplit(value)
        if url.scheme != "https" or url.path not in ("", "/") or url.query or url.fragment or url.username or url.port:
            raise ValueError("Use an HTTPS hostname without a path, port, or password.")
        value = url.hostname or ""
    value = value.encode("idna").decode("ascii")
    if len(value) > 253 or "." not in value or not all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in value.split(".")):
        raise ValueError("Enter a valid public DNS hostname.")
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return value
    raise ValueError("Use a DNS hostname from your Cloudflare zone.")


def hidden_run(args: list[str], *, timeout=30, env=None, cwd=None):
    result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace",
                            timeout=timeout, env=env, cwd=cwd, creationflags=NO_WINDOW)
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout or f"Exit code {result.returncode}")[-4000:].strip())
    return result.stdout.strip()


def powershell() -> str:
    return str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe")


def _first_file(candidates) -> str:
    return next((str(Path(p).resolve()) for p in candidates if p and Path(p).is_file()), "")


def detect_dependencies(home: Path) -> dict:
    local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
    roaming = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))
    program = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    node = _first_file([shutil.which("node"), program / "nodejs/node.exe"])
    git = shutil.which("git")
    bash = _first_file([Path(git).parent.parent / "bin/bash.exe" if git else None, program / "Git/bin/bash.exe"])
    cloud = _first_file([shutil.which("cloudflared"), *local.glob("Microsoft/WinGet/Packages/Cloudflare.cloudflared_*/cloudflared.exe")])
    cli = _first_file([home / "engine/node_modules/@waishnav/devspace/dist/cli.js",
                       roaming / "npm/node_modules/@waishnav/devspace/dist/cli.js"])
    version = ""
    if cli:
        version = read_json(Path(cli).parent.parent / "package.json", {}).get("version", "")
    return {"node_path": node, "bash_path": bash, "cloudflared_path": cloud, "devspace_cli": cli,
            "engine_version": version, "engine_compatible": version == DEVSPACE_VERSION}


class Manager:
    def __init__(self, home: Path):
        self.home = home.resolve()
        self.home.mkdir(parents=True, exist_ok=True)
        self.path = self.home / "settings.json"
        self.lock = threading.RLock()
        self.job = {"running": False, "action": "", "ok": None, "message": ""}
        self.settings = read_json(self.path)
        if self.settings is None:
            self.settings = {"schema_version": 1, "instance_id": uuid.uuid4().hex[:12], "domain": "",
                             "tunnel_name": "heartdevspace", "tunnel_id": "", "credentials_path": "",
                             "port": 7676, "metrics_port": 20251, "allowed_roots": [], "enabled": False,
                             "language": "en", **detect_dependencies(self.home)}
            self.persist()
        self.deploy_runtime()

    @property
    def task_name(self):
        return "Soft-HeartDevSpace-" + self.settings["instance_id"]

    def persist(self):
        self.settings.update({"home": str(self.home), "config_dir": str(self.home / "devspace"),
                              "state_dir": str(self.home / "devspace-state"), "log_dir": str(self.home / "logs"),
                              "tunnel_config": str(self.home / "tunnel.yml"), "heartbeat_seconds": 30})
        write_json(self.path, self.settings)

    def deploy_runtime(self):
        runtime = self.home / "runtime"
        runtime.mkdir(exist_ok=True)
        for name in ("watch.ps1", "control.ps1"):
            src, dest = PACKAGE / "runtime" / name, runtime / name
            if not dest.exists() or dest.read_bytes() != src.read_bytes():
                stage = dest.with_suffix(".new")
                shutil.copyfile(src, stage)
                os.replace(stage, dest)

    def snapshot(self):
        with self.lock:
            return {"version": __version__, "settings": dict(self.settings), "job": dict(self.job),
                    "health": read_json(self.home / "logs/status.json", {}),
                    "endpoint": f"https://{self.settings['domain']}/mcp" if self.settings["domain"] else "",
                    "task_name": self.task_name, "configured": bool(self.settings["domain"] and self.settings["allowed_roots"])}

    def save(self, payload):
        with self.lock:
            if self.job["running"]:
                raise ValueError("Wait for the current operation to finish.")
            if self.settings["enabled"]:
                raise ValueError("Stop the connection before changing its settings.")
            candidate = dict(self.settings)
            candidate["domain"] = normalize_domain(str(payload.get("domain", "")))
            name = str(payload.get("tunnel_name", "heartdevspace")).strip()
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,62}", name):
                raise ValueError("Tunnel name must contain letters, numbers, underscores, or hyphens.")
            candidate["tunnel_name"] = name
            roots = payload.get("allowed_roots", [])
            if not isinstance(roots, list) or not roots:
                raise ValueError("Choose at least one existing project folder.")
            resolved = []
            for item in roots:
                root = Path(str(item)).expanduser()
                if not root.is_absolute() or not root.is_dir():
                    raise ValueError(f"Project folder does not exist: {root}")
                if str(root.resolve()) not in resolved:
                    resolved.append(str(root.resolve()))
            candidate["allowed_roots"] = resolved
            for name in ("port", "metrics_port"):
                val = int(payload.get(name, candidate[name]))
                if not 1024 <= val <= 65535:
                    raise ValueError("Ports must be between 1024 and 65535.")
                candidate[name] = val
            if candidate["port"] == candidate["metrics_port"]:
                raise ValueError("Service and health ports must be different.")
            for name in ("node_path", "bash_path", "cloudflared_path", "devspace_cli"):
                val = str(payload.get(name, candidate.get(name, ""))).strip()
                if val and not Path(val).is_file():
                    raise ValueError(f"File does not exist: {val}")
                candidate[name] = val
            candidate["language"] = payload.get("language", "en") if payload.get("language") in ("en", "zh") else "en"
            # A tunnel name change requires a new explicit create/connect operation.
            if candidate["tunnel_name"] != self.settings["tunnel_name"]:
                candidate["tunnel_id"] = ""
                candidate["credentials_path"] = ""
            self.settings = candidate
            self.persist()
            self.write_service_config()
        return "Settings saved."

    def write_service_config(self):
        s = self.settings
        if not s["domain"] or not s["allowed_roots"]:
            raise ValueError("Save a hostname and project folders first.")
        config_dir = Path(s["config_dir"])
        write_json(config_dir / "config.json", {"host": "127.0.0.1", "port": s["port"],
                    "publicBaseUrl": f"https://{s['domain']}", "allowedRoots": s["allowed_roots"],
                    "stateDir": s["state_dir"], "worktreeRoot": str(self.home / "worktrees")})
        auth = config_dir / "auth.json"
        if not auth.exists():
            write_json(auth, {"ownerToken": secrets.token_urlsafe(32)})
        if s["tunnel_id"] and s["credentials_path"]:
            # JSON strings are valid YAML scalars, including Windows paths.
            q = json.dumps
            text = (f"protocol: http2\ntunnel: {q(s['tunnel_id'])}\ncredentials-file: {q(s['credentials_path'])}\n"
                    f"metrics: 127.0.0.1:{s['metrics_port']}\ningress:\n"
                    f"  - hostname: {q(s['domain'])}\n    service: http://127.0.0.1:{s['port']}\n"
                    "  - service: http_status:404\n")
            target = self.home / "tunnel.yml"
            stage = target.with_suffix(".new")
            stage.write_text(text, encoding="utf-8")
            os.replace(stage, target)

    def owner_password(self):
        auth = read_json(Path(self.settings["config_dir"]) / "auth.json", {})
        if not auth.get("ownerToken"):
            raise ValueError("Save the connection settings first.")
        return auth["ownerToken"]

    def control(self, action):
        if os.name != "nt":
            raise RuntimeError("Background services require Windows 10 or Windows 11.")
        return hidden_run([powershell(), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
                           str(self.home / "runtime/control.ps1"), "-ConfigPath", str(self.path), "-Action", action], timeout=140)

    def ensure_engine(self):
        s = self.settings
        for label in ("node_path", "bash_path", "devspace_cli"):
            if not s.get(label) or not Path(s[label]).is_file():
                raise ValueError(f"Missing {label}. Install the prerequisite and choose Detect tools.")
        version = read_json(Path(s["devspace_cli"]).parent.parent / "package.json", {}).get("version")
        if version != DEVSPACE_VERSION:
            raise ValueError(f"This release supports DevSpace {DEVSPACE_VERSION}. Choose Install DevSpace.")
        node_version = hidden_run([s["node_path"], "--version"])
        if not node_version.startswith("v24."):
            raise ValueError("Use Node.js 24 LTS for the tested engine version.")

    def perform(self, action):
        if action == "detect":
            if self.settings["enabled"]:
                raise ValueError("Stop the connection before changing its runtime tools.")
            self.settings.update(detect_dependencies(self.home))
            self.persist()
            return "Tools detected."
        if action == "engine_install":
            if self.settings["enabled"]:
                raise ValueError("Stop the connection before installing the engine.")
            node = self.settings.get("node_path")
            if not node:
                raise ValueError("Install Node.js 24 LTS, then choose Detect tools.")
            npm_cli = Path(node).parent / "node_modules/npm/bin/npm-cli.js"
            if not npm_cli.is_file():
                raise ValueError("npm-cli.js was not found beside Node.js. Install the Node.js LTS distribution.")
            env = dict(os.environ, PATH=str(Path(node).parent) + os.pathsep + os.environ.get("PATH", ""))
            hidden_run([node, str(npm_cli), "install", "--prefix", str(self.home / "engine"),
                        f"@waishnav/devspace@{DEVSPACE_VERSION}", "--no-audit", "--no-fund"], timeout=900, env=env)
            self.settings.update(detect_dependencies(self.home))
            self.persist()
            return f"DevSpace {DEVSPACE_VERSION} installed."
        if action == "cloudflare_login":
            exe = self.settings.get("cloudflared_path")
            if not exe:
                raise ValueError("Install cloudflared, then choose Detect tools.")
            hidden_run([exe, "tunnel", "login"], timeout=600)
            return "Cloudflare account authorized."
        if action == "tunnel_create":
            if self.settings["enabled"]:
                raise ValueError("Stop the connection before changing the tunnel.")
            s = self.settings
            if not s["domain"]:
                raise ValueError("Save your hostname first.")
            exe = s.get("cloudflared_path")
            if not exe:
                raise ValueError("Install cloudflared, then choose Detect tools.")
            tunnels = json.loads(hidden_run([exe, "tunnel", "list", "--output", "json"], timeout=45))
            match = next((t for t in tunnels if t.get("name") == s["tunnel_name"]), None)
            if not match:
                hidden_run([exe, "tunnel", "create", s["tunnel_name"]], timeout=60)
                tunnels = json.loads(hidden_run([exe, "tunnel", "list", "--output", "json"], timeout=45))
                match = next((t for t in tunnels if t.get("name") == s["tunnel_name"]), None)
            if not match:
                raise ValueError("The tunnel was not returned by Cloudflare. Check the account and tunnel name.")
            tunnel_id = str(uuid.UUID(match["id"]))
            credential = Path.home() / ".cloudflared" / (tunnel_id + ".json")
            if not credential.is_file():
                raise ValueError("This tunnel has no local credentials. Use a new tunnel name or restore its credential file.")
            s.update(tunnel_id=tunnel_id, credentials_path=str(credential))
            self.persist()
            self.write_service_config()
            hidden_run([exe, "--config", str(self.home / "tunnel.yml"), "tunnel", "route", "dns", tunnel_id, s["domain"]], timeout=60)
            return "Tunnel and DNS hostname are ready."
        if action == "start":
            if self.settings["enabled"]:
                return "Heartbeat is already enabled."
            self.ensure_engine()
            self.write_service_config()
            if not self.settings.get("tunnel_id") or not Path(self.settings.get("credentials_path", "")).is_file():
                raise ValueError("Create the tunnel and DNS route first.")
            for port in (self.settings["port"], self.settings["metrics_port"]):
                with socket.socket() as probe:
                    probe.settimeout(0.5)
                    if probe.connect_ex(("127.0.0.1", port)) == 0:
                        raise ValueError(f"Port {port} is in use. Stop the existing installation or choose a different port.")
            old = self.settings["enabled"]
            self.settings["enabled"] = True
            self.persist()
            try:
                self.control("Install")
            except Exception:
                self.settings["enabled"] = old
                self.persist()
                raise
            return "Heartbeat enabled. Initial startup can take up to three minutes."
        if action in ("stop", "remove_autostart"):
            self.settings["enabled"] = False
            self.persist()
            self.control("Remove" if action == "remove_autostart" else "Stop")
            return "Connection stopped." if action == "stop" else "Startup task removed. Local settings retained."
        if action == "check":
            self.control("Check")
            return "Connection checked."
        raise ValueError("Unknown action.")

    def start_job(self, action):
        if action not in {"detect", "engine_install", "cloudflare_login", "tunnel_create", "start", "stop", "remove_autostart", "check"}:
            raise ValueError("Unknown action.")
        with self.lock:
            if self.job["running"]:
                raise ValueError("Wait for the current operation to finish.")
            self.job = {"running": True, "action": action, "ok": None, "message": ""}

        def worker():
            try:
                message = self.perform(action)
                outcome = {"running": False, "action": action, "ok": True, "message": message}
            except Exception as error:
                outcome = {"running": False, "action": action, "ok": False, "message": str(error)[:4000]}
            with self.lock:
                self.job = outcome
        threading.Thread(target=worker, daemon=True).start()

    def logs(self):
        path = self.home / "logs/heartbeat.log"
        if not path.exists():
            return ""
        with path.open("rb") as handle:
            handle.seek(max(0, path.stat().st_size - 24000))
            return handle.read().decode("utf-8", errors="replace")
