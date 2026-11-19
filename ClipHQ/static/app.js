// Clip HQ desktop page
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
let META = {presets:{}, layouts:{}, styles:{}, hook_styles:[], campaigns:[]};
let SETTINGS = {};
let lastEvent = null;
let currentClip = null;

async function api(path, opts = {}) {
  const o = {...opts, headers: {"Content-Type": "application/json", ...(opts.headers || {})}};
  if (o.body && typeof o.body !== "string") o.body = JSON.stringify(o.body);
  const r = await fetch(path, o);
  let data = null;
  try { data = await r.json(); } catch { data = null; }
  if (!r.ok) throw new Error((data && data.detail) || r.statusText);
  return data;
}
function toast(msg, kind = "info", ms = 5000) {
  const t = document.createElement("div");
  t.className = "toast " + kind; t.textContent = msg;
  $("#toasts").appendChild(t); setTimeout(() => t.remove(), ms);
}
function fmt(t) { t = Math.max(0, Math.round(t)); const h = Math.floor(t/3600), m = Math.floor(t%3600/60), s = t%60;
  return h ? `${h}:${String(m).padStart(2,"0")}:${String(s).padStart(2,"0")}` : `${m}:${String(s).padStart(2,"0")}`; }
function parseTime(s) { const p = String(s).trim().split(":").map(Number); if (p.some(isNaN)) return NaN;
  return p.reduce((a, b) => a * 60 + b, 0); }
function ago(iso) { const d = (Date.now() - new Date(iso)) / 1000; if (isNaN(d)) return "";
  if (d < 3600) return Math.max(1, Math.round(d/60)) + " min ago"; if (d < 86400) return Math.round(d/3600) + " h ago";
  return Math.round(d/86400) + " days ago"; }
function scoreClass(s) { return s >= 85 ? "s90" : s >= 70 ? "s70" : s >= 50 ? "s50" : "s0"; }
function fillSelect(sel, entries, value) {
  sel.innerHTML = entries.map(([v, l]) => `<option value="${esc(v)}">${esc(l)}</option>`).join("");
  if (value !== undefined && value !== null) sel.value = value;
}
function campaignOptions() { return [["", "— none —"], ...META.campaigns.map(c => [c.id, c.name])]; }

// ---------- tabs ----------
$$("#tabs button").forEach(b => b.onclick = () => showTab(b.dataset.tab));
function showTab(name) {
  $$("#tabs button").forEach(b => b.classList.toggle("active", b.dataset.tab === name));
  $$(".tab").forEach(t => t.classList.toggle("active", t.id === "tab-" + name));
  location.hash = name;
  ({review: loadClips, exports: loadExports, watcher: loadWatcher, record: loadRecorder, campaigns: loadCampaigns, settings: loadSettings}[name] || (()=>{}))();
}
$$("[data-close]").forEach(b => b.onclick = () => b.closest(".modal").classList.remove("open"));

// ---------- notifications ----------
$("#btn-notify").onclick = async () => {
  if (!("Notification" in window)) return toast("This browser can't show notifications");
  const p = await Notification.requestPermission();
  toast(p === "granted" ? "Desktop pop-ups are on" : "Pop-ups blocked by the browser");
};
function popup(title, body) {
  if ("Notification" in window && Notification.permission === "granted" && document.hidden) new Notification(title, {body});
}

// ---------- status polling ----------
async function poll() {
  try {
    const s = await api("/api/status?since=" + (lastEvent ?? 0));
    if (lastEvent === null) lastEvent = s.last_event;
    else {
      for (const e of s.events.slice().reverse()) {
        if (e.id <= lastEvent) continue;
        toast(e.message, e.kind);
        if (["clips", "upload", "error"].includes(e.kind)) popup("Clip HQ", e.message);
        if (e.kind === "clips" && $("#tab-review").classList.contains("active")) loadClips();
        if (e.kind === "upload" && $("#tab-watcher").classList.contains("active")) loadWatcher();
      }
      lastEvent = Math.max(lastEvent, s.last_event);
    }
    renderQueue(s.videos);
    const c = s.counts;
    $("#badge-review").textContent = (c.ready || 0) + (c.rendering || 0) + (c.queued || 0) + (c.new || 0) || "";
    $("#badge-exports").textContent = c.approved || "";
    $("#badge-watcher").textContent = s.new_uploads || "";
    const working = s.videos.filter(v => v.status === "working")[0];
    const queued = s.videos.filter(v => v.status === "queued").length;
    $("#queue-mini").textContent = working ? `⚙ ${working.stage}` + (queued ? ` (+${queued} waiting)` : "") : (queued ? `${queued} waiting` : "");
    updateRecorder(s.recorder);
  } catch (e) { $("#queue-mini").textContent = "⚠ app not responding"; }
}
setInterval(poll, 2500);

// ---------- process ----------
function renderQueue(videos) {
  const el = $("#queue");
  if (!videos.length) { el.innerHTML = `<div class="empty">Nothing queued yet.</div>`; return; }
  const open = new Set($$("details[data-vid]", el).filter(d => d.open).map(d => d.dataset.vid));
  el.innerHTML = videos.map(v => {
    const pct = Math.round((v.progress || 0) * 100);
    const o = v.options || {};
    const btns = v.status === "working" || v.status === "queued" ? `<button class="ghost small" onclick="cancelVid(${v.id})">Cancel</button>` :
      v.status === "error" || v.status === "cancelled" ? `<button class="ghost small" onclick="retryVid(${v.id})">Retry</button>` :
      o.scout ? "" : `<button class="ghost small" onclick="openReview(${v.id})">Review clips</button>`;
    return `<div class="qitem">
      <div class="row between"><div class="name">${esc(v.name)}</div><span class="status ${v.status}">${v.status}</span></div>
      <div class="hint">${esc(META.presets[o.preset]?.label || o.preset || "")}${o.scout ? " · scout " + o.speed + "x" : ""}${o.source ? " · from " + o.source : ""}</div>
      ${v.status === "working" || v.status === "queued" ? `<div class="bar"><i style="width:${pct}%"></i></div><div class="hint">${esc(v.stage || "Waiting...")} ${v.status === "working" ? "· " + pct + "% overall" : ""}</div>` : `<div class="hint">${esc(v.stage || "")}</div>`}
      ${v.error ? `<div class="hint" style="color:var(--bad)">${esc(v.error)}</div>` : ""}
      <div class="row" style="margin-top:8px">${btns}
        ${v.status === "done" ? `<button class="ghost small" onclick="markExample(${v.id})">⭐ Mark a good moment</button>` : ""}
        <button class="ghost small" onclick="deleteVid(${v.id})">Remove</button></div>
      ${o.scout && v.status === "done" ? `<details data-vid="${v.id}" ${open.has(String(v.id)) ? "open" : ""}><summary>Scout timestamps</summary><div id="scout-${v.id}">Loading…</div></details>` : ""}
    </div>`;
  }).join("");
  videos.filter(v => v.options?.scout && v.status === "done").forEach(v => loadScout(v.id));
}
const scoutCache = {};
async function loadScout(id) {
  if (!scoutCache[id]) {
    const all = await api("/api/videos");
    all.forEach(v => { if (v.scout?.length) scoutCache[v.id] = v.scout; });
  }
  const list = scoutCache[id] || [];
  const el = $("#scout-" + id); if (!el) return;
  const text = list.map(m => `${m.from}–${m.to}  (${m.score})  ${m.kind}: ${m.reason}`).join("\n");
  el.innerHTML = `<p class="hint">Times are in the ORIGINAL (normal speed) video. Go back to these times and record just these bits.</p>
    <table class="scout">${list.map(m => `<tr><td><b>${m.from}–${m.to}</b></td><td><span class="score ${scoreClass(m.score)}">${m.score}</span></td><td>${esc(m.kind)}<br><span class="hint">${esc(m.reason)}</span><br><i class="hint">"${esc(m.text)}"</i></td></tr>`).join("")}</table>
    <button class="ghost small" onclick='navigator.clipboard.writeText(${JSON.stringify(text)});toast("Copied")'>Copy list</button>`;
}
window.cancelVid = async id => { await api(`/api/videos/${id}/cancel`, {method: "POST"}); poll(); };
window.retryVid = async id => { await api(`/api/videos/${id}/retry`, {method: "POST"}); poll(); };
window.deleteVid = async id => { if (confirm("Remove this video from the list? (Its clips stay.)")) { await api(`/api/videos/${id}`, {method: "DELETE"}); poll(); } };
window.openReview = id => { showTab("review"); $("#r-video").value = id; loadClips(); };
window.markExample = id => { $("#m-example").classList.add("open"); $("#m-example").dataset.vid = id; $("#x-msg").textContent = ""; };
$("#x-save").onclick = async () => {
  const t = parseTime($("#x-time").value);
  if (isNaN(t)) return toast("Type a time like 12:40", "error");
  $("#x-msg").textContent = "Learning…";
  try {
    const r = await api(`/api/videos/${$("#m-example").dataset.vid}/examples`, {method: "POST", body: {t, label: $("#x-label").value}});
    $("#x-msg").textContent = "Got it! Signal boosts now: " + JSON.stringify(r.weights) + (r.phrases.length ? " · learned words: " + r.phrases.join(", ") : "");
  } catch (e) { $("#x-msg").textContent = e.message; }
};

$("#p-start").onclick = async () => {
  const path = $("#p-path").value.trim();
  if (!path) return toast("Pick a video first (Browse…)", "error");
  const body = {preset: $("#p-preset").value, campaign_id: $("#p-campaign").value || null, layout: $("#p-layout").value,
    max_clips: +$("#p-max").value, min_clip: +$("#p-min-len").value, max_clip: +$("#p-max-len").value,
    scout: $("#p-scout").checked, speed: $("#p-scout").checked ? +$("#p-speed").value : 1, remember_for_drop: $("#p-remember").checked};
  if ($("#p-path").dataset.folder === "1") body.folder = path; else body.path = path;
  try { const r = await api("/api/process", {method: "POST", body}); toast(`Queued ${r.queued.length} video(s)`, "clips"); poll(); }
  catch (e) { toast(e.message, "error"); }
};
$("#p-path").oninput = () => { $("#p-path").dataset.folder = ""; $("#p-picked").textContent = ""; };

// file browser
let browsePath = "";
$("#p-browse").onclick = () => { $("#m-browse").classList.add("open"); browse(browsePath); };
async function browse(p) {
  try {
    const r = await api("/api/browse?path=" + encodeURIComponent(p));
    browsePath = r.path; $("#b-path").value = r.path; $("#b-up").dataset.parent = r.parent;
    $("#b-list").innerHTML = r.dirs.map(d => `<div data-dir="${esc(d)}">📁 ${esc(d.split(/[\\/]/).filter(Boolean).pop() || d)}</div>`).join("") +
      r.files.map(f => `<div data-file="${esc(f.path)}">🎬 ${esc(f.name)} <span class="hint">${(f.size/1e6).toFixed(0)} MB</span></div>`).join("") ||
      `<div class="hint">No videos here.</div>`;
    $$("#b-list [data-dir]").forEach(d => d.onclick = () => browse(d.dataset.dir));
    $$("#b-list [data-file]").forEach(d => d.onclick = () => {
      $("#p-path").value = d.dataset.file; $("#p-path").dataset.folder = ""; $("#p-picked").textContent = "";
      $("#m-browse").classList.remove("open"); });
  } catch (e) { toast(e.message, "error"); }
}
$("#b-up").onclick = () => browse($("#b-up").dataset.parent || "");
$("#b-path").onchange = () => browse($("#b-path").value);
$("#b-folder").onclick = () => { if (!browsePath) return; $("#p-path").value = browsePath; $("#p-path").dataset.folder = "1";
  $("#p-picked").textContent = "Every video in this folder will be queued."; $("#m-browse").classList.remove("open"); };

// ---------- review ----------
$("#r-video").onchange = loadClips; $("#r-status").onchange = loadClips;
async function loadVideoFilter() {
  const vids = await api("/api/videos");
  const cur = $("#r-video").value;
  fillSelect($("#r-video"), [["0", "All videos"], ...vids.filter(v => !v.options.scout).map(v => [v.id, v.name])], cur || "0");
}
async function loadClips() {
  await loadVideoFilter();
  const clips = await api(`/api/clips?status=${$("#r-status").value}&video_id=${$("#r-video").value || 0}`);
  const el = $("#clips");
  if (!clips.length) { el.innerHTML = `<div class="empty">No clips here yet. Process a video first.</div>`; return; }
  el.innerHTML = clips.map(c => `<div class="clip">
    <div class="media" onclick="editClip(${c.id})">
      ${c.url ? `<video src="${c.url}" poster="${c.thumb_url}" preload="none" muted loop playsinline onmouseenter="this.play()" onmouseleave="this.pause()"></video>` : ""}
      ${c.status !== "ready" && c.status !== "approved" ? `<div class="overlay">${c.status === "error" ? "⚠ " + esc(c.render_error).slice(0, 120) : "Rendering…"}</div>` : ""}
      <span class="badge score ${scoreClass(c.score)}">${c.score}</span><span class="kind">${esc(c.kind)}</span>
    </div>
    <div class="body">
      <div class="hook">${esc(c.hook)}</div>
      <div class="reason">${esc(c.reason)}</div>
      <div class="hint">${fmt(c.start)}–${fmt(c.end)} · ${Math.round(c.end - c.start)}s · ${esc(META.layouts[c.layout] || c.layout)}</div>
      <div class="acts">${c.status === "approved" ? `<button disabled>✓ Approved</button>` : `<button class="ok" onclick="approveClip(${c.id})" ${c.status !== "ready" ? "disabled" : ""}>✓</button>`}
        <button onclick="editClip(${c.id})">Edit</button><button class="danger" onclick="deleteClip(${c.id})">✕</button></div>
    </div></div>`).join("");
}
window.approveClip = async id => { try { await api(`/api/clips/${id}/approve`, {method: "POST"}); toast("Approved: saved to the approved folder", "clips"); loadClips(); } catch (e) { toast(e.message, "error"); } };
window.deleteClip = async id => { if (!confirm("Delete this clip?")) return; await api(`/api/clips/${id}/delete`, {method: "POST"}); $("#m-edit").classList.remove("open"); loadClips(); };

window.editClip = async id => {
  const c = await api(`/api/clips/${id}`);
  currentClip = c;
  $("#m-edit").classList.add("open");
  $("#e-title").textContent = `${c.video_name} · ${fmt(c.start)}–${fmt(c.end)}`;
  const v = $("#e-video"); v.src = c.url ? c.url + "?t=" + Date.now() : ""; v.poster = c.thumb_url;
  $("#e-state").textContent = c.status === "ready" || c.status === "approved" ? "" : c.status === "error" ? "⚠ " + c.render_error : "Rendering… this preview updates when it's done.";
  $("#e-score").textContent = c.score; $("#e-score").className = "score " + scoreClass(c.score);
  $("#e-reason").textContent = c.reason;
  $("#e-hook").value = c.hook || "";
  $("#e-start").value = c.start; $("#e-end").value = c.end;
  fillSelect($("#e-layout"), Object.entries(META.layouts).filter(([k]) => k !== "auto"), c.layout);
  fillSelect($("#e-style"), Object.entries(META.styles), c.style);
  fillSelect($("#e-hookstyle"), META.hook_styles.map((h, i) => [i, `Style ${i + 1}`]), c.edits.hook_style ?? 0);
  $("#e-capy").value = c.edits.caption_y ?? (c.layout === "stacked" ? 0.58 : 0.66);
  $("#e-captions").checked = c.edits.captions_on !== false;
  renderExtras(c.edits.extra_texts || []);
  fillSelect($("#e-campaign"), campaignOptions(), c.edits.campaign_id || "");
  $("#e-titletext").value = c.title; titleLen();
  $("#e-desc").value = c.description;
  renderChecklist(c.edits.checklist || [], c.edits.checked || []);
  $("#e-approve").disabled = c.status === "approved";
  $("#e-approve").textContent = c.status === "approved" ? "✓ Approved" : "✓ Approve";
  $("#e-frame").src = `/api/videos/${c.video_id}/frame?t=${(c.start + c.end) / 2}`;
  drawFacecam(c.edits.facecam);
};
function renderExtras(list) {
  $("#e-extras").innerHTML = list.map((x, i) => `<div class="extra"><input value="${esc(x.text)}" data-k="text" data-i="${i}" placeholder="Text">
    <input type="number" step="0.5" value="${x.start}" data-k="start" data-i="${i}" title="Show from (s into clip)">
    <input type="number" step="0.5" value="${x.end}" data-k="end" data-i="${i}" title="Hide at (s into clip)">
    <button class="ghost small" onclick="this.parentElement.remove()">✕</button></div>`).join("");
}
function readExtras() {
  return $$("#e-extras .extra").map(row => ({text: $("[data-k=text]", row).value, start: +$("[data-k=start]", row).value, end: +$("[data-k=end]", row).value})).filter(x => x.text.trim());
}
$("#e-add-extra").onclick = () => { const cur = readExtras(); const d = (currentClip.end - currentClip.start);
  cur.push({text: "", start: Math.round(d / 2), end: Math.round(d / 2 + 3)}); renderExtras(cur); };
$$("[data-nudge]").forEach(b => b.onclick = () => { const [k, d] = b.dataset.nudge.split(","); const el = $("#e-" + k); el.value = (+el.value + +d).toFixed(1); });
function renderChecklist(items, checked) {
  $("#e-checklist").innerHTML = `<label>Before posting</label>` + items.map((t, i) =>
    `<label class="check"><input type="checkbox" data-ci="${i}" ${checked.includes(i) ? "checked" : ""}> ${esc(t)}</label>`).join("");
  $$("#e-checklist input").forEach(cb => cb.onchange = () => api(`/api/clips/${currentClip.id}`, {method: "PATCH",
    body: {checked: $$("#e-checklist input").filter(x => x.checked).map(x => +x.dataset.ci)}}));
}
function titleLen() { const n = [...$("#e-titletext").value].length; $("#e-title-len").textContent = `${n}/70`; $("#e-title-len").style.color = n > 70 ? "var(--bad)" : ""; }
$("#e-titletext").oninput = titleLen;
$("#e-render").onclick = async () => {
  const body = {hook: $("#e-hook").value, extra_texts: readExtras(), start: +$("#e-start").value, end: +$("#e-end").value,
    layout: $("#e-layout").value, style: $("#e-style").value, hook_style: +$("#e-hookstyle").value, caption_y: +$("#e-capy").value,
    captions_on: $("#e-captions").checked, title: $("#e-titletext").value, description: $("#e-desc").value};
  if (fcBox) body.facecam = fcBox;
  // new hook but untouched title/description: let the app rewrite them to match
  if (body.hook !== currentClip.hook && body.title === currentClip.title && body.description === currentClip.description) {
    delete body.title; delete body.description;
  }
  try { await api(`/api/clips/${currentClip.id}`, {method: "PATCH", body}); toast("Re-rendering… (usually under a minute)"); waitRender(currentClip.id); }
  catch (e) { toast(e.message, "error"); }
};
async function waitRender(id) {
  $("#e-state").textContent = "Rendering…";
  for (let i = 0; i < 200; i++) {
    await new Promise(r => setTimeout(r, 2500));
    const c = await api(`/api/clips/${id}`);
    if (c.status === "ready" || c.status === "error") {
      if (currentClip && currentClip.id === id && $("#m-edit").classList.contains("open")) editClip(id);
      loadClips(); return;
    }
  }
}
$("#e-shuffle").onclick = async () => { await api(`/api/clips/${currentClip.id}/shuffle`, {method: "POST"}); toast("New style: re-rendering"); waitRender(currentClip.id); };
$("#e-example").onclick = async () => {
  const peak = currentClip.edits.peak ?? (currentClip.start + currentClip.end) / 2;
  await api(`/api/videos/${currentClip.video_id}/examples`, {method: "POST", body: {t: peak, label: currentClip.kind}});
  toast("Thanks: Clip HQ will look for more moments like this", "clips");
};
$("#e-savetext").onclick = async () => { await api(`/api/clips/${currentClip.id}`, {method: "PATCH", body: {title: $("#e-titletext").value, description: $("#e-desc").value}}); toast("Saved"); };
$("#e-approve").onclick = async () => { await $("#e-savetext").onclick(); await approveClip(currentClip.id); editClip(currentClip.id); };
$("#e-delete").onclick = () => deleteClip(currentClip.id);
$("#e-campaign").onchange = async () => {
  const c = await api(`/api/clips/${currentClip.id}/apply_campaign`, {method: "POST", body: {campaign_id: $("#e-campaign").value || null}});
  currentClip = c; $("#e-titletext").value = c.title; $("#e-desc").value = c.description; titleLen(); renderChecklist(c.edits.checklist, []);
};

// facecam box drawing
let fcBox = null, fcStart = null;
function drawFacecam(box) {
  fcBox = box || null;
  const el = $("#e-fcbox");
  if (!box) { el.style.display = "none"; return; }
  el.style.display = "block";
  el.style.left = box[0] * 100 + "%"; el.style.top = box[1] * 100 + "%"; el.style.width = box[2] * 100 + "%"; el.style.height = box[3] * 100 + "%";
}
const img = $("#e-frame");
img.addEventListener("pointerdown", e => { e.preventDefault(); const r = img.getBoundingClientRect(); fcStart = [(e.clientX - r.left) / r.width, (e.clientY - r.top) / r.height]; img.setPointerCapture(e.pointerId); });
img.addEventListener("pointermove", e => { if (!fcStart) return; const r = img.getBoundingClientRect();
  const x = Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)), y = Math.min(1, Math.max(0, (e.clientY - r.top) / r.height));
  drawFacecam([Math.min(x, fcStart[0]), Math.min(y, fcStart[1]), Math.abs(x - fcStart[0]), Math.abs(y - fcStart[1])]); });
img.addEventListener("pointerup", () => { fcStart = null; if (fcBox && fcBox[2] > 0.03) { fcBox = fcBox.map(v => +v.toFixed(4)); $("#e-layout").value = "stacked"; toast("Facecam box set. Press Save & re-render."); } });

// ---------- exports ----------
async function loadExports() {
  const clips = await api("/api/clips?status=approved");
  const el = $("#exports");
  if (!clips.length) { el.innerHTML = `<div class="empty">Approve clips in Review and they'll appear here, ready to post.</div>`; return; }
  el.innerHTML = clips.map(c => `<div class="exp">
    <video src="${c.approved_url || c.url}" poster="${c.thumb_url}" controls preload="none" playsinline></video>
    <div>
      <div class="row between"><span class="score ${scoreClass(c.score)}">${c.score}</span><a href="/api/download/${c.id}" download><button class="primary">⬇ Download</button></a></div>
      <label>Title</label><div class="copybox"><input readonly value="${esc(c.title)}"><button class="ghost" onclick="copyText(this)">Copy</button></div>
      <label>Description</label><div class="copybox"><textarea readonly rows="5">${esc(c.description)}</textarea><button class="ghost" onclick="copyText(this)">Copy</button></div>
      <label>Checklist</label>${(c.edits.checklist || []).map((t, i) => `<div class="hint">${(c.edits.checked || []).includes(i) ? "☑" : "☐"} ${esc(t)}</div>`).join("")}
    </div></div>`).join("");
}
window.copyText = btn => { const f = btn.previousElementSibling; navigator.clipboard.writeText(f.value); toast("Copied"); };

// ---------- watcher ----------
async function loadWatcher() {
  const r = await api("/api/channels");
  $("#w-channels").innerHTML = r.channels.map(c => `<div class="chan"><div><b>${esc(c.name)}</b><div class="hint">${c.last_error ? "⚠ " + esc(c.last_error) : "checked " + ago(new Date(c.last_checked * 1000))}</div></div>
    <button class="ghost small" onclick="delChannel(${c.id})">Remove</button></div>`).join("") || `<div class="hint" style="margin-top:12px">No channels yet.</div>`;
  $("#w-uploads").innerHTML = r.uploads.map(u => `<div class="up"><a href="${esc(u.link)}" target="_blank" onclick="seen('${esc(u.video_id)}')"><img src="${esc(u.thumb)}" loading="lazy"></a>
    <div>${u.is_new ? `<span class="new">NEW</span>` : ""}<a href="${esc(u.link)}" target="_blank" onclick="seen('${esc(u.video_id)}')"><b>${esc(u.title)}</b></a>
    <div class="hint">${esc(u.channel_name || "")} · posted ${ago(u.published)} (${new Date(u.published).toLocaleString()})</div></div></div>`).join("") || `<div class="empty">New videos from your channels show up here.</div>`;
}
$("#w-add-btn").onclick = async () => {
  const t = $("#w-add").value.trim(); if (!t) return;
  $("#w-add-btn").disabled = true;
  try { const r = await api("/api/channels", {method: "POST", body: {text: t}}); toast(`Added ${r.name}`); $("#w-add").value = ""; loadWatcher(); }
  catch (e) { toast(e.message, "error"); } finally { $("#w-add-btn").disabled = false; }
};
$("#w-check").onclick = async () => { const r = await api("/api/channels/check", {method: "POST"}); toast(r.new ? `${r.new} new upload(s)` : "No new uploads"); loadWatcher(); };
$("#w-seen").onclick = async () => { await api("/api/uploads/seen", {method: "POST", body: {}}); loadWatcher(); poll(); };
window.seen = id => api("/api/uploads/seen", {method: "POST", body: {video_id: id}});
window.delChannel = async id => { if (confirm("Stop watching this channel?")) { await api(`/api/channels/${id}`, {method: "DELETE"}); loadWatcher(); } };

// ---------- recorder ----------
let recSourcesLoaded = false;
async function loadRecorder() {
  if (!recSourcesLoaded) {
    try {
      const s = await api("/api/recorder/sources");
      fillSelect($("#rec-window"), s.windows.map(w => [w, w]));
      fillSelect($("#rec-device"), (s.audio.dshow || []).map(d => [d, d]));
      fillSelect($("#rec-mic"), [["", "No"], ...(s.audio.dshow || []).map(d => [d, d])]);
      if (!s.audio.loopback) $("#rec-msg").textContent = "⚠ 'What I hear' isn't available: " + (s.audio.loopback_error || "") + " Pick an audio device instead.";
      recSourcesLoaded = true;
    } catch (e) { $("#rec-msg").textContent = e.message; }
  }
  const r = SETTINGS.record || {};
  $("#rec-chunk").value = r.chunk_minutes ?? 20; $("#rec-autostop").value = r.auto_stop_minutes || 180;
  recVis();
}
function recVis() { $("#rec-window-wrap").style.display = $("#rec-target").value === "window" ? "" : "none";
  $("#rec-dev-wrap").style.display = $("#rec-audio").value === "device" ? "" : "none"; }
$("#rec-target").onchange = recVis; $("#rec-audio").onchange = recVis;
$("#rec-start").onclick = async () => {
  const body = {target: $("#rec-target").value, window_title: $("#rec-window").value, audio: $("#rec-audio").value,
    audio_device: $("#rec-device").value, mic_device: $("#rec-mic").value, chunk_minutes: +$("#rec-chunk").value,
    auto_stop_minutes: +$("#rec-autostop").value, preset: $("#rec-preset").value, campaign_id: $("#rec-campaign").value || null,
    auto_process: $("#rec-process").checked, scout: $("#rec-scout").checked, speed: $("#rec-scout").checked ? +$("#rec-speed").value : 1};
  try { await api("/api/recorder/start", {method: "POST", body}); toast("Recording… you can walk away"); poll(); }
  catch (e) { toast(e.message, "error"); }
};
$("#rec-stop").onclick = async () => { $("#rec-stop").disabled = true; toast("Stopping and saving the last chunk…"); await api("/api/recorder/stop", {method: "POST"}); poll(); };
function updateRecorder(r) {
  const on = r.recording;
  $("#rec-start").disabled = on; $("#rec-stop").disabled = !on;
  $("#rec-timer").textContent = fmt(r.elapsed || 0); $("#rec-timer").classList.toggle("on", on);
  $("#badge-rec").textContent = on ? "REC " + fmt(r.elapsed) : "";
  if (r.error) $("#rec-msg").textContent = "⚠ " + r.error;
  else if (on && r.auto_stop_minutes) $("#rec-msg").textContent = `Auto-stops in ${fmt(r.auto_stop_minutes * 60 - r.elapsed)}`;
  $("#rec-chunks").innerHTML = (r.chunks || []).length ? r.chunks.map((c, i) => `<div>✅ Chunk ${i + 1}: ${esc(c)}</div>`).join("") : "Nothing yet.";
}

// ---------- campaigns ----------
async function loadCampaigns() {
  META.campaigns = await api("/api/campaigns");
  $("#c-list").innerHTML = META.campaigns.map(c => `<div class="chan"><div><b>${esc(c.name)}</b> <span class="hint">${esc(c.pay_rate)}</span>
    <div class="hint">${esc(c.hashtags)} · ${esc(c.rules).slice(0, 120)}</div></div>
    <div class="row"><button class="ghost small" onclick='editCampaign(${JSON.stringify(c).replace(/'/g, "&#39;")})'>Edit</button><button class="ghost small" onclick="delCampaign(${c.id})">Delete</button></div></div>`).join("")
    || `<div class="hint">No campaigns yet. Example: Lacy · #Lacy · "Lacy must be the main focus, no logos".</div>`;
  refreshCampaignSelects();
}
function refreshCampaignSelects() { ["#p-campaign", "#rec-campaign"].forEach(s => fillSelect($(s), campaignOptions(), $(s).value)); }
window.editCampaign = c => { $("#c-id").value = c.id; $("#c-name").value = c.name; $("#c-hashtags").value = c.hashtags; $("#c-tags").value = c.tags;
  $("#c-pay").value = c.pay_rate; $("#c-rules").value = c.rules; $("#c-focus").value = c.focus || ""; $("#c-form-title").textContent = "Edit campaign"; };
window.delCampaign = async id => { if (confirm("Delete this campaign?")) { await api(`/api/campaigns/${id}`, {method: "DELETE"}); loadCampaigns(); } };
$("#c-new").onclick = () => { ["#c-id", "#c-name", "#c-hashtags", "#c-tags", "#c-pay", "#c-rules", "#c-focus"].forEach(s => $(s).value = ""); $("#c-form-title").textContent = "New campaign"; };
$("#c-save").onclick = async () => {
  try { await api("/api/campaigns", {method: "POST", body: {id: $("#c-id").value || null, name: $("#c-name").value, hashtags: $("#c-hashtags").value,
    tags: $("#c-tags").value, pay_rate: $("#c-pay").value, rules: $("#c-rules").value, focus: $("#c-focus").value}});
    toast("Campaign saved"); $("#c-new").onclick(); loadCampaigns(); } catch (e) { toast(e.message, "error"); }
};

// ---------- settings ----------
const regStr = r => (r || []).map(x => x.join(",")).join("\n");
const parseRegs = s => s.split("\n").map(l => l.split(",").map(Number)).filter(a => a.length === 4 && a.every(n => !isNaN(n)));
async function loadSettings() {
  const s = SETTINGS = await api("/api/settings");
  $("#s-whisper").value = s.whisper_model; $("#s-min").value = s.min_clip; $("#s-max").value = s.max_clip; $("#s-maxclips").value = s.max_clips;
  $("#s-hooksec").value = s.hook_seconds; $("#s-key").value = s.claude_api_key; $("#s-model").value = s.claude_model; $("#s-useclaude").checked = s.use_claude;
  $("#s-random").checked = s.randomise_style; $("#s-preset").value = s.render_preset; $("#s-clutter").value = regStr(s.clutter_regions);
  $("#s-drop").value = s.drop_folder; $("#s-watchdrop").checked = s.watch_drop_folder; $("#s-notify").checked = s.notify_desktop;
  $("#s-styles").innerHTML = Object.entries(META.styles).map(([k, l]) => `<label class="check"><input type="checkbox" value="${k}" ${s.caption_styles_enabled.includes(k) ? "checked" : ""}> ${esc(l)}</label>`).join("");
  const g = s.gta;
  $("#s-ocr").value = g.ocr_engine;
  $("#s-phrases").value = Object.entries(g.ocr_phrases).map(([k, v]) => `${k}: ${v.join(", ")}`).join("\n");
  $("#s-regions").value = Object.entries(g.ocr_regions).map(([k, v]) => `${k}: ${v.join(",")}`).join("\n");
  $("#s-wanted").value = g.wanted_region.join(","); $("#s-hud").value = regStr(g.hud_regions);
  $("#s-hidehud").checked = g.hide_hud; $("#s-skipquiet").checked = g.skip_quiet;
  $("#s-learned").textContent = `${s.examples} example(s). Signal boosts: ${JSON.stringify(g.weights || {})}` + (s.learned_phrases.length ? `\nLearned on-screen words: ${s.learned_phrases.join(", ")}` : "");
  $("#p-dropdir").textContent = s.drop_folder;
}
$("#s-save").onclick = async () => {
  const kv = txt => Object.fromEntries(txt.split("\n").filter(l => l.includes(":")).map(l => { const i = l.indexOf(":"); return [l.slice(0, i).trim(), l.slice(i + 1)]; }));
  const phrases = Object.fromEntries(Object.entries(kv($("#s-phrases").value)).map(([k, v]) => [k, v.split(",").map(x => x.trim()).filter(Boolean)]));
  const regions = Object.fromEntries(Object.entries(kv($("#s-regions").value)).map(([k, v]) => [k, v.split(",").map(Number)]).filter(([, v]) => v.length === 4 && v.every(n => !isNaN(n))));
  const wanted = $("#s-wanted").value.split(",").map(Number);
  const body = {whisper_model: $("#s-whisper").value, min_clip: +$("#s-min").value, max_clip: +$("#s-max").value, max_clips: +$("#s-maxclips").value,
    hook_seconds: +$("#s-hooksec").value, claude_api_key: $("#s-key").value.trim(), claude_model: $("#s-model").value.trim(), use_claude: $("#s-useclaude").checked,
    randomise_style: $("#s-random").checked, render_preset: $("#s-preset").value, clutter_regions: parseRegs($("#s-clutter").value),
    caption_styles_enabled: $$("#s-styles input:checked").map(x => x.value), drop_folder: $("#s-drop").value, watch_drop_folder: $("#s-watchdrop").checked,
    notify_desktop: $("#s-notify").checked,
    gta: {ocr_engine: $("#s-ocr").value, ocr_phrases: phrases, ocr_regions: regions, hud_regions: parseRegs($("#s-hud").value),
      hide_hud: $("#s-hidehud").checked, skip_quiet: $("#s-skipquiet").checked}};
  if (wanted.length === 4 && wanted.every(n => !isNaN(n))) body.gta.wanted_region = wanted;
  try { await api("/api/settings", {method: "PUT", body}); toast("Settings saved"); loadSettings(); applyDefaults(); } catch (e) { toast(e.message, "error"); }
};
$("#s-test").onclick = async () => { await $("#s-save").onclick(); const r = await api("/api/settings/test_claude", {method: "POST"}); toast("Claude: " + r.result, r.result === "ok" ? "clips" : "error", 8000); };
$("#s-reset-learn").onclick = async () => { if (confirm("Forget all learned examples?")) { await api("/api/settings/reset_learning", {method: "POST"}); loadSettings(); } };

function applyDefaults() {
  $("#p-min-len").value = SETTINGS.min_clip; $("#p-max-len").value = SETTINGS.max_clip; $("#p-max").value = SETTINGS.max_clips;
}

// ---------- start ----------
(async function init() {
  META = await api("/api/meta");
  await loadSettings();
  const presets = Object.entries(META.presets).map(([k, v]) => [k, v.label]);
  fillSelect($("#p-preset"), presets, "gta6"); fillSelect($("#rec-preset"), presets, "gta6");
  fillSelect($("#p-layout"), Object.entries(META.layouts), "auto");
  refreshCampaignSelects();
  applyDefaults();
  $("#p-preset").onchange = () => { $("#p-layout").value = "auto"; };
  poll();
  const tab = location.hash.slice(1);
  if (tab && $("#tab-" + tab)) showTab(tab);
})();
