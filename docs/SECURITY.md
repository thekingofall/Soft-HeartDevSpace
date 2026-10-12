# Privacy and security / 隐私与安全

Soft-HeartDevSpace is designed for one person managing a trusted Windows computer. It exposes DevSpace file and command tools to clients that complete the configured OAuth flow. The Windows account's permissions determine what commands can access. Project-root configuration does not isolate a command process from the rest of that account.

本软件适用于个人管理可信的 Windows 电脑。授权后的客户端能够使用 DevSpace 文件和命令工具。命令权限以运行软件的 Windows 账户为准；需要严格隔离时，请使用专用账户、虚拟机或独立电脑。

## Data locations

| Location | Contents |
| :--- | :--- |
| `%LOCALAPPDATA%\Soft-HeartDevSpace\settings.json` | Hostname, folders, executable paths and startup state |
| `devspace\auth.json` under that folder | Owner authorization password |
| `devspace-state\` | DevSpace's persistent authorization state |
| `logs\` | Health events and component output |
| `%USERPROFILE%\.cloudflared` | Account certificate and tunnel credentials managed by cloudflared |

The control panel has no analytics or application telemetry. npm and cloudflared contact their respective services during setup. The tunnel routes requests through Cloudflare. ChatGPT receives the results of authorized tool calls. Upstream tools and connected services have their own data policies.

控制台本身不收集使用统计。安装依赖和配置隧道会连接对应服务，Cloudflare 转发隧道请求，ChatGPT 接收已授权工具的返回内容。上游工具及所连接服务适用各自的数据政策。

## Connection protection

The dashboard binds to loopback and checks its private session, request host, and request origin. The initial dashboard URL is a local bearer credential; keep it private. The public service uses DevSpace's OAuth implementation. Keep the Owner password, tunnel credentials, and the Windows account private.

The application preserves the Owner password across normal settings changes. Restarting the service retains its state. Revoked or expired client authorization may require reconnection in ChatGPT.

## Reporting a problem

For a security concern, use the repository's private vulnerability reporting option when it is available. For an ordinary bug, open a GitHub issue with the app version, Windows version, and a sanitized description. Share short relevant log excerpts. Remove passwords, authorization headers, tunnel credentials, hostnames, and personal paths.

反馈故障时，请提供版本、系统环境和经过清理的错误摘要。公开 issue 中请清除密码、授权信息、隧道凭据以及私人路径。仓库启用私密漏洞报告时，安全问题可通过该入口提交。
