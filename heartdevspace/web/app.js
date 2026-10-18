"use strict";
const session = document.querySelector('meta[name="heart-session"]').content;
history.replaceState(null, "", "/");
const zh = {
 activeRoute:"当前线路", connectionMode:"连接模式", dualMode:"双通道 · 自动切换", cloudflareOrigin:"Cloudflare 源站域名", originHint:"双通道使用独立的源站子域名，公网域名指向中转网关。", frpConfig:"本机 FRP 配置文件（.toml）", frpHint:"配置一个指向 DevSpace 端口的 STCP 通道，凭据保存在该本机文件内。", frpGuide:"FRP 与双通道设置指南 ↗",
 sidebar:"让本机项目保持连接", overview:"概览",connection:"连接设置",activity:"运行记录",localOnly:"本机控制台",backgroundNote:"关闭此页面后，后台心跳按当前设置继续运行。",quit:"退出控制台",
 overviewEyebrow:"让你的工作空间随时可达",headline:"让本机项目，\n保持连接。",lead:"将本地项目接入 ChatGPT，让连接定时检查、断线后自动恢复。",heartbeatLabel:"连接心跳监控",
 localService:"本地工作空间",secureTunnel:"安全隧道",checkEvery:"心跳间隔",seconds:"秒",lastSeen:"最近一次连接正常",folders:"共享目录",yourEndpoint:"你的连接地址",copy:"复制",start:"启动并启用心跳",check:"检查连接",stop:"停止连接",firstTime:"首次连接？",firstTimeNote:"设置域名和目录，授权 Cloudflare，再到 ChatGPT 中连接应用。",openSetup:"开始设置 →",
 connectionEyebrow:"使用你的域名和项目",setupTitle:"连接设置",setupLead:"选择 ChatGPT 可以操作的项目，以及连接这台电脑的域名。",hostname:"公网域名",hostnameHint:"填写 ChatGPT 使用的固定 HTTPS 域名。",tunnelName:"隧道名称",tunnelHint:"为这台电脑的连接取一个容易识别的名称。",projectFolders:"项目目录",foldersHint:"每行填写一个已存在的目录。连接的客户端可以编辑文件，并以你的 Windows 账户权限执行命令。",advanced:"高级设置 · 端口与运行工具",servicePort:"DevSpace 端口",metricsPort:"隧道健康检查端口",save:"保存设置",detect:"检测运行工具",installEngine:"安装 DevSpace 1.0.8",cloudflareTitle:"连接你的域名",authorizeCloudflare:"授权 Cloudflare",cloudflareNote:"在浏览器中登录，并选择包含所填域名的站点。",signIn:"登录 Cloudflare",createTunnel:"创建隧道和域名路由",createNote:"创建 Cloudflare 源站路由；FRP 与双通道模式还需要配置中转网关。",create:"创建连接",prerequisites:"需要 Node.js 24 LTS、Git for Windows、cloudflared，以及由 Cloudflare 管理 DNS 的域名。安装步骤见 README。",
 chatEyebrow:"从浏览器连接你的本地项目",chatTitle:"接入 ChatGPT",chatLead:"添加一次个人连接，然后在需要本地文件的对话中选择它。",chatStep1:"创建自定义应用",chatStep1Body:"打开 ChatGPT 插件页，点击加号，再选择添加自定义 MCP 服务器。菜单与开放情况取决于账户和工作区设置。",openChatGPT:"打开 ChatGPT ↗",chatStep2:"填写服务器地址",chatStep2Body:"粘贴下方 MCP 地址，身份验证选择 OAuth，再按提示连接。",chatStep3:"授权并试用",chatStep3Body:"在你自己域名的授权页输入 Owner 密码。返回 ChatGPT，选择应用，请它列出一个项目目录。",showPassword:"显示 Owner 密码",testPrompt:"试试这条指令",prompt:"请使用我的 DevSpace 连接，打开 C:\\Projects\\MyProject 并列出顶层文件，保持文件内容不变。",accountNote:"创建入口与菜单随 ChatGPT 套餐、功能开放和工作区政策变化。Owner 密码保存在本机，请在授权页输入并妥善保管。",officialGuide:"ChatGPT 官方接入指南 ↗",
 activityEyebrow:"连接运行记录",activityTitle:"心跳与自动恢复",activityLead:"每次检查都有记录。连续异常时，后台会按恢复策略重新连接。",recentActivity:"最近记录",refresh:"刷新",startup:"登录后自动启动",startupNote:"启动连接后会启用隐藏运行的自动恢复任务。移除自启后仍保留本地设置。",removeStartup:"移除自动启动",footer:"连接你的本地工作空间。"
};
const en = {};
document.querySelectorAll("[data-i18n]").forEach(el => en[el.dataset.i18n] = el.textContent);
en.headline = "Keep your workspace\nwithin reach.";
let language = localStorage.getItem("heart-language") || (navigator.language.startsWith("zh") ? "zh" : "en");
let state = null, formLoaded = false, lastJob = "", page = "overview", polling = false;
const tr = (enText, zhText) => language === "zh" ? zhText : enText;
function translate() {
 document.documentElement.lang = language === "zh" ? "zh-CN" : "en";
 document.querySelectorAll("[data-i18n]").forEach(el => el.textContent = (language === "zh" ? zh : en)[el.dataset.i18n] || en[el.dataset.i18n]);
 document.getElementById("language").textContent = language === "zh" ? "English" : "中文";
 document.getElementById("page-label").textContent = page === "chatgpt" ? "ChatGPT" : (language === "zh" ? zh : en)[page];
 if (state) render(state);
}
function notice(message, error=false) {const el=document.getElementById("notice");el.hidden=false;el.textContent=message;el.classList.toggle("error",error);}
async function api(path, data) {
 const options=data === undefined ? {} : {method:"POST",headers:{"Content-Type":"application/json","X-Heart-Session":session},body:JSON.stringify(data)};
 const response=await fetch(path,options);const result=await response.json();if(!response.ok) throw new Error(result.error || "Request failed");return result;
}
function navigate(next) {page=next;document.querySelectorAll(".page").forEach(el=>el.classList.toggle("active",el.id===next));document.querySelectorAll(".nav").forEach(el=>el.classList.toggle("active",el.dataset.page===next));translate();if(next==="activity") loadLogs();window.scrollTo(0,0);}
function fillForm(settings) {const form=document.getElementById("settings-form");for(const [key,value] of Object.entries(settings)){const el=form.elements.namedItem(key);if(el)el.value=key==="allowed_roots"?value.join("\n"):value;}formLoaded=true;}
function render(data) {
 state=data;const health=data.health, enabled=data.settings.enabled;
 const fresh=health.checkedAtUtc && Date.now()-Date.parse(health.checkedAtUtc)<120000;
 const complete=enabled && fresh && health.local?.healthy && (health.tunnel?.healthy || health.frp?.healthy) && health.public?.healthy;
 const badge=document.getElementById("connection-badge");badge.textContent=complete?tr("ENDPOINT ONLINE","服务地址在线"):enabled?tr("CONNECTING","连接检查中"):data.configured?tr("STOPPED","已停止"):tr("SETUP REQUIRED","等待设置");badge.classList.toggle("good",!!complete);
 for(const [id,key] of [["local-state","local"],["tunnel-state","tunnel"],["frp-state","frp"],["public-state","public"]]){const ok=enabled&&fresh&&health[key]?.healthy;const pending=enabled&&fresh&&health[key]?.deferred;const el=document.getElementById(id);el.textContent=health[key]?.disabled?tr("Not selected","未选用"):!enabled?tr("Not running","尚未运行"):!fresh?tr("Awaiting heartbeat","等待心跳"):pending?tr("Gateway pending","等待公网网关"):ok?(key==="public"?tr("Endpoint reachable","地址可达"):tr("Healthy","正常")):tr("Reconnecting","恢复中");el.className="state "+(ok?"good":enabled&&!pending&&!health[key]?.disabled?"bad":"");}
 document.getElementById("active-route").textContent=health.public?.transport || (data.settings.connection_mode==="cloudflare"?"Cloudflare":"—");
 document.getElementById("last-healthy").textContent=health.state?.lastHealthyUtc?new Date(health.state.lastHealthyUtc).toLocaleTimeString(language==="zh"?"zh-CN":"en-GB",{hour12:false}):"—";
 document.getElementById("root-count").textContent=data.settings.allowed_roots.length;
 document.getElementById("endpoint").textContent=data.endpoint||"https://your-domain.example/mcp";
 document.getElementById("chat-endpoint").textContent=data.endpoint||tr("Save your hostname in Connection settings.","请先在连接设置中保存域名。");
 document.getElementById("copy-endpoint").disabled=!data.endpoint;
 document.querySelectorAll("[data-action]").forEach(el=>el.disabled=data.job.running || (el.dataset.action==="start"&&enabled));
 document.querySelector('#settings-form button[type="submit"]').disabled=data.job.running||enabled;
 if(!formLoaded)fillForm(data.settings);
 const signature=JSON.stringify(data.job);
 if(data.job.action && signature!==lastJob){if(data.job.running)notice(tr("Working: ","正在处理：")+data.job.action+tr(". Browser authorization may require your input.","。如出现浏览器授权页，请完成登录。"));else notice((data.job.ok?tr("Completed. ","操作完成。 "):tr("Action required. ","需要处理。 "))+data.job.message,!data.job.ok);if(!data.job.running && ["detect","engine_install"].includes(data.job.action))fillForm(data.settings);lastJob=signature;}
}
async function refresh(){if(polling)return;polling=true;try{render(await api("/api/state"));}catch(error){notice(tr("Control panel unavailable. Reopen Soft-HeartDevSpace. ","控制台连接中断，请重新打开软件。 ")+error.message,true);}finally{polling=false;}}
async function loadLogs(){try{document.getElementById("logs").textContent=(await api("/api/logs")).text||tr("Heartbeat records appear after you start the connection.","启动连接后可查看心跳记录。");}catch(error){notice(error.message,true);}}
document.querySelectorAll("[data-page]").forEach(el=>el.addEventListener("click",()=>navigate(el.dataset.page)));
document.getElementById("language").addEventListener("click",()=>{language=language==="en"?"zh":"en";localStorage.setItem("heart-language",language);translate();});
document.getElementById("settings-form").addEventListener("submit",async event=>{event.preventDefault();const values=Object.fromEntries(new FormData(event.target));values.allowed_roots=values.allowed_roots.split(/\r?\n/).map(s=>s.trim()).filter(Boolean);values.port=Number(values.port);values.metrics_port=Number(values.metrics_port);values.language=language;try{await api("/api/settings",values);notice(tr("Settings saved.","设置已保存。"));await refresh();}catch(error){notice(error.message,true);}});
document.querySelectorAll("[data-action]").forEach(el=>el.addEventListener("click",async()=>{try{await api("/api/action",{action:el.dataset.action});await refresh();}catch(error){notice(error.message,true);}}));
document.getElementById("copy-endpoint").addEventListener("click",async()=>{try{await navigator.clipboard.writeText(state.endpoint);notice(tr("MCP address copied.","MCP 地址已复制。"));}catch{notice(tr("Select and copy the connection address.","请选中连接地址并复制。"));}});
document.getElementById("show-password").addEventListener("click",async()=>{const output=document.getElementById("password");if(!output.hidden){output.hidden=true;output.textContent="";return;}try{output.textContent=(await api("/api/owner-password",{})).password;output.hidden=false;setTimeout(()=>{output.hidden=true;output.textContent="";},30000);}catch(error){notice(error.message,true);}});
document.getElementById("refresh-logs").addEventListener("click",loadLogs);
document.getElementById("quit").addEventListener("click",async()=>{try{await api("/api/quit",{});clearInterval(timer);notice(tr("Control panel closed. You can close this tab.","控制台已退出，可以关闭此标签页。"));}catch(error){notice(error.message,true);}});
translate();refresh();const timer=setInterval(refresh,4000);
