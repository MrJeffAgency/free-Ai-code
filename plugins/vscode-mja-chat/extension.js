// MrJeffAgency AI Chat for VS Code — talks to a local MJA server
const vscode = require("vscode");

let currentPanel = null;

function cfg() {
  const c = vscode.workspace.getConfiguration("mjaChat");
  return {
    serverUrl: String(c.get("serverUrl") || "http://127.0.0.1:8082").replace(/\/$/, ""),
    model: String(c.get("model") || ""),
    token: String(c.get("token") || ""),
  };
}

async function setSetting(key, prompt) {
  const c = vscode.workspace.getConfiguration("mjaChat");
  const current = String(c.get(key) || "");
  const value = await vscode.window.showInputBox({ prompt, value: current, placeHolder: key === "serverUrl" ? "http://127.0.0.1:8082" : "" });
  if (value !== undefined) {
    await c.update(key, value, vscode.ConfigurationTarget.Global);
    if (currentPanel) currentPanel.webview.postMessage({ type: "config", config: cfg() });
  }
}

function openChat(context) {
  const column = vscode.ViewColumn.Beside;
  if (currentPanel) {
    currentPanel.reveal(column);
    return;
  }
  const panel = vscode.window.createWebviewPanel(
    "mjaChat", "MrJeffAgency AI Chat", column,
    { enableScripts: true, retainContextWhenHidden: true }
  );
  currentPanel = panel;
  panel.webview.html = getHtml(cfg());

  panel.webview.onDidReceiveMessage(async (msg) => {
    if (msg.type === "chat") {
      const settings = cfg();
      const history = msg.history || [];
      try {
        const res = await fetch(settings.serverUrl + "/v1/chat/completions", {
          method: "POST",
          headers: Object.assign(
            { "Content-Type": "application/json" },
            settings.token ? { Authorization: "Bearer " + settings.token } : {}
          ),
          body: JSON.stringify({
            model: settings.model || undefined,
            messages: history,
            stream: true,
          }),
        });
        if (!res.ok) {
          const t = await res.text();
          panel.webview.postMessage({ type: "error", text: "HTTP " + res.status + ": " + t.slice(0, 300) });
          return;
        }
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buf = "";
        let full = "";
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buf += decoder.decode(value, { stream: true });
          let i;
          while ((i = buf.indexOf("\n")) >= 0) {
            const line = buf.slice(0, i).trim();
            buf = buf.slice(i + 1);
            if (!line.startsWith("data:")) continue;
            const data = line.slice(5).trim();
            if (data === "[DONE]") continue;
            try {
              const obj = JSON.parse(data);
              const d = obj.choices && obj.choices[0] && obj.choices[0].delta;
              if (d && d.content) {
                full += d.content;
                panel.webview.postMessage({ type: "delta", text: d.content });
              }
            } catch (_) { /* ignore */ }
          }
        }
        panel.webview.postMessage({ type: "done", text: full });
      } catch (e) {
        panel.webview.postMessage({ type: "error", text: String((e && e.message) || e) });
      }
    }
  });

  panel.onDidDispose(() => { currentPanel = null; });
}

function getHtml(config) {
  const c = JSON.stringify(config).replace(/</g, "\\u003c");
  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>MrJeffAgency AI Chat</title>
<style>
  body { font-family: var(--vscode-font-family); color: var(--vscode-foreground); background: var(--vscode-editor-background); margin:0; display:flex; flex-direction:column; height:100vh; }
  header { padding:8px 12px; border-bottom:1px solid var(--vscode-panel-border); font-weight:bold; }
  header small { font-weight:normal; opacity:.7; }
  #log { flex:1; overflow:auto; padding:10px; }
  .msg { margin:8px 0; }
  .msg b { display:block; font-size:11px; opacity:.7; }
  .msg div { white-space:pre-wrap; word-break:break-word; }
  #row { display:flex; gap:6px; padding:8px; border-top:1px solid var(--vscode-panel-border); }
  textarea { flex:1; resize:vertical; background:var(--vscode-input-background); color:var(--vscode-input-foreground); border:1px solid var(--vscode-input-border); padding:6px; }
  button { background:var(--vscode-button-background); color:var(--vscode-button-foreground); border:0; padding:6px 12px; cursor:pointer; }
</style>
</head>
<body>
<header>MrJeffAgency AI Chat <small id="info"></small></header>
<div id="log"></div>
<div id="row"><textarea id="in" rows="3" placeholder="Type a message…"></textarea><button id="send">Send</button></div>
<script>
  const vscode = acquireVsCodeApi();
  let config = ${c};
  let history = [];
  let busy = false;
  const log = document.getElementById('log');
  const info = document.getElementById('info');
  const input = document.getElementById('in');
  function updateInfo() { info.textContent = 'model: ' + (config.model || '(server default)') + ' · ' + config.serverUrl; }
  function add(role, text) {
    const m = document.createElement('div'); m.className = 'msg';
    const b = document.createElement('b'); b.textContent = role === 'user' ? 'You' : 'MJA';
    const d = document.createElement('div'); d.textContent = text;
    m.append(b, d); log.append(m); log.scrollTop = log.scrollHeight;
    return d;
  }
  function send() {
    if (busy) return;
    const text = input.value.trim(); if (!text) return;
    input.value = ''; busy = true;
    add('user', text);
    history.push({role:'user', content:text});
    const out = add('assistant', '');
    vscode.postMessage({type:'chat', history: history});
  }
  window.addEventListener('message', (e) => {
    const m = e.data;
    if (m.type === 'config') { config = m.config; updateInfo(); }
    else if (m.type === 'delta') {
      const nodes = log.querySelectorAll('.msg div');
      if (nodes.length) { nodes[nodes.length-1].textContent += m.text; log.scrollTop = log.scrollHeight; }
    }
    else if (m.type === 'error') { add('error', m.text); busy = false; }
    else if (m.type === 'done') { history.push({role:'assistant', content:m.text}); busy = false; }
  });
  document.getElementById('send').onclick = send;
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } });
  updateInfo();
</script>
</body>
</html>`;
}

function activate(context) {
  context.subscriptions.push(
    vscode.commands.registerCommand("mja-chat.open", () => openChat(context)),
    vscode.commands.registerCommand("mja-chat.setUrl", () => setSetting("serverUrl", "MJA server URL")),
    vscode.commands.registerCommand("mja-chat.setModel", () => setSetting("model", "Model id (blank = server default)")),
    vscode.commands.registerCommand("mja-chat.setToken", () => setSetting("token", "Proxy auth bearer token (blank = none)"))
  );
}

function deactivate() {}

module.exports = { activate, deactivate };
