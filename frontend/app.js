(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const el = {
    library: $("library"), backdrop: $("backdrop"), menuBtn: $("menuBtn"),
    dropzone: $("dropzone"), fileInput: $("fileInput"), uploadStatus: $("uploadStatus"),
    shelf: $("shelf"), shelfEmpty: $("shelfEmpty"), count: $("count"), clearAll: $("clearAll"),
    aiStatus: $("aiStatus"), thread: $("thread"), quick: $("quick"), composer: $("composer"),
    question: $("question"), send: $("send"), hint: $("hint"), scopeTitle: $("scopeTitle"),
    scopeMeta: $("scopeMeta"), newChat: $("newChat"),
  };

  const STARTERS = [
    { label: "Summary", q: "Summarize this paper." },
    { label: "Problem", q: "What problem does this paper solve?" },
    { label: "Methodology", q: "What methodology is used?" },
    { label: "Data and algorithms", q: "What datasets and algorithms are used?" },
    { label: "Key findings", q: "What are the key findings?" },
    { label: "Limits and future work", q: "What limitations and future work are mentioned?" },
  ];

  const state = { docs: [], selected: new Set(), history: [], busy: false, aiConfigured: true, hasMessages: false };

  /* ---------------- helpers ---------------- */
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const title = (name) => name.replace(/\.pdf$/i, "");
  const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;

  async function api(path, options) {
    let res;
    try { res = await fetch(path, options); }
    catch { throw new Error("Can't reach the server. Is it running?"); }
    let body = null;
    try { body = await res.json(); } catch { /* non-JSON */ }
    if (!res.ok) {
      const d = body && body.detail;
      throw new Error(typeof d === "string" ? d : "Request failed. Please try again.");
    }
    return body;
  }

  function setHint(text, warn = false) {
    el.hint.textContent = text || "";
    el.hint.classList.toggle("warn", warn);
  }

  /* ---------------- markdown (small, safe) ---------------- */
  function inline(s, ids) {
    return s
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/(^|[^*\w])\*([^*\s][^*]*?)\*(?![*\w])/g, "$1<em>$2</em>")
      .replace(/\[(\d+)\]/g, (m, n) =>
        ids.has(+n) ? `<button type="button" class="cite" data-n="${n}" aria-label="Show source ${n}">${n}</button>` : "");
  }
  function markdown(text, ids) {
    const lines = esc(text).split(/\r?\n/);
    const out = []; let list = null; let para = [];
    const flushPara = () => { if (para.length) { out.push(`<p>${inline(para.join(" "), ids)}</p>`); para = []; } };
    const flushList = () => { if (list) { out.push(`</${list}>`); list = null; } };
    for (const raw of lines) {
      const line = raw.trimEnd();
      let m;
      if (!line.trim()) { flushPara(); flushList(); continue; }
      if ((m = line.match(/^#{1,4}\s+(.*)$/))) { flushPara(); flushList(); out.push(`<h3>${inline(m[1], ids)}</h3>`); continue; }
      if ((m = line.match(/^\s*[-*•]\s+(.*)$/))) {
        flushPara(); if (list !== "ul") { flushList(); out.push("<ul>"); list = "ul"; }
        out.push(`<li>${inline(m[1], ids)}</li>`); continue;
      }
      if ((m = line.match(/^\s*\d+[.)]\s+(.*)$/))) {
        flushPara(); if (list !== "ol") { flushList(); out.push("<ol>"); list = "ol"; }
        out.push(`<li>${inline(m[1], ids)}</li>`); continue;
      }
      flushList(); para.push(line.trim());
    }
    flushPara(); flushList();
    return out.join("");
  }

  /* ---------------- library ---------------- */
  function renderShelf() {
    el.count.textContent = state.docs.length;
    el.shelfEmpty.hidden = state.docs.length > 0;
    el.clearAll.hidden = state.docs.length === 0;
    el.shelf.innerHTML = state.docs.map((d) => `
      <li class="paper ${state.selected.has(d.id) ? "on" : ""}" data-id="${d.id}">
        <input type="checkbox" ${state.selected.has(d.id) ? "checked" : ""} aria-label="Ask about ${esc(title(d.name))}">
        <div>
          <div class="paper-name"><span>${esc(title(d.name))}</span></div>
          <div class="paper-meta">${plural(d.pages, "page")} · ${plural(d.chunks, "passage")}</div>
        </div>
        <button class="icon-btn" data-del="${d.id}" aria-label="Remove ${esc(d.name)}" title="Remove">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg>
        </button>
      </li>`).join("");
    renderScope();
    renderStarters();
    if (!state.hasMessages) renderHero();
  }

  function renderScope() {
    const total = state.docs.length, sel = state.selected.size;
    if (!total) { el.scopeTitle.textContent = "Ask your papers"; el.scopeMeta.textContent = "Answers come only from the documents you upload."; return; }
    if (!sel) { el.scopeTitle.textContent = "No paper selected"; el.scopeMeta.textContent = "Tick at least one paper on the shelf to ask about it."; return; }
    const names = state.docs.filter((d) => state.selected.has(d.id)).map((d) => title(d.name));
    el.scopeTitle.textContent = sel === 1 ? names[0] : `Asking across ${sel} papers`;
    el.scopeMeta.textContent = sel === 1 ? "Answers cite the page they came from." : names.join(" · ");
  }

  function renderStarters() {
    el.quick.hidden = !state.docs.length || !state.hasMessages;
    el.quick.innerHTML = STARTERS.map((s) => `<button type="button" class="chip" data-q="${esc(s.q)}">${esc(s.label)}</button>`).join("");
  }

  function renderHero() {
    if (state.docs.length === 0) {
      el.thread.innerHTML = `<div class="col hero">
        <h2>Ask your papers anything.</h2>
        <p>Upload one or more research papers and ask about their <span class="hl">methods, data, findings and limits</span>. Every answer shows the document and page it came from, and if your papers don't say, it tells you so.</p>
        <button class="primary" type="button" data-pick>Choose PDF files</button></div>`;
    } else {
      el.thread.innerHTML = `<div class="col hero">
        <h2>What would you like to know?</h2>
        <p>Start with one of these, or type your own question below.</p>
        <div class="starters">${STARTERS.map((s) => `<button type="button" class="starter" data-q="${esc(s.q)}"><b>${esc(s.label)}</b><span>${esc(s.q)}</span></button>`).join("")}</div></div>`;
    }
  }

  async function loadDocs(selectNew) {
    const data = await api("/api/documents");
    const before = new Set(state.docs.map((d) => d.id));
    state.docs = data.documents;
    const ids = new Set(state.docs.map((d) => d.id));
    state.selected = new Set([...state.selected].filter((id) => ids.has(id)));
    state.docs.forEach((d) => { if (selectNew && !before.has(d.id)) state.selected.add(d.id); });
    renderShelf();
  }

  /* ---------------- upload ---------------- */
  async function upload(fileList) {
    const files = [...fileList];
    if (!files.length) return;
    el.uploadStatus.innerHTML = `<div class="up-row"><div class="spinner"></div><div><b>Indexing ${plural(files.length, "file")}…</b><span class="msg">Reading pages, splitting text and building embeddings. Large papers take a little longer.</span></div></div>`;
    const form = new FormData();
    files.forEach((f) => form.append("files", f, f.name));
    try {
      const data = await api("/api/documents", { method: "POST", body: form });
      el.uploadStatus.innerHTML = data.results.map((r) => r.status === "indexed"
        ? `<div class="up-row ok"><div><b>${esc(r.name)}</b><span class="msg">Ready: ${plural(r.document.pages, "page")}, ${plural(r.document.chunks, "passage")} indexed.</span></div></div>`
        : `<div class="up-row err"><div><b>${esc(r.name)}</b><span class="msg">${esc(r.error)}</span></div></div>`).join("");
      await loadDocs(true);
      if (data.indexed) setTimeout(() => { if (!el.uploadStatus.querySelector(".err")) el.uploadStatus.innerHTML = ""; }, 6000);
      if (data.indexed && window.innerWidth <= 900) closeDrawer();
    } catch (e) {
      el.uploadStatus.innerHTML = `<div class="up-row err"><div><b>Upload failed</b><span class="msg">${esc(e.message)}</span></div></div>`;
    }
    el.fileInput.value = "";
  }

  async function removeDoc(id) {
    try { await api(`/api/documents/${id}`, { method: "DELETE" }); state.selected.delete(id); await loadDocs(false); }
    catch (e) { el.uploadStatus.innerHTML = `<div class="up-row err"><div><span class="msg">${esc(e.message)}</span></div></div>`; }
  }

  /* ---------------- chat ---------------- */
  function scrollDown() { el.thread.scrollTop = el.thread.scrollHeight; }
  function startThread() {
    if (!state.hasMessages) { state.hasMessages = true; el.thread.innerHTML = '<div class="col" id="msgs"></div>'; el.newChat.hidden = false; renderStarters(); }
    return $("msgs");
  }
  function addNode(html, cls) {
    const box = startThread(); const d = document.createElement("div");
    d.className = `msg ${cls}`; d.innerHTML = html; box.appendChild(d); scrollDown(); return d;
  }

  function sourceBlock(sources) {
    const buttons = sources.map((s) => `<button type="button" class="src" data-n="${s.id}" aria-expanded="false">
        <span class="n">${s.id}</span><span class="doc" title="${esc(s.document)}">${esc(title(s.document))}</span>
        <span class="pg">${s.page ? "p. " + s.page : "page n/a"}</span></button>`).join("");
    const cards = sources.map((s) => `<div class="evidence" data-ev="${s.id}"><div><div class="ev-card">
        <div class="ev-top"><b>${esc(s.document)}</b><span>${s.page ? "Page " + s.page : "Page not available"}</span></div>
        <p class="ev-text"><span class="marker">${esc(s.snippet)}</span></p></div></div></div>`).join("");
    return `<div class="sources"><span class="label">Sources</span>${buttons}</div>${cards}`;
  }

  function toggleSource(root, n) {
    const card = root.querySelector(`[data-ev="${n}"]`); if (!card) return;
    const open = !card.classList.contains("open");
    root.querySelectorAll(".evidence.open").forEach((c) => { if (c !== card) c.classList.remove("open"); });
    card.classList.toggle("open", open);
    root.querySelectorAll(".src, .cite").forEach((b) => {
      const on = open && b.dataset.n === String(n);
      b.classList.toggle("on", on); if (b.classList.contains("src")) b.setAttribute("aria-expanded", on);
    });
  }

  function renderAnswer(node, data) {
    if (!data.found) {
      node.innerHTML = `<div class="notfound"><div class="glyph">∅</div><div><b>Not in your papers</b><span>${esc(data.answer)}</span></div></div>`;
      return;
    }
    const ids = new Set(data.sources.map((s) => s.id));
    node.innerHTML = `<div class="answer">${markdown(data.answer, ids)}</div>${sourceBlock(data.sources)}
      <div class="tools"><span>Read ${plural(data.passages_read, "passage")} from ${plural(data.documents_searched, "paper")}</span><button type="button" data-copy>Copy answer</button></div>`;
    node._plain = data.answer.replace(/\[\d+\]/g, "").replace(/\s+\n/g, "\n");
  }

  async function ask(question) {
    question = (question || "").trim();
    if (state.busy) return;
    if (!question) { setHint("Type a question first.", true); el.question.focus(); return; }
    if (!state.docs.length) { setHint("No document uploaded yet. Add a research paper (PDF) first.", true); return; }
    if (!state.selected.size) { setHint("Select at least one paper on the shelf.", true); return; }
    setHint("");
    state.busy = true; el.send.disabled = true;
    addNode(`<div>${esc(question)}</div>`, "you");
    el.question.value = ""; autoGrow();
    const node = addNode('<div class="thinking"><span>Reading your papers…</span></div>', "bot");
    try {
      const data = await api("/api/chat", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, doc_ids: [...state.selected], history: state.history.slice(-6) }),
      });
      renderAnswer(node, data);
      state.history.push({ role: "user", content: question }, { role: "assistant", content: data.found ? data.answer.replace(/\[\d+\]/g, "") : "Not available in the uploaded documents." });
    } catch (e) {
      node.innerHTML = `<div class="note-err"><b>Couldn't answer.</b> ${esc(e.message)}</div>`;
    }
    state.busy = false; el.send.disabled = false; scrollDown(); el.question.focus();
  }

  function resetChat() {
    state.history = []; state.hasMessages = false; el.newChat.hidden = true; setHint(""); renderStarters(); renderHero();
  }

  /* ---------------- UI wiring ---------------- */
  function autoGrow() { el.question.style.height = "auto"; el.question.style.height = Math.min(el.question.scrollHeight, 160) + "px"; }
  function openDrawer() { el.library.classList.add("open"); el.backdrop.classList.add("show"); }
  function closeDrawer() { el.library.classList.remove("open"); el.backdrop.classList.remove("show"); }

  el.dropzone.addEventListener("click", () => el.fileInput.click());
  el.dropzone.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); el.fileInput.click(); } });
  el.fileInput.addEventListener("click", (e) => e.stopPropagation());
  el.fileInput.addEventListener("change", () => upload(el.fileInput.files));
  ["dragenter", "dragover"].forEach((t) => document.addEventListener(t, (e) => { e.preventDefault(); el.dropzone.classList.add("drag"); }));
  ["dragleave", "drop"].forEach((t) => document.addEventListener(t, (e) => { e.preventDefault(); if (t === "drop" || e.target === document.documentElement) el.dropzone.classList.remove("drag"); }));
  document.addEventListener("drop", (e) => { if (e.dataTransfer && e.dataTransfer.files.length) upload(e.dataTransfer.files); });

  el.shelf.addEventListener("click", (e) => {
    const del = e.target.closest("[data-del]"); if (del) { removeDoc(del.dataset.del); return; }
    const li = e.target.closest(".paper"); if (!li) return;
    if (e.target.tagName !== "INPUT") { const cb = li.querySelector("input"); cb.checked = !cb.checked; }
    const id = li.dataset.id;
    li.querySelector("input").checked ? state.selected.add(id) : state.selected.delete(id);
    li.classList.toggle("on", state.selected.has(id)); renderScope(); setHint("");
  });
  el.clearAll.addEventListener("click", async () => {
    if (!confirm("Remove all uploaded papers?")) return;
    try { await api("/api/documents", { method: "DELETE" }); state.selected.clear(); await loadDocs(false); resetChat(); } catch (e) { alert(e.message); }
  });

  el.thread.addEventListener("click", (e) => {
    const pick = e.target.closest("[data-pick]"); if (pick) { el.fileInput.click(); return; }
    const q = e.target.closest("[data-q]"); if (q) { ask(q.dataset.q); return; }
    const root = e.target.closest(".msg.bot");
    const n = e.target.closest("[data-n]"); if (n && root) { toggleSource(root, n.dataset.n); return; }
    const copy = e.target.closest("[data-copy]");
    if (copy && root) { navigator.clipboard.writeText(root._plain || "").then(() => { copy.textContent = "Copied"; setTimeout(() => (copy.textContent = "Copy answer"), 1500); }); }
  });
  el.quick.addEventListener("click", (e) => { const q = e.target.closest("[data-q]"); if (q) ask(q.dataset.q); });

  el.composer.addEventListener("submit", (e) => { e.preventDefault(); ask(el.question.value); });
  el.question.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); ask(el.question.value); } });
  el.question.addEventListener("input", () => { autoGrow(); if (el.question.value.trim()) setHint(""); });
  el.newChat.addEventListener("click", resetChat);
  el.menuBtn.addEventListener("click", openDrawer);
  el.backdrop.addEventListener("click", closeDrawer);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDrawer(); });

  /* ---------------- boot ---------------- */
  (async function init() {
    renderHero(); renderStarters();
    try {
      const health = await api("/api/health");
      state.aiConfigured = health.ai_configured;
      if (!health.ai_configured) {
        el.aiStatus.hidden = false;
        el.aiStatus.textContent = "Gemini API key missing. Add GOOGLE_API_KEY to your .env file and restart the server.";
      }
      await loadDocs(true);
      state.docs.forEach((d) => state.selected.add(d.id)); renderShelf();
    } catch (e) {
      el.aiStatus.hidden = false; el.aiStatus.textContent = e.message;
    }
  })();
})();
