/* MrJeffAgency AI Chat for Acode — talks to a local MJA server */
(function () {
  "use strict";

  const ID = "mrjeffagency.mja-chat";
  const K_URL = ID + ".url";
  const K_MODEL = ID + ".model";
  const K_TOKEN = ID + ".token";

  let page = null;
  let messages = [];          // {role, content}
  let busy = false;
  let controller = null;      // AbortController for active stream
  let models = [];

  const url = () => localStorage.getItem(K_URL) || "http://127.0.0.1:8083";
  const model = () => localStorage.getItem(K_MODEL) || "";
  const token = () => localStorage.getItem(K_TOKEN) || "";

  const esc = (s) => String(s).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
  const el = (tag, css, html) => {
    const e = document.createElement(tag);
    if (css) e.style.cssText = css;
    if (html != null) e.innerHTML = html;
    return e;
  };
  const btn = (label, fn, primary) => {
    const b = el("button",
      "padding:8px 14px;border:0;border-radius:8px;font-size:14px;cursor:pointer;" +
      (primary
        ? "background:var(--primary-color,#39f);color:var(--primary-text-color,#fff)"
        : "background:var(--secondary-color,#555);color:var(--secondary-text-color,#fff)"),
      label);
    b.onclick = fn;
    return b;
  };

  function headers() {
    const h = { "Content-Type": "application/json" };
    if (token()) h["Authorization"] = "Bearer " + token();
    return h;
  }

  async function loadModels() {
    try {
      const r = await fetch(url().replace(/\/$/, "") + "/v1/models", { headers: headers() });
      if (!r.ok) throw new Error("HTTP " + r.status);
      const d = await r.json();
      models = (d.data || []).map((m) => m.id).filter(Boolean);
    } catch (e) {
      models = [];
    }
  }

  function render() {
    if (!page) return;
    const body = page.body;
    body.innerHTML = "";
    body.style.cssText = "height:100%;display:flex;flex-direction:column;padding:10px;box-sizing:border-box";

    const bar = el("div", "display:flex;gap:6px;align-items:center;margin-bottom:8px;flex:0 0 auto;flex-wrap:wrap");
    const modelLabel = el("span", "font-size:12px;opacity:.8", "Model:");
    const sel = el("select", "padding:6px;border-radius:6px;background:var(--input-color,#222);color:var(--secondary-text-color,#eee);max-width:60%");
    const none = new Option("(server default)", "");
    sel.append(none);
    models.forEach((m) => sel.append(new Option(m, m)));
    sel.value = model();
    sel.onchange = () => { localStorage.setItem(K_MODEL, sel.value); };
    bar.append(modelLabel, sel,
      btn("Refresh", async () => { await loadModels(); render(); }),
      btn("Insert into editor", insertLast),
      btn("Send", send, true),
      busy ? btn("Stop", stop) : el("span", ""));

    const log = el("div",
      "flex:1;overflow:auto;border:1px solid var(--divider-color,#444);border-radius:8px;padding:10px;" +
      "font-size:14px;line-height:1.5;background:var(--primary-color)");
    if (!messages.length) {
      log.append(el("p", "opacity:.7", "Ask anything — your models come from MJA at " + esc(url()) + "."));
    }
    messages.forEach((m) => {
      const wrap = el("div", "margin:6px 0");
      wrap.append(el("b", "display:block;font-size:12px;opacity:.7", m.role === "user" ? "You" : "MJA"));
      wrap.append(el("div", "white-space:pre-wrap;word-break:break-word", esc(m.content)));
      log.append(wrap);
    });
    log.scrollTop = log.scrollHeight;

    const inputRow = el("div", "display:flex;gap:6px;margin-top:8px;flex:0 0 auto");
    const input = el("textarea",
      "flex:1;min-height:56px;max-height:140px;padding:8px;border-radius:8px;border:1px solid var(--divider-color,#444);" +
      "background:var(--input-color,#222);color:var(--secondary-text-color,#eee);resize:vertical;font-size:14px");
    input.placeholder = "Type a message…";
    input.value = draft;
    input.oninput = () => { draft = input.value; };
    input.onkeydown = (e) => {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
    };
    inputRow.append(input);
    body.append(bar, log, inputRow);
    setTimeout(() => input.focus(), 50);
  }

  let draft = "";

  function insertLast() {
    const last = [...messages].reverse().find((m) => m.role === "assistant" && m.content.trim());
    if (!last) { window.toast && window.toast("No reply to insert yet", 2000); return; }
    let text = last.content.trim();
    // Strip a single surrounding markdown code fence so code is inserted cleanly.
    const fence = text.match(/^```[a-zA-Z0-9_+-]*\n([\s\S]*?)\n```$/);
    if (fence) text = fence[1];
    try {
      const ed = editorManager.editor;
      const session = ed.session;
      const cursor = ed.selection.getCursor();
      session.insert(cursor, text);
      ed.focus();
      window.toast && window.toast("Inserted into editor", 2000);
    } catch (e) {
      window.toast && window.toast("Insert failed: " + ((e && e.message) || e), 3000);
    }
  }

  function stop() {
    if (controller) controller.abort();
    controller = null;
    busy = false;
    render();
  }

  async function send() {
    if (busy) return;
    const text = draft.trim();
    if (!text) return;
    draft = "";
    messages.push({ role: "user", content: text });
    messages.push({ role: "assistant", content: "" });
    busy = true;
    render();

    controller = new AbortController();
    try {
      const body = {
        model: model() || undefined,
        messages: messages.filter((m) => m.content).map((m) => ({ role: m.role, content: m.content })),
        stream: true,
      };
      const r = await fetch(url().replace(/\/$/, "") + "/v1/chat/completions", {
        method: "POST",
        headers: headers(),
        body: JSON.stringify(body),
        signal: controller.signal,
      });
      if (!r.ok) {
        const t = await r.text();
        throw new Error("HTTP " + r.status + ": " + t.slice(0, 300));
      }
      const reader = r.body.getReader();
      const dec = new TextDecoder();
      let buf = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        let i;
        while ((i = buf.indexOf("\n")) >= 0) {
          const line = buf.slice(0, i).trim();
          buf = buf.slice(i + 1);
          if (!line.startsWith("data:")) continue;
          const data = line.slice(5).trim();
          if (data === "[DONE]") continue;
          try {
            const obj = JSON.parse(data);
            const delta = obj.choices && obj.choices[0] && obj.choices[0].delta;
            if (delta && delta.content) {
              messages[messages.length - 1].content += delta.content;
              render();
            }
          } catch (_) { /* ignore non-JSON frame */ }
        }
      }
    } catch (e) {
      const msg = (e && e.name === "AbortError") ? "" : "Error: " + ((e && e.message) || e);
      messages[messages.length - 1].content += (messages[messages.length - 1].content ? "\n\n" : "") + msg;
    } finally {
      controller = null;
      busy = false;
      render();
    }
  }

  async function open() {
    if (!page) { window.toast && window.toast("Plugin page not ready — restart Acode", 3000); return; }
    try { acode.require("sidebar").hide(); } catch (_) {}
    if (page.settitle) page.settitle("MrJeffAgency AI Chat");
    else if (page.setTitle) page.setTitle("MrJeffAgency AI Chat");
    page.onhide = () => { page = null; };
    await loadModels();
    render();
    page.show();
  }

  async function setUrl() {
    const prompt = acode.require("prompt");
    const v = await prompt("MJA server URL", url(), "text", { placeholder: "http://127.0.0.1:8083" });
    if (v) { localStorage.setItem(K_URL, v.replace(/\/$/, "")); await loadModels(); if (page) render(); }
  }

  async function setModel() {
    const prompt = acode.require("prompt");
    if (!models.length) await loadModels();
    const v = await prompt("Model id (blank = server default)\n\n" + models.join("\n"), model(), "text");
    if (v != null) { localStorage.setItem(K_MODEL, v.trim()); if (page) render(); }
  }

  async function setToken() {
    const prompt = acode.require("prompt");
    const v = await prompt("Proxy auth bearer token (blank = none)", token(), "text");
    if (v != null) { localStorage.setItem(K_TOKEN, v.trim()); if (page) render(); }
  }

  /* ---------- sidebar ---------- */
  const SB_ID = "mja-chat";
  const SB_ICON = "mja-chat-sb-icon";
  let styleEl = null;

  function addSidebar() {
    const svg = encodeURIComponent(
      "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'><path fill='currentColor' d='M4 3h16a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1H9l-5 4V4a1 1 0 0 1 1-1z'/></svg>"
    );
    styleEl = document.createElement("style");
    styleEl.textContent =
      `.icon.${SB_ICON}{display:inline-block;background-color:currentColor;` +
      `-webkit-mask:url("data:image/svg+xml,${svg}") center/70% no-repeat;` +
      `mask:url("data:image/svg+xml,${svg}") center/70% no-repeat}` +
      `.icon.${SB_ICON}:before{content:none}`;
    document.head.append(styleEl);

    acode.require("sidebarApps").add(SB_ICON, SB_ID, "MJA Chat", (container) => {
      container.style.cssText = "padding:16px;text-align:center";
      container.innerHTML = "";
      const mk = (t, fn) => {
        const b = document.createElement("button");
        b.textContent = t;
        b.style.cssText = "display:block;width:100%;margin:8px 0;padding:10px;border:0;border-radius:8px;background:var(--primary-color);color:var(--primary-text-color);filter:brightness(1.3)";
        b.onclick = fn;
        return b;
      };
      container.append(
        el("h3", "", "MrJeffAgency AI Chat"),
        el("p", "font-size:13px;opacity:.8", "Chat with MJA models inside Acode."),
        mk("Open chat", open),
        mk("Set server URL", setUrl),
        mk("Set model", setModel),
        mk("Set token", setToken)
      );
    });
  }

  if (window.acode) {
    acode.setPluginInit(ID, async (baseUrl, $page) => {
      page = $page;
      try { addSidebar(); } catch (e) { console.error("MJA sidebar:", e); }
      const c = editorManager.editor.commands;
      c.addCommand({ name: "mja-open", description: "MJA Chat: Open", exec: open });
      c.addCommand({ name: "mja-url", description: "MJA Chat: Set server URL", exec: setUrl });
      c.addCommand({ name: "mja-model", description: "MJA Chat: Set model", exec: setModel });
      c.addCommand({ name: "mja-token", description: "MJA Chat: Set token", exec: setToken });
    });
    acode.setPluginUnmount(ID, () => {
      try { acode.require("sidebarApps").remove(SB_ID); } catch (_) {}
      if (styleEl) styleEl.remove();
      const c = editorManager.editor.commands;
      ["mja-open", "mja-url", "mja-model", "mja-token"].forEach((n) => c.removeCommand(n));
      if (controller) controller.abort();
    });
  }
})();
