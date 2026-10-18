# Development / 开发与验证

[English README](../README.md) · [中文说明](../README.zh-CN.md)

## Run from source

Python 3.12 is the reference runtime. The control panel uses the Python standard library. Service management requires Windows PowerShell 5.1 and Windows Task Scheduler.

```powershell
git clone https://github.com/thekingofall/Soft-HeartDevSpace.git
cd Soft-HeartDevSpace
python launch.py
```

For an isolated configuration, supply a new data directory:

```powershell
python launch.py --home D:\AppTests\HeartDevSpace
```

`--no-browser` starts the dashboard without opening a tab. The private bootstrap URL is stored in `<home>\dashboard.json` while the dashboard is running. `--port` fixes the loopback dashboard port; it is separate from the DevSpace and cloudflared ports.

每套配置由 `--home` 指定，拥有独立的服务状态和计划任务。测试其他实例时，请为 DevSpace 和隧道健康检查选择不同端口。

## Source map

| File | Responsibility |
| :--- | :--- |
| `heartdevspace/core.py` | Settings, dependency detection, Cloudflare setup, background jobs |
| `heartdevspace/server.py` | Authenticated loopback dashboard and single-instance launch |
| `heartdevspace/web/` | English / Chinese user interface |
| `heartdevspace/runtime/control.ps1` | Hidden scheduled task installation and removal |
| `heartdevspace/runtime/watch.ps1` | Health checks, process identity, recovery policy, logs |
| `heartdevspace/runtime/quiet-launcher.cs` | Windowless process host, log capture, child-process cleanup |
| `relay/` | HTTPS gateway, STCP templates, Linux health checker and systemd units |
| `tests/test_failover.py` | Route selection, recovery hold, reload rollback and crash recovery |
| `tests/test_core.py` | Configuration and HTTP boundary tests |
| `tests/test_recovery.ps1` | Recovery thresholds, cooldowns, duplicate processes |
| `tests/windows_integration.py` | Opt-in real-engine recovery and task lifecycle test |
| `scripts/draw_overview.R` | Rebuild the PNG and vector PDF illustration |

The heartbeat runs as a bounded task. Two repeating one-minute triggers are offset by 30 seconds; a mutex serializes checks. Each HTTP probe has an eight-second timeout. Task execution is capped at two minutes. Startup uses the signed-in user's identity and limited run level.

Managed processes are identified by executable path plus an instance-specific marker or tunnel configuration path. Stop and recovery operate on matching processes. DevSpace uses a persistent app-owned configuration and state directory, so restarts retain OAuth state.

The .NET Framework compiler builds a small windowless host in the private runtime directory. Its filename contains a source hash, so existing hosts can continue through upgrades. Services use `CreateNoWindow` and a Windows job with `KILL_ON_JOB_CLOSE`. The heartbeat detaches its output handles before creating persistent service hosts. Scheduled tasks retain the worker exit code. This requires the Windows .NET Framework 4.x compiler.

The optional `external_engine` runtime field supports an existing DevSpace deployment managed by another watchdog. It suppresses engine start/stop; the deployment adapter must supply that engine's existing configuration directory. The normal dashboard manages its own engine and configuration.

The worker clears inherited `DEVSPACE_*` variables in its own process before selecting the app's configuration. This keeps credentials, ports, and roots from an older installation from overriding the control panel's settings. Windows user and system environment settings remain intact.

## Automated checks

```powershell
python -m unittest discover -s tests -v
powershell -NoProfile -ExecutionPolicy Bypass -File tests\test_recovery.ps1
node --check heartdevspace\web\app.js
```

The optional Windows integration test creates a temporary scheduled task and removes it in cleanup. It requires installed Node 24, Git Bash, DevSpace 1.0.8, and the Windows .NET Framework C# compiler. Supply a **new disposable directory**:

```powershell
python -m tests.windows_integration --home D:\AppTests\heart-integration-01
python -m tests.windows_quiet --home D:\AppTests\heart-quiet-01
```

This test runs the real DevSpace service with a local cloudflared readiness fixture, completes local OAuth and an authenticated file read, terminates the test service, waits for scheduled recovery, reuses its existing authorization, and checks stop/task removal. The fixture creates no public tunnel or DNS record. Customer-account Cloudflare provisioning and ChatGPT OAuth completion require validation in the customer's actual account.

The quiet-launcher test checks that both the managed process and its child have no console, that exit codes propagate, and that the child exits when its managed parent is terminated.

Windows 集成测试会实际启动 DevSpace，并通过结束测试进程检查自动恢复。Cloudflare 就绪状态由本地测试程序提供；真实域名的创建和 ChatGPT 账户授权，需要在相应账户中完成验证。

## Build a Windows release

Build on Windows x64 with Python 3.12:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\scripts\build_windows.ps1 -Python .venv\Scripts\python.exe -BuildRoot D:\BuildTemp\Soft-HeartDevSpace
```

The output in `dist` includes a portable folder, a versioned ZIP, and `SHA256SUMS.txt`. The app uses PyInstaller's windowed launcher. User configuration is stored outside the release folder. Version 0.2.0 Windows binaries are unsigned.

Check the compiled application with a new disposable home directory:

```powershell
python -m tests.package_smoke --exe dist\Soft-HeartDevSpace\Soft-HeartDevSpace.exe --home D:\AppTests\heart-package-01
```

Before publishing, run the checks, launch the packaged executable with an isolated `--home`, verify language switching and bundled assets, and inspect the archive for local data. Keep Node, Git, DevSpace, and cloudflared as explicit external dependencies.

## Diagram and visual identity

```powershell
Rscript scripts\draw_overview.R
```

The script uses base R's `grid` package and Arial, with Cairo PNG/PDF devices. The diagram palette is centralized in the script: teal `#167E7B`, blue `#5B80AA`, gold `#BA9348`, purple `#8875A9`, and charcoal `#243A45`. Documentation screenshots show an unconfigured installation.

The diagram is software documentation. Its visual reference is the author's [scFetallife_Blood graphical abstract](https://github.com/thekingofall/scFetallife_Blood/blob/main/docs/figures/graphical_abstract.png).

## Upstream references

- [DevSpace](https://github.com/Waishnav/DevSpace)
- [Cloudflare: create a locally managed tunnel](https://developers.cloudflare.com/tunnel/features/locally-managed-tunnels/create-local-tunnel/)
- [Cloudflare: configuration file](https://developers.cloudflare.com/tunnel/features/locally-managed-tunnels/configuration-file/)
- [Cloudflare: runtime parameters](https://developers.cloudflare.com/tunnel/reference/run-parameters/)
- [OpenAI: connect and test an MCP server](https://developers.openai.com/plugins/deploy/connect-chatgpt)
- [Microsoft: task repetition interval](https://learn.microsoft.com/en-us/windows/win32/taskschd/taskschedulerschema-interval-repetitiontype-element)
