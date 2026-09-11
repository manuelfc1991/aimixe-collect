/* AImixE Data Collection — local web interface. Talks only to /api; the same services as the CLI. */
(() => {
  "use strict";
  const $ = (sel, el = document) => el.querySelector(sel);
  const $$ = (sel, el = document) => Array.from(el.querySelectorAll(sel));
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const state = { lang: null, status: null, schema: null, profileData: null, lastCatalogueJob: null, view: "home", reviewLang: undefined, reviewSel: null, catFilter: "all" };
  const ARROW = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M13 6l6 6-6 6"></path></svg>';
  const TICK = '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12l5 5L20 7"></path></svg>';
  const kbd = (k) => `<span class="kbd">${esc(k)}</span>`;

  // ------------------------------------------------------------------ api
  async function api(method, path, body) {
    const res = await fetch(path, { method, headers: body ? { "Content-Type": "application/json" } : {}, body: body ? JSON.stringify(body) : undefined });
    const data = await res.json().catch(() => ({ error: "invalid response" }));
    if (!res.ok) throw new Error(data.error || res.statusText);
    return data;
  }
  const get = (p) => api("GET", p);
  const post = (p, b) => api("POST", p, b || {});
  const del = (p) => api("DELETE", p);
  function toast(msg, isError) {
    const t = $("#toast");
    t.textContent = msg; t.className = "toast" + (isError ? " error" : "");
    clearTimeout(t._h); t._h = setTimeout(() => t.classList.add("hidden"), isError ? 6000 : 3000);
  }
  const fail = (e) => toast(e.message || String(e), true);

  // ------------------------------------------------------------------ formatting
  function fmt(v) {
    if (v === null || v === undefined || (Array.isArray(v) && !v.length)) return "";
    if (Array.isArray(v)) return v.map(fmt).join(" · ");
    if (typeof v === "object") {
      if ("state" in v) return v.state + (v.detail ? ` (${v.detail})` : "");
      if ("name" in v) { const extra = ["type", "region", "country", "role"].filter((k) => v[k]).map((k) => v[k]); return v.name + (extra.length ? ` (${extra.join(", ")})` : ""); }
      if ("code" in v && "name" in v) return `${v.name} (${v.code})`;
      if ("value" in v) { const extra = ["type", "detail", "code"].filter((k) => v[k]).map((k) => v[k]); return String(v.value) + (v.approximate ? " (approx.)" : "") + (extra.length ? ` (${extra.join(", ")})` : ""); }
      if ("min" in v) return `${v.min}–${v.max}`;
      if ("title" in v || "kind" in v) return ["kind", "title", "date", "organisation", "url"].filter((k) => v[k]).map((k) => v[k]).join(" · ");
      if ("text" in v) return v.text + Object.keys(v).filter((k) => k !== "text").map((k) => `; ${k}: ${fmt(v[k])}`).join("");
      return Object.entries(v).filter(([, x]) => x !== null && x !== "").map(([k, x]) => `${k}: ${fmt(x)}`).join("; ");
    }
    if (typeof v === "boolean") return v ? "yes" : "no";
    return String(v);
  }
  const hb = (n) => n == null ? "?" : n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(0)} KB` : n < 1073741824 ? `${(n / 1048576).toFixed(1)} MB` : `${(n / 1073741824).toFixed(1)} GB`;
  const ht = (s) => s == null ? "—" : s < 60 ? `${Math.round(s)}s` : `${Math.floor(s / 60)}m${String(Math.round(s % 60)).padStart(2, "0")}s`;
  const when = (iso) => { if (!iso) return ""; const t = new Date(iso); if (isNaN(t)) return iso; const d = Math.floor((new Date().setHours(0, 0, 0, 0) - new Date(t).setHours(0, 0, 0, 0)) / 86400000); const hm = t.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }); return d === 0 ? `today ${hm}` : d === 1 ? `yesterday ${hm}` : d < 7 ? `${d} days ago` : t.toLocaleDateString(); };
  const words = ["no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve"];
  const num = (n) => n < words.length ? words[n] : String(n);
  const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);
  const plural = (n, one, many) => `${n} ${n === 1 ? one : (many || one + "s")}`;
  const scoreClass = (s) => s >= 70 ? "green" : s >= 30 ? "amber" : "";
  const scoreHtml = (s) => `<div class="score ${scoreClass(s)}"><span class="n">${s ?? "—"}</span><span class="bar"><i style="width:${Math.max(0, Math.min(100, s || 0))}%"></i></span></div>`;
  const stripUrl = (u) => String(u || "").replace(/^https?:\/\//, "").replace(/\/$/, "");
  const modeLabel = (m) => ({ "Online Collection": "online", "Offline Collection": "offline scan", Import: "import" }[m] || (m || "").toLowerCase());
  const linkOrText = (s) => /^https?:/.test(s || "") ? `<a class="mono" href="${esc(s)}" target="_blank" rel="noopener">${esc(stripUrl(s))}</a>` : `<span class="mono">${esc(s || "—")}</span>`;

  // ------------------------------------------------------------------ navigation
  const renderers = {};
  function show(view) {
    if ($(`#nav [data-view="${view}"]`)?.classList.contains("needs-lang") && !state.lang) { toast("Choose a language first"); view = "home"; }
    state.view = view;
    $$(".view").forEach((v) => v.classList.add("hidden"));
    $(`#view-${view}`).classList.remove("hidden");
    $$("#nav .nav-item").forEach((b) => b.classList.toggle("active", b.dataset.view === view || (view === "find" && b.dataset.view === "home") || (view === "catalogues" && b.dataset.view === "settings")));
    window.scrollTo({ top: 0 });
    history.replaceState(null, "", "#" + view + (state.lang ? ":" + state.lang : ""));
    const render = renderers[view];
    if (render) render().catch(fail);
  }
  $$("#nav .nav-item").forEach((b) => b.addEventListener("click", () => show(b.dataset.view)));
  $("#lang-select").addEventListener("change", (e) => { if (e.target.value) openLanguage(e.target.value); else { state.lang = null; syncSidebar(); show("home"); } });
  $("#jump-form").addEventListener("submit", (e) => { e.preventDefault(); const q = $("#jump-input").value.trim(); if (!q) return; $("#jump-input").value = ""; findLanguage(q); });
  document.addEventListener("keydown", (e) => {
    const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName);
    if (e.key === "/" && !typing) { e.preventDefault(); $("#jump-input").focus(); return; }
    if (e.key === "Escape" && document.activeElement === $("#jump-input")) { $("#jump-input").blur(); return; }
    if (typing || e.metaKey || e.ctrlKey || e.altKey) return;
    const k = e.key.toLowerCase();
    if (state.chord) { state.chord = false; const map = { n: "find", r: "review", h: "history", s: "settings", l: "home" }; if (map[k]) { if (k === "r") { state.reviewLang = null; } show(map[k]); e.preventDefault(); } return; }
    if (k === "g") { state.chord = true; setTimeout(() => { state.chord = false; }, 1500); return; }
    if (state.view === "review" && state.reviewKeys) state.reviewKeys(k, e);
  });

  async function refreshStatus() {
    state.status = await get("/api/status");
    $("#version").textContent = "v" + (state.status.version || "");
    $("#version").title = state.status.home;
    const sel = $("#lang-select");
    sel.innerHTML = '<option value="">— all languages —</option>' + state.status.languages.map((l) => `<option value="${esc(l.id)}">${esc(l.name)} [${esc(l.iso639_3 || l.id)}]</option>`).join("");
    sel.value = state.lang || "";
    const badge = $("#review-badge");
    badge.textContent = state.status.pending_review; badge.classList.toggle("hidden", !state.status.pending_review);
    const a = state.status.agent, eng = state.status.backends || [];
    $("#side-status").innerHTML = `<span><i class="dot ${a.available ? "" : "amber"}"></i>Agent: ${esc(a.name)}${a.available ? "" : " (not available)"}</span><span><i class="dot ${eng.length ? "" : "grey"}"></i>Engines: ${esc(eng.join(", ") || "none")}</span>`;
    syncSidebar();
  }
  function syncSidebar() {
    const sw = $("#lang-switch"), d = state.profileData;
    if (state.lang && d) {
      sw.classList.remove("no-lang");
      $("#switch-code").textContent = d.profile.iso639_3 || d.profile.id;
      $("#switch-name").textContent = d.profile.name;
      $("#nav-profile-count").textContent = `${d.status.known.length}/${totalFields()}`;
      $("#nav-collection-count").textContent = d.resource_count;
    } else {
      sw.classList.add("no-lang");
      $("#switch-code").textContent = "—"; $("#switch-name").textContent = "Choose a language";
      $("#nav-profile-count").textContent = ""; $("#nav-collection-count").textContent = "";
    }
    $$("#nav .needs-lang").forEach((b) => b.classList.toggle("disabled", !state.lang));
    $("#lang-select").value = state.lang || "";
  }
  const totalFields = () => state.schema ? state.schema.groups.reduce((n, g) => n + g.fields.length, 0) : 26;
  async function loadSchema() { if (!state.schema) state.schema = await get("/api/schema"); return state.schema; }
  async function loadProfile() { state.profileData = await get(`/api/languages/${encodeURIComponent(state.lang)}`); syncSidebar(); return state.profileData; }
  async function openLanguage(id, view) {
    state.lang = id; state.reviewLang = undefined;
    await loadSchema();
    await loadProfile();
    show(view || "profile");
  }

  // ------------------------------------------------------------------ home
  renderers.home = async function () {
    const el = $("#view-home");
    const d = await get("/api/home");
    const n = d.languages.length, w = d.pending_review;
    if (!n) {
      el.innerHTML = `<div class="head"><div class="head-text"><h1 class="display">Nothing collected yet.<br><span class="dim">Start by naming a language.</span></h1>
        <p class="lede">AImixE collects language resources three ways: online (catalogues and an agent searching the web), offline (scanning folders on this machine) and by direct import. Every file is hashed, classified, stored unchanged and indexed with where it came from. The profile you build for a language steers every search.</p></div>
        <div class="head-side"><button class="btn primary lg" id="home-new">New language ${ARROW}</button></div></div>`;
      $("#home-new").addEventListener("click", () => show("find"));
      return;
    }
    const keys = `<span class="keys">${kbd("G N")} new ${kbd("G R")} review ${kbd("G H")} history ${kbd("G S")} settings</span>`;
    el.innerHTML = `<div class="head"><div class="head-text">
        <h1 class="display">${cap(num(n))} ${n === 1 ? "language" : "languages"}.<br><span class="dim">${w ? `${cap(num(w))} ${w === 1 ? "thing" : "things"} waiting for you.` : "Nothing waiting for review."}</span></h1>
        <p class="lede">Everything below was found, hashed and stored unchanged. Your decisions in the review queue are what turn discoveries into the record.</p></div>
      <div class="head-side"><button class="btn primary lg" id="home-new">New language ${ARROW}</button>${keys}</div></div>
      <div class="rows">${d.languages.map((l) => {
        const meta = [l.family, l.region].filter(Boolean).map(esc);
        meta.push(l.last_session ? `last collected ${esc(when(l.last_session.started_at))} by ${esc(modeLabel(l.last_session.mode))}` : "never collected");
        const waiting = l.pending_review
          ? `<span class="state"><i class="dot lg amber"></i>${l.pending_review} waiting for review</span><span class="l">${[l.pending_resources ? plural(l.pending_resources, "resource") : "", l.pending_facts ? plural(l.pending_facts, "language fact") : ""].filter(Boolean).join(" · ")}</span>`
          : l.resources === 0 ? `<span class="state green"><i class="dot lg"></i>Ready to start</span><span class="l">profile from the bundled tables</span>`
          : `<span class="state green"><i class="dot lg"></i>Up to date</span><span class="l">${esc(l.next_step)}</span>`;
        const action = l.pending_review ? `<button class="btn amber" data-review="${esc(l.id)}">Review ${ARROW}</button>`
          : l.resources === 0 ? `<button class="btn green" data-open="${esc(l.id)}" data-to="catalogue">Start collecting ${ARROW}</button>`
          : `<button class="btn outline" data-open="${esc(l.id)}">Open ${ARROW}</button>`;
        return `<div class="lang-row"><div><div class="title"><span class="name" data-open="${esc(l.id)}">${esc(l.name)}</span><span class="code">${esc(l.iso639_3 || l.id)}</span>${l.identifier_type === "local" ? '<span class="tag">local id</span>' : ""}</div><div class="sub">${meta.join(" · ")}</div></div>
          <div class="stat"><span class="n">${l.resources}</span><span class="l">resources</span></div>
          <div class="stat"><span class="n">${l.profile_known}<small> / ${l.profile_total}</small></span><span class="l">profile fields known</span></div>
          <div class="stat" style="gap:6px">${waiting}</div>${action}</div>`; }).join("")}</div>
      <div class="cards3">
        <button class="card-link amber" id="home-review" ${w ? "" : "disabled"}><span><span class="t">Review everything waiting</span><span class="s">${w ? `${plural(w, "item")} across ${num(new Set(d.languages.filter((l) => l.pending_review).map((l) => l.id)).size)} language(s)` : "nothing waiting"}</span></span>${ARROW}</button>
        <button class="card-link" id="home-history"><span><span class="t">Collection history</span><span class="s">${plural(d.sessions, "session")} · ${hb(d.stored_bytes)} stored</span></span>${ARROW}</button>
        <button class="card-link" id="home-settings"><span><span class="t">Settings</span><span class="s">Agent ${esc(state.status.agent.name)} · engines ${esc((state.status.backends || []).join(", ") || "none")}</span></span>${ARROW}</button>
      </div>`;
    $$("[data-open]", el).forEach((b) => b.addEventListener("click", () => openLanguage(b.dataset.open, b.dataset.to)));
    $$("[data-review]", el).forEach((b) => b.addEventListener("click", async () => { await openLanguage(b.dataset.review, "review"); }));
    $("#home-new").addEventListener("click", () => show("find"));
    $("#home-review").addEventListener("click", () => { state.reviewLang = null; show("review"); });
    $("#home-history").addEventListener("click", () => show("history"));
    $("#home-settings").addEventListener("click", () => show("settings"));
  };

  // ------------------------------------------------------------------ find language (§1)
  renderers.find = async function () {
    const el = $("#view-find");
    el.innerHTML = `<div class="head"><div class="head-text"><span class="eyebrow">New language</span><h1 class="display">Which language?</h1>
      <p class="lede">Enter a name or an ISO 639-3 code. The bundled ISO and Glottolog tables answer offline; a language nobody has catalogued gets a local identifier.</p></div></div>
      <form id="find-form" class="form-row" style="max-width:720px"><input id="find-input" placeholder="Tangsa · nst · Nocte · njb" autofocus><button class="btn primary">Search ${ARROW}</button></form>
      <div id="find-result"></div>`;
    $("#find-form").addEventListener("submit", (e) => { e.preventDefault(); const q = $("#find-input").value.trim(); if (q) findLanguage(q); });
    if (state.findQuery) { $("#find-input").value = state.findQuery; const q = state.findQuery; state.findQuery = null; await resolveInto(q); }
  };
  function findLanguage(q) { state.findQuery = q; state.lang = null; syncSidebar(); show("find"); }
  async function resolveInto(q) {
    const box = $("#find-result");
    try {
      const res = await get(`/api/resolve?q=${encodeURIComponent(q)}`);
      if (res.status === "none") {
        box.innerHTML = `<div class="panel" style="max-width:720px"><h3>No language found for “${esc(q)}”</h3><p class="note" style="margin:0">Not in the local registry or the bundled ISO 639-3 / Glottolog tables. Create a profile anyway: without a valid ISO code a local identifier (x-…) is used and labelled as such.</p>
          <form id="create-form" class="form-row"><input id="create-name" value="${esc(q)}" placeholder="Language name"><input id="create-code" placeholder="ISO 639-3 code, if known" style="flex-grow:0;width:200px"><button class="btn primary">Create profile ${ARROW}</button></form></div>`;
        $("#create-form").addEventListener("submit", async (ev) => {
          ev.preventDefault();
          try { const r = await post("/api/languages/create", { name: $("#create-name").value, code: $("#create-code").value }); await refreshStatus(); openLanguage(r.language_id); } catch (err) { fail(err); }
        });
        return;
      }
      box.innerHTML = `<div class="rows">${res.status === "ambiguous" ? `<div class="empty" style="padding:0 0 20px">Several languages match “${esc(q)}”. Choose one.</div>` : `<span class="eyebrow" style="padding-bottom:12px">Language detected</span>`}${res.matches.slice(0, 8).map((m) => `
        <div class="match"><div class="name"><span>${esc(m.name)}</span><span class="code">${esc(m.iso639_3 || m.language_id)}</span>${m.source === "local_registry" ? '<span class="tag green">already in your registry</span>' : ""}${m.identifier_type === "local" ? '<span class="tag">local id</span>' : ""}</div>
          <div class="kv">${m.family ? `<span class="k">Family</span><span class="v">${esc(m.family)}</span>` : ""}${m.region ? `<span class="k">Region</span><span class="v">${esc(m.region)}</span>` : ""}${m.alternative_names.length ? `<span class="k">Also called</span><span class="v">${esc(m.alternative_names.slice(0, 8).join(" · "))}</span>` : ""}${m.matched_on !== "name" && m.matched_on !== "code" ? `<span class="k">Matched on</span><span class="v">${esc(m.matched_on.replace("_", " "))} “${esc(m.matched_text)}”</span>` : ""}</div>
          <div><button class="btn primary" data-open="${m.index}">${m.source === "local_registry" ? "Open" : "Continue with this language"} ${ARROW}</button></div></div>`).join("")}</div>`;
      $$("button[data-open]", box).forEach((b) => b.addEventListener("click", async () => {
        try { const r = await post("/api/languages/open", { query: q, index: Number(b.dataset.open) }); await refreshStatus(); if (r.created) toast(`Profile created for ${r.language_id}`); openLanguage(r.language_id); } catch (err) { fail(err); }
      }));
    } catch (err) { fail(err); }
  }

  // ------------------------------------------------------------------ profile (§2)
  renderers.profile = async function () {
    const [data, schema] = await Promise.all([loadProfile(), loadSchema()]);
    const p = data.profile, st = data.status;
    const key = (g, f) => `${g}.${f}`;
    const toAsk = new Set(st.to_ask.map(([g, f]) => key(g, f)));
    const uncertain = new Set(st.uncertain.map(([g, f]) => key(g, f)));
    const contradictory = new Set(st.contradictory.map(([g, f]) => key(g, f)));
    const knownSet = new Set(st.known.map(([g, f]) => key(g, f)));
    let pending = [];
    try { pending = (await get(`/api/review?language=${encodeURIComponent(state.lang)}`)).items.filter((i) => i.kind === "profile_field"); } catch (e) { /* review is optional here */ }
    const findPending = (g, f, value) => pending.find((i) => i.payload.group === g && i.payload.field === f && JSON.stringify(i.payload.value) === JSON.stringify(value));
    const groupCounts = schema.groups.map((g) => ({ g, known: g.fields.filter((f) => knownSet.has(key(g.name, f.name))).length, total: g.fields.length, state: st.groups[g.name] }));
    const el = $("#view-profile");
    el.innerHTML = `<div class="two-col">
      <div class="aside-col">
        <div class="title"><span class="eyebrow">Language profile</span><span class="name">${esc(p.name)}</span><span class="sub">${st.known.length} of ${totalFields()} fields known · ${esc(p.iso639_3 ? "ISO 639-3 " + p.iso639_3 : "local identifier " + p.id)}</span></div>
        <div class="group-nav">${groupCounts.map(({ g, known, total, state: s }, i) => `<button data-go="${g.name}" class="${i === 0 ? "on" : ""}"><i class="dot lg ${s === "done" ? "" : known ? "amber" : "grey"}"></i>${esc(g.progress_label)}<span class="n">${known}/${total}</span></button>`).join("")}</div>
        <button class="btn primary lg" id="profile-propose">Propose values ${ARROW}</button>
        <span class="note">Glottolog and a short read of pages about the language. Nothing is downloaded; each fact waits for your decision in the review queue.</span>
        ${jobsArea("propose-jobs")}
      </div>
      <div class="rows-wrap">${schema.groups.map((g, gi) => {
        const gc = groupCounts[gi];
        const legend = gi === 0 ? `<span class="legend"><span><i class="dot lg"></i>bundled tables</span><span><i class="dot lg amber"></i>proposed, awaiting you</span><span><i class="dot lg ink"></i>your answer</span></span>` : `<span class="note">${gc.known} known · ${gc.total - gc.known} to fill</span>`;
        return `<div class="group-block" id="group-${g.name}"><div class="section-head"><h2 class="section">${esc(g.title)}</h2>${legend}</div><div class="rows">${g.fields.map((f) => {
          const k = key(g.name, f.name), val = p[g.name][f.name];
          const envs = (p.provenance[g.name] || {})[f.name] || [];
          const has = fmt(val) !== "";
          const flag = contradictory.has(k) ? '<span class="tag amber">sources disagree</span>' : uncertain.has(k) ? '<span class="tag amber">uncertain</span>' : "";
          const accepted = envs.filter((e) => e.status !== "proposed").length;
          const prov = envs.map((e) => {
            const proposed = e.status === "proposed";
            const dot = proposed ? "amber" : e.source_type === "user" ? "ink" : "";
            const srcName = e.source_type === "local_database" ? "bundled tables" : e.source_type === "agent" ? "agent" : e.source_type;
            const ref = e.source ? (/^https?:/.test(e.source) ? `<a href="${esc(e.source)}" target="_blank" rel="noopener">${esc(stripUrl(e.source).slice(0, 48))}${stripUrl(e.source).length > 48 ? "…" : ""}</a>` : esc(e.source)) : "";
            const item = proposed ? findPending(g.name, f.name, e.value) : null;
            const acts = item ? ` · <a href="#" class="link" data-rv="${item.id}" data-act="accept">accept</a> · <a href="#" class="link quiet" data-rv="${item.id}" data-act="reject">reject</a>` : "";
            const text = proposed
              ? `${esc(srcName)} proposes <b>${esc(fmt(e.value))}</b> · ${Number(e.confidence).toFixed(2)}${ref ? " · " + ref : ""}${acts}`
              : `${accepted > 1 ? `${e.preferred ? "★ " : ""}<b>${esc(fmt(e.value))}</b> · ` : ""}${[esc(srcName), ref, e.year ? esc(e.year) : ""].filter(Boolean).join(" · ")} · ${Number(e.confidence).toFixed(2)}${e.status !== "accepted" ? ` · ${esc(e.status)}` : ""}${e.note ? " — " + esc(e.note) : ""}`;
            return `<span class="prov-line"><i class="dot lg ${dot}"></i><span>${text}</span></span>`;
          }).join("");
          return `<div class="field-row" data-group="${g.name}" data-field="${f.name}">
            <div class="key"><span class="eyebrow">${esc(f.label)} ${flag}</span><span class="code">${esc(k)}</span></div>
            <div class="val"><span class="v ${has ? "" : "none"}">${has ? esc(fmt(val)) : `Not recorded yet${f.help ? ` <span class="dim">— ${esc(f.help.split(".")[0].toLowerCase())}</span>` : ""}`}</span>${prov ? `<div class="prov">${prov}</div>` : ""}</div>
            <button class="link edit">${has ? "Edit" : "Add"}</button>
            <form class="editor hidden">${editorFor(f)}</form></div>`; }).join("")}</div></div>`; }).join("")}</div></div>`;
    $$("[data-go]", el).forEach((b) => b.addEventListener("click", () => { $$("[data-go]", el).forEach((x) => x.classList.toggle("on", x === b)); $(`#group-${b.dataset.go}`).scrollIntoView({ behavior: "smooth", block: "start" }); }));
    $$("[data-rv]", el).forEach((a) => a.addEventListener("click", async (e) => { e.preventDefault(); try { await post(`/api/review/${a.dataset.rv}/${a.dataset.act}`); toast(a.dataset.act === "accept" ? "Accepted" : "Rejected"); refreshStatus(); renderers.profile(); } catch (err) { fail(err); } }));
    const proposeDone = (j) => { const c = j.result || {}; toast(`${c.catalogue || 0} fact(s) from Glottolog, ${c.agent || 0} from ${c.pages || 0} page(s)`); if ((c.catalogue || 0) + (c.agent || 0) > 0) { state.reviewLang = state.lang; show("review"); } else renderers.profile(); };
    $("#profile-propose").addEventListener("click", async () => { try { await runJobIn("propose-jobs", "profile_enrich", {}, proposeDone); } catch (e) { fail(e); } });
    resumeJobs(["profile_enrich"], "propose-jobs", () => {}, (j) => j.status === "running").catch(() => {});
    $$(".field-row", el).forEach((row) => {
      const form = $(".editor", row);
      $(".edit", row).addEventListener("click", () => { form.classList.toggle("hidden"); row.classList.toggle("editing", !form.classList.contains("hidden")); const first = $("input, select, textarea", form); if (first && !form.classList.contains("hidden")) first.focus(); });
      $(".cancel", form)?.addEventListener("click", () => { form.classList.add("hidden"); row.classList.remove("editing"); });
      form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const fd = new FormData(form); const obj = {}; fd.forEach((v, k) => obj[k] = v);
        try { await post(`/api/languages/${encodeURIComponent(state.lang)}/profile`, { group: row.dataset.group, field: row.dataset.field, form: obj }); toast("Recorded"); renderers.profile(); } catch (err) { fail(err); }
      });
    });
  };
  function editorFor(f) {
    const sug = f.suggested || [];
    const dl = sug.length ? `<datalist id="dl-${f.name}">${sug.map((s) => `<option value="${esc(s)}">`).join("")}</datalist>` : "";
    const help = `<div class="help">${esc(f.help || "")}${sug.length && !["state", "basis", "parent", "community", "entries"].includes(f.kind) ? ` Suggested: ${esc(sug.join(", "))}` : ""}</div>`;
    const save = `<button class="btn primary sm">Save</button><button type="button" class="btn quiet sm cancel">Cancel</button>`;
    let body;
    switch (f.kind) {
      case "text": body = `<input name="value" placeholder="${esc(f.prompt)}">`; break;
      case "choice": body = `<input name="value" list="dl-${f.name}" placeholder="pick or describe">${dl}`; break;
      case "list": case "scripts": body = `<input name="value" placeholder="comma separated" style="min-width:420px">`; break;
      case "tagged_list": body = `<input name="value" placeholder="Hindi (lingua franca), Assamese: regional" style="min-width:420px">`; break;
      case "state": body = `<select name="state"><option value="">state…</option>${["yes", "no", "unknown", "limited", "reported", "historical"].map((s) => `<option>${s}</option>`).join("")}</select><input name="detail" placeholder="detail (optional)">`; break;
      case "speakers": body = `<input name="value" placeholder="8500 · ~8500 · 8000-9000">`; break;
      case "parent": body = `<input name="value" placeholder="parent language / group"><select name="type"><option value="">type…</option>${sug.map((s) => `<option>${esc(s)}</option>`).join("")}</select>`; break;
      case "places": body = `<textarea name="value" placeholder="one per line: name, type, region, country&#10;Changlang, district, Arunachal Pradesh, India"></textarea>`; break;
      case "basis": body = `<input name="type" list="dl-${f.name}" placeholder="type (census, fieldwork, …)">${dl}<input name="year" class="short" placeholder="year"><input name="source" placeholder="source">`; break;
      case "age_spread": body = `${["children", "young_adults", "adults", "elderly"].map((k) => `<label>${k.replace("_", " ")} <select name="${k}" style="min-width:100px"><option value="">?</option><option>yes</option><option>no</option><option>unknown</option></select></label>`).join("")}<input name="note" placeholder="note">`; break;
      case "entries": body = `<textarea name="value" placeholder="no · unknown · or one per line: kind | title | date | organisation | url&#10;Bible translation | New Testament | 2005 | Bible Society of India"></textarea><div class="help">Kinds: ${esc(sug.join(", "))}</div>`; break;
      case "community": body = `<textarea name="value" placeholder="community information"></textarea>${sug.map((a) => `<input name="${a.replace(/ /g, "_")}" placeholder="${esc(a)} (comma separated)">`).join("")}`; break;
      default: body = `<input name="value">`;
    }
    return `${help}<div class="fields">${body}</div><div class="actions">${save}</div>`;
  }

  // ------------------------------------------------------------------ jobs
  // A job runs on the server; the page only watches it. Leaving a page never stops a job, and
  // coming back re-attaches to it (resumeJob), so the log, progress and result are never lost.
  const JOB_LABEL = { import: "Import", offline: "Offline scan", catalogue_search: "Catalogue search", catalogue_collect: "Catalogue download", agent_search: "Agent search", profile_enrich: "Propose values" };
  const JOB_VIEW = { import: "import", offline: "offline", catalogue_search: "catalogue", catalogue_collect: "catalogue", agent_search: "agent", profile_enrich: "profile" };
  function jobCounter(j) {
    const c = (j.progress || {}).counters || {}, active = (j.progress || {}).active || [];
    const bits = [];
    if (c.files_seen != null && !c.records) bits.push(`${c.files_seen} files seen, ${c.hits || 0} match(es)`);
    if (c.import_total) bits.push(`${c.import_done || 0}/${c.import_total} imported`);
    if (c.records) bits.push(`record ${c.record || 0}/${c.records}`);
    if (c.max_pages) bits.push(`pages ${c.pages || 0}/${c.max_pages}`);
    if (active.length) bits.push(`${active.length} download(s) · ${hb(active.reduce((n, t) => n + (t.speed || 0), 0))}/s`);
    return bits.join(" · ") || (c.stage ? String(c.stage) : "") || (j.last_line || "").slice(0, 60) || "working …";
  }
  function startJob(kind, params) { return post("/api/jobs", { kind, language_id: state.lang, params }).then((r) => { watchJobs(); return r.job_id; }); }
  function attachJob(jobId, logEl, onDone) {
    return new Promise((resolve, reject) => {
      if (!logEl.textContent) logEl.textContent = "starting …";
      const tick = async () => {
        try {
          if (!logEl.isConnected) return resolve(null);          // the page moved on; the job keeps running on the server
          const j = await get(`/api/jobs/${jobId}`);
          logEl.textContent = j.log.join("\n") || "…";
          logEl.scrollTop = logEl.scrollHeight;
          renderProgress(logEl, j);
          if (j.status === "running") return setTimeout(tick, 800);
          if (j.status === "failed") { toast(j.error, true); return reject(new Error(j.error)); }
          refreshStatus().catch(() => {});
          if (state.lang) loadProfile().catch(() => {});
          if (onDone) onDone(j);
          resolve(j);
        } catch (e) { reject(e); }
      };
      tick();
    });
  }
  function runJob(kind, params, logEl, onDone) { return startJob(kind, params).then((id) => attachJob(id, logEl, onDone)); }
  const langName = (id) => { const l = (state.status?.languages || []).find((x) => x.id === id); return l ? l.name : id; };
  async function watchJobs() {
    clearTimeout(state.jobsTimer);
    let jobs;
    try { jobs = (await get("/api/jobs?summary=1")).jobs; } catch (e) { return; }
    const running = jobs.filter((j) => j.status === "running");
    const seen = state.jobsSeen || (state.jobsSeen = {});
    for (const j of jobs) {
      if (seen[j.id] === "running" && j.status !== "running") {
        toast(`${JOB_LABEL[j.kind] || j.kind} for ${langName(j.language_id)} ${j.status === "failed" ? "failed: " + (j.error || "") : "finished"}`, j.status === "failed");
        refreshStatus().catch(() => {}); if (state.view === "home") renderers.home().catch(() => {});
      }
      seen[j.id] = j.status;
    }
    $("#side-jobs").innerHTML = running.map((j) => `<button class="side-job" data-job-lang="${esc(j.language_id)}" data-job-view="${JOB_VIEW[j.kind] || "home"}"><span class="t"><span class="spinner"></span>${esc(JOB_LABEL[j.kind] || j.kind)} · ${esc(j.language_id)}</span><span class="s">${esc(jobCounter(j))}</span></button>`).join("");
    $$("#side-jobs [data-job-lang]").forEach((b) => b.addEventListener("click", () => openLanguage(b.dataset.jobLang, b.dataset.jobView)));
    state.jobs = jobs;
    if (running.length) state.jobsTimer = setTimeout(watchJobs, 1500);
  }
  async function latestJob(kinds, extra) {
    const jobs = (await get("/api/jobs?summary=1")).jobs;
    return jobs.find((j) => kinds.includes(j.kind) && j.language_id === state.lang && (!extra || extra(j))) || null;
  }
  const jobHead = (j) => `<div class="job-head">${j.status === "running" ? '<span class="spinner"></span>' : ""}<b>${esc(JOB_LABEL[j.kind] || j.kind)}</b> started ${esc(when(j.started_at))}${j.status !== "running" ? ` · ${esc(j.status)} ${esc(when(j.finished_at))}` : " · still running; you can leave this page and come back"}${j.params && j.params.path ? ` · ${esc(j.params.path)}` : ""}${j.params && j.params.roots ? ` · ${esc(j.params.roots.join(", "))}` : ""}</div>`;
  /** Run a new job in its own block. onDone(job, resultEl) draws the result into the block. */
  async function runJobIn(areaId, kind, params, onDone) {
    const b = jobBlock(areaId, null);
    const id = await startJob(kind, params);
    b.el.dataset.job = id;
    return attachJob(id, b.log, (j) => { b.head(j); if (onDone) onDone(j, b.result); b.el.scrollIntoView({ behavior: "smooth", block: "nearest" }); }).catch((e) => { b.head({ kind, status: "failed", started_at: new Date().toISOString(), finished_at: new Date().toISOString() }); throw e; });
  }
  /** Show every running job of these kinds for the current language, plus the most recent finished one. */
  async function resumeJobs(kinds, areaId, onDone, extra) {
    const jobs = (await get("/api/jobs?summary=1")).jobs.filter((j) => kinds.includes(j.kind) && j.language_id === state.lang && (!extra || extra(j)));
    const running = jobs.filter((j) => j.status === "running");
    const done = jobs.find((j) => j.status !== "running");
    const shown = done ? [...running, done] : running;
    if (!$(`#${areaId}`)) return shown;
    for (const j of shown.slice().reverse()) {          // oldest first so the newest ends up on top
      const b = jobBlock(areaId, j);
      if (j.status === "running") attachJob(j.id, b.log, (full) => { b.head(full); onDone(full, b.result); }).catch(() => {});
      else { const full = await get(`/api/jobs/${j.id}`); b.log.textContent = full.log.join("\n"); if (full.status === "finished") onDone(full, b.result); else if (full.error) b.result.innerHTML = `<p class="note" style="color:var(--red)">${esc(full.error)}</p>`; }
    }
    return shown;
  }
  function renderProgress(logEl, j) {
    let box = logEl.nextElementSibling;
    if (!box || !box.classList.contains("progress-box")) { box = document.createElement("div"); box.className = "progress-box"; logEl.after(box); }
    const p = j.progress || {}; const c = p.counters || {}; const active = p.active || [];
    if (j.status !== "running") { box.innerHTML = ""; return; }
    const bits = [];
    if (c.stage) bits.push(`<b>${esc(c.stage)}</b>`);
    if (c.records) bits.push(`record ${c.record || 0}/${c.records}`);
    if (c.files) bits.push(`file ${c.file || 0}/${c.files}`);
    if (c.max_pages) bits.push(`pages ${c.pages || 0}/${c.max_pages}`);
    if (c.files_seen != null && !c.records) bits.push(`${c.files_seen} files seen, ${c.hits || 0} match(es)`);
    if (c.import_total) bits.push(`${c.import_done || 0}/${c.import_total} imported`);
    box.innerHTML = `<div class="note"><span class="spinner"></span> ${bits.join(" · ") || "working …"}</div>` + active.map((t) => `
      <div class="xfer"><div class="xfer-name">${esc(t.name)}</div>
        <div class="bar-track"><div class="bar-fill" style="width:${t.percent != null ? t.percent.toFixed(0) : 100}%"></div></div>
        <div class="xfer-stats">${t.total ? `${t.percent.toFixed(0)}% · ${hb(t.done)} / ${hb(t.total)}` : hb(t.done)} · ${hb(t.speed)}/s${t.eta != null ? ` · eta ${ht(t.eta)}` : ""}</div></div>`).join("");
  }
  const jobsArea = (id) => `<div class="jobs" id="${id}"></div>`;
  /** A block for one job inside a jobs area: header, log, progress, result. Newest on top. */
  function jobBlock(areaId, j) {
    const area = $(`#${areaId}`);
    const el = document.createElement("div"); el.className = "job"; el.dataset.job = j ? j.id : "";
    el.innerHTML = `${j ? jobHead(j) : '<div class="job-head"><span class="spinner"></span><b>starting …</b></div>'}<pre class="log"></pre><div class="progress-box"></div><div class="job-result"></div>`;
    area.prepend(el);
    return { el, log: $("pre", el), result: $(".job-result", el), head: (job) => { $(".job-head", el).outerHTML = jobHead(job); } };
  }
  function summaryHtml(s) {
    return `<div class="section-head"><h2 class="section">Session ${esc(s.id)}</h2><span class="note">${esc(s.language_name)} · ${esc(s.mode)} · ${esc(s.status)}</span></div>
      <div class="stats">${[["Discovered", s.discovered], ["Relevant", s.relevant], ["Downloaded", s.downloaded], ["Duplicates", s.duplicates], ["Failed", s.failed], ["Pending review", s.pending_review]].map(([k, v]) => `<div class="stat"><span class="n">${v}</span><span class="l">${k}</span></div>`).join("")}</div>`;
  }
  function outcomesHtml(outs) {
    if (!outs || !outs.length) return "<div class='empty'>No resources.</div>";
    const label = { stored: "stored", duplicate_linked: "duplicate", uncertain_review: "to review", rejected: "skipped", failed: "failed" };
    return `<div class="rows"><div class="thead cols-out"><span>Outcome</span><span>Relevance</span><span>Resource</span><span>Type</span></div>${outs.map((o) => `<div class="trow cols-out ${o.resource_id ? "click" : ""}" data-rid="${o.resource_id || ""}"><span class="cell status-${o.status}" style="font-weight:600">${esc(label[o.status] || o.status)}</span>${scoreHtml(o.relevance)}<div><div class="rtitle" style="font-size:15px">${esc(o.name)}</div>${["failed", "duplicate_linked", "rejected"].includes(o.status) && o.message ? `<div class="rsub">${esc(o.message)}</div>` : ""}</div><span class="cell">${esc((o.types || []).join(", ") || "—")}</span></div>`).join("")}</div>`;
  }
  function wireResourceRows(el) { $$("[data-rid]", el).forEach((r) => r.dataset.rid && r.addEventListener("click", () => showResource(Number(r.dataset.rid)))); }

  // ------------------------------------------------------------------ catalogue search (§4.1)
  renderers.catalogue = async function () {
    const el = $("#view-catalogue");
    const cats = state.status.catalogues, p = state.profileData.profile;
    el.innerHTML = `<div class="head"><div class="head-text"><span class="eyebrow">Online collection · Catalogue search</span><h1 class="display">Ask the catalogues about ${esc(p.name)}.</h1>
        <p class="lede">Providers search with the whole language profile: ISO code, name, alternative names, varieties, known publications. Lookup providers have no machine-readable search and return a place to open in a browser.</p></div>
      <div class="head-side"><button class="btn primary lg" id="cat-search">Search ${ARROW}</button></div></div>
      <div class="chips">${cats.map((c) => `<label class="chip ${c.enabled ? "" : "off"}"><input type="checkbox" name="prov" value="${esc(c.name)}" ${c.enabled ? "checked" : "disabled"}> ${esc(c.name)} <span class="muted">${esc(c.kind)}</span></label>`).join("")}<a class="link quiet" id="cat-manage">manage catalogues</a></div>
      ${jobsArea("cat-jobs")}<div id="cat-results"></div>`;
    $("#cat-manage").addEventListener("click", () => show("catalogues"));
    const searchDone = (j, resultEl) => {
      state.lastCatalogueJob = j.id;
      const secs = Math.max(0, Math.round((new Date(j.finished_at) - new Date(j.started_at)) / 1000)) || 0;
      resultEl.innerHTML = `<p class="note">${j.result.results.length} result(s), ${j.result.lookups.length} place(s) to open — shown below.</p>`;
      renderCatalogueResults(j.result, secs, (j.params || {}).providers || []);
      resumeJobs(["catalogue_collect"], "cat-collect-jobs", showCollectResult, (c) => (c.params || {}).search_job === j.id).catch(() => {});
    };
    $("#cat-search").addEventListener("click", async () => {
      const providers = $$("input[name=prov]:checked", el).map((i) => i.value);
      try { await runJobIn("cat-jobs", "catalogue_search", { providers }, searchDone); } catch (e) { fail(e); }
    });
    resumeJobs(["catalogue_search"], "cat-jobs", searchDone).catch(() => {});
  };
  function showCollectResult(j2, box) {
    if (!box) return;
    box.innerHTML = summaryHtml(j2.result.session) + (j2.result.proposals ? `<p class="note">${j2.result.proposals} language fact(s) proposed for review.</p>` : "") + outcomesHtml(j2.result.outcomes);
    wireResourceRows(box);
  }
  function renderCatalogueResults(r, secs, providers) {
    const cfg = state.status.config;
    const out = $("#cat-results");
    const results = r.results.slice().sort((a, b) => b.score - a.score);
    const conf = results.filter((s) => s.score >= cfg.confirmed_at).length, rev = results.filter((s) => s.score >= cfg.review_at && s.score < cfg.confirmed_at).length, low = results.length - conf - rev;
    let minScore = cfg.review_at; let filter = "all"; let showAll = false;
    const answered = [...new Set(results.map((s) => s.provider))];
    const draw = () => {
      const visible = results.filter((s) => filter === "all" || (filter === "confirmed" && s.score >= cfg.confirmed_at) || (filter === "review" && s.score >= cfg.review_at && s.score < cfg.confirmed_at) || (filter === "low" && s.score < cfg.review_at));
      const shown = showAll || filter !== "all" ? visible : visible.filter((s) => s.score >= cfg.review_at);
      const hiddenCount = visible.length - shown.length;
      const selected = results.filter((s) => s.score >= minScore);
      const selConf = selected.filter((s) => s.score >= cfg.confirmed_at).length;
      out.innerHTML = `<div class="head"><div class="head-text"><h2 class="section" style="font-size:34px">${results.length} ${results.length === 1 ? "result" : "results"}, ${conf + rev ? `${num(conf + rev)} worth a look` : "none above the review line"}.</h2>
          <span class="note">${answered.length ? esc(answered.join(", ")) + ` answered in ${secs} s.` : "No catalogue returned results."}${r.lookups.length ? ` ${cap(num(r.lookups.length))} more place${r.lookups.length === 1 ? "" : "s"} to open in a browser.` : ""}${r.unavailable && r.unavailable.length ? ` Unavailable: ${esc(r.unavailable.join(", "))}.` : ""}</span>
          ${r.errors.map((e) => `<span class="note" style="color:var(--red)">${esc(e)}</span>`).join("")}</div>
        <div class="pills">${[["all", `All ${results.length}`, ""], ["confirmed", `Confirmed ${conf}`, "green"], ["review", `For review ${rev}`, "amber"], ["low", `Below ${cfg.review_at} · ${low}`, ""]].map(([k, l, c]) => `<button class="pill ${c} ${filter === k ? "on" : ""}" data-f="${k}">${l}</button>`).join("")}</div></div>
        <div class="rows"><div class="thead cols-cat"><span></span><span>Relevance</span><span>Result</span><span>Catalogue</span><span>Licence</span><span>Files</span></div>
        ${shown.map((s) => `<div class="trow cols-cat ${s.score < cfg.review_at ? "dim" : ""}"><span class="tick ${s.score >= minScore ? "on" : ""}">${s.score >= minScore ? TICK : ""}</span>${scoreHtml(s.score)}<div style="min-width:0"><a class="rtitle" href="${esc(s.url || "#")}" target="_blank" rel="noopener">${esc(s.title)}</a><div class="rsub">${esc(s.reasons.join(" · "))}</div></div><span class="cell">${esc(s.provider)}</span><span class="cell mono">${esc(s.licence || "—")}</span><span class="cell mono">${esc(s.action || "")}</span></div>`).join("")}
        ${hiddenCount ? `<div class="tfoot"><span>${hiddenCount} more below ${cfg.review_at} — recorded in the session, not downloaded</span><a class="link" id="cat-showall">Show all</a></div>` : ""}${!shown.length ? `<div class="empty">Nothing in this band.</div>` : ""}</div>
        <div class="summary-bar"><div class="chips">${r.lookups.length ? `<span class="eyebrow" style="margin-right:6px">Open in a browser</span>${r.lookups.map((l) => `<a class="chip" href="${esc(l.url)}" target="_blank" rel="noopener">${esc(l.provider)}${l.title ? " · " + esc(l.title) : ""}</a>`).join("")}` : ""}</div>
          <div class="dark"><div><span class="t">${plural(selected.length, "result")} selected</span><span class="s">${selConf} confirmed, ${selected.length - selConf} to the review queue · minimum relevance <input id="cat-min" type="number" min="0" max="100" value="${minScore}"></span></div><button class="btn" id="cat-collect" ${selected.length ? "" : "disabled"}>Download ${ARROW}</button></div></div>
        ${jobsArea("cat-collect-jobs")}`;
      $$("[data-f]", out).forEach((b) => b.addEventListener("click", () => { filter = b.dataset.f; draw(); }));
      $("#cat-showall")?.addEventListener("click", () => { showAll = true; draw(); });
      $("#cat-min").addEventListener("change", (e) => { minScore = Math.max(0, Math.min(100, Number(e.target.value) || 0)); draw(); });
      $("#cat-collect").addEventListener("click", async () => {
        try { await runJobIn("cat-collect-jobs", "catalogue_collect", { search_job: state.lastCatalogueJob, min_score: minScore }, showCollectResult); } catch (e) { fail(e); }
      });
    };
    draw();
  }

  // ------------------------------------------------------------------ agent search (§6)
  renderers.agent = async function () {
    const el = $("#view-agent");
    const p = state.profileData.profile;
    el.innerHTML = `<div class="head"><div class="head-text"><span class="eyebrow">Online collection · Agent search</span><h1 class="display">Let the agent read the web for ${esc(p.name)}.</h1><span class="note"><span class="spinner"></span> Planning queries from the language profile …</span></div></div>`;
    const [plan, prov, eng] = await Promise.all([get(`/api/languages/${encodeURIComponent(state.lang)}/agent/plan`), get("/api/agent/provider"), get("/api/agent/engines")]);
    const lim = plan.limits;
    const usable = eng.engines.filter((e) => e.enabled && e.available).map((e) => e.name);
    el.innerHTML = `<div class="head"><div class="head-text"><span class="eyebrow">Online collection · Agent search</span><h1 class="display">Let the agent read the web for ${esc(p.name)}.</h1>
        <p class="lede">The agent turns the profile into search queries, reads the pages it finds, follows links to files and proposes what it learns. Names and varieties discovered during the run feed later rounds and go to the review queue, never straight into the profile.</p></div>
      <div class="head-side"><button class="btn primary lg" id="agent-run" ${plan.backends.length ? "" : "disabled"}>Run ${plan.queries.length} queries ${ARROW}</button><span class="note">${lim.max_pages} pages · depth ${lim.max_depth} · ${lim.per_host} per host · ${lim.max_files} files · ${lim.max_rounds} rounds</span></div></div>
      <div class="cards3">
        <div class="panel"><h3>Agent provider</h3><select id="agent-provider">${prov.choices.map((c) => `<option value="${esc(c.name)}" ${c.current ? "selected" : ""} ${c.installed ? "" : "disabled"}>${esc(c.name)} — ${esc(c.what)}${c.installed ? "" : " (not installed)"}</option>`).join("")}</select>
          <span class="note">${plan.agent.available ? "A model provider receives the language profile and the text of visited pages." : `<span style="color:var(--amber-ink)">${esc(plan.agent.name)} is not available (${esc(plan.agent.why)}); the rule-based agent is used.</span>`}</span></div>
        <div class="panel"><h3>Search engines</h3><span style="font-size:15px">${usable.length ? esc(usable.join(", ")) : '<span style="color:var(--amber-ink)">none usable</span>'}</span><span class="note">Engines are asked in this order. Keys and regional engines (Baidu, Sogou, Yandex, SearXNG …) are set in <a class="link" id="agent-to-settings">Settings</a>.</span></div>
        <div class="panel"><h3>Your own queries</h3><input id="agent-extra" placeholder="separate several with ;"><span class="note">Added to the planned queries below with basis “user”.</span></div></div>
      <div class="rows"><div class="thead cols-q"><span></span><span>Basis</span><span>Query</span></div>${plan.queries.map((q, i) => `<label class="trow cols-q" style="padding:14px 0;cursor:pointer"><input class="check" type="checkbox" checked data-i="${i}" style="width:16px;height:16px;accent-color:var(--ink)"><span class="cell">${esc(q.basis)}</span><div style="min-width:0"><div class="rtitle" style="font-size:15px">${esc(q.text)}</div>${q.rationale ? `<div class="rsub">${esc(q.rationale)}</div>` : ""}</div></label>`).join("")}</div>
      ${jobsArea("agent-jobs")}`;
    $("#agent-to-settings").addEventListener("click", () => show("settings"));
    $("#agent-provider").addEventListener("change", async (e) => { try { await post("/api/agent/provider", { provider: e.target.value }); toast(`Agent provider: ${e.target.value}`); await refreshStatus(); renderers.agent(); } catch (err) { fail(err); } });
    const agentDone = (j, out) => {
      const r = j.result; if (!out) return;
      out.innerHTML = summaryHtml(r.session) + `<p class="note">Hits ${r.hits} · pages fetched ${r.pages_fetched} · relevant ${r.pages_relevant} · files found ${r.files_found}${r.learned.length ? ` · learned: ${esc(r.learned.join(", "))}` : ""}${r.proposals_queued ? ` · ${r.proposals_queued} fact(s) proposed for review` : ""}</p>` + r.errors.map((e) => `<p class="note" style="color:var(--red)">${esc(e)}</p>`).join("") + outcomesHtml(r.outcomes);
      wireResourceRows(out);
    };
    $("#agent-run").addEventListener("click", async () => {
      const queries = plan.queries.filter((q, i) => $(`input[data-i="${i}"]`, el).checked).map((q) => ({ text: q.text, basis: q.basis, rationale: q.rationale }));
      $("#agent-extra").value.split(";").map((s) => s.trim()).filter(Boolean).forEach((t) => queries.push({ text: t, basis: "user" }));
      try { await runJobIn("agent-jobs", "agent_search", { queries }, agentDone); } catch (e) { fail(e); }
    });
    resumeJobs(["agent_search"], "agent-jobs", agentDone).catch(() => {});
  };

  // ------------------------------------------------------------------ offline (§8) and import (§9)
  const modeSelect = (id) => `<select id="${id}">${["copy", "move", "reference"].map((m) => `<option ${m === state.status.config.storage_mode ? "selected" : ""}>${m}</option>`).join("")}</select>`;
  renderers.offline = async function () {
    const el = $("#view-offline"), terms = state.profileData.offline_terms, p = state.profileData.profile;
    el.innerHTML = `<div class="head"><div class="head-text"><span class="eyebrow">Offline collection</span><h1 class="display">Scan this machine for ${esc(p.name)}.</h1>
        <p class="lede">Folders are walked for the profile's ${terms.length} search terms in file names and, optionally, inside text and document files. Matches are hashed, typed and stored the way you choose; originals are never modified.</p></div>
      <div class="head-side"><button class="btn primary lg" id="off-run">Scan ${ARROW}</button></div></div>
      <div class="cards3"><div class="panel" style="grid-column:span 2"><h3>Folders to scan</h3><textarea id="off-roots" placeholder="/home/you/Documents&#10;one folder per line"></textarea></div>
        <div class="panel"><h3>Options</h3><label class="note">Storage mode ${modeSelect("off-mode")}</label><label class="check"><input type="checkbox" id="off-content" checked> Also look inside text and document files</label></div></div>
      <div class="chips"><span class="eyebrow" style="margin-right:6px">Search terms</span>${terms.slice(0, 24).map((t) => `<span class="chip">${esc(t)}</span>`).join("")}${terms.length > 24 ? `<span class="note">and ${terms.length - 24} more</span>` : ""}</div>
      ${jobsArea("off-jobs")}`;
    const offDone = (j, out) => {
      if (!out) return;
      out.innerHTML = summaryHtml(j.result.session) + (j.result.scan ? `<p class="note">Files seen ${j.result.scan.files_seen} · matches ${j.result.scan.hits} · folders skipped ${j.result.scan.dirs_skipped}</p>` : "") + outcomesHtml(j.result.outcomes);
      wireResourceRows(out);
    };
    $("#off-run").addEventListener("click", async () => {
      const roots = $("#off-roots").value.split("\n").map((s) => s.trim()).filter(Boolean);
      if (!roots.length) return toast("Enter at least one folder", true);
      try { await runJobIn("off-jobs", "offline", { roots, mode: $("#off-mode").value, content: $("#off-content").checked }, offDone); } catch (e) { fail(e); }
    });
    resumeJobs(["offline"], "off-jobs", offDone).then((jobs) => { const j = jobs[0]; if (j && j.params && j.params.roots && !$("#off-roots").value) $("#off-roots").value = j.params.roots.join("\n"); }).catch(() => {});
  };
  renderers.import = async function () {
    const el = $("#view-import"), p = state.profileData.profile;
    el.innerHTML = `<div class="head"><div class="head-text"><span class="eyebrow">Import</span><h1 class="display">Bring your own files into ${esc(p.name)}.</h1>
        <p class="lede">A file or a whole folder. Every file is hashed (SHA-256), duplicate-checked, typed, classified and stored with its original location recorded. The original is never modified.</p></div>
      <div class="head-side"><button class="btn primary lg" id="imp-run">Import ${ARROW}</button></div></div>
      <div class="cards3"><div class="panel" style="grid-column:span 2"><h3>Path on this machine</h3><input id="imp-path" placeholder="/path/to/folder or dictionary.pdf"></div>
        <div class="panel"><h3>Storage mode</h3>${modeSelect("imp-mode")}<span class="note">copy keeps the original in place · move relocates it · reference indexes it where it is</span></div></div>
      ${jobsArea("imp-jobs")}`;
    $("#imp-path").addEventListener("keydown", (e) => { if (e.key === "Enter") $("#imp-run").click(); });
    const impDone = (j, out) => { if (!out) return; out.innerHTML = summaryHtml(j.result.session) + outcomesHtml(j.result.outcomes); wireResourceRows(out); };
    $("#imp-run").addEventListener("click", async () => {
      const path = $("#imp-path").value.trim();
      if (!path) return toast("Enter a path", true);
      try { await runJobIn("imp-jobs", "import", { path, mode: $("#imp-mode").value }, impDone); } catch (e) { fail(e); }
    });
    resumeJobs(["import"], "imp-jobs", impDone).then((jobs) => { const j = jobs[0]; if (j && j.params && j.params.path && !$("#imp-path").value) $("#imp-path").value = j.params.path; }).catch(() => {});
  };

  // ------------------------------------------------------------------ collection (§3 item 4)
  renderers.collection = async function () {
    const el = $("#view-collection"), p = state.profileData.profile;
    const { resources } = await get(`/api/languages/${encodeURIComponent(state.lang)}/resources`);
    const size = resources.reduce((n, r) => n + (r.size || 0), 0);
    el.innerHTML = `<div class="head"><div class="head-text"><span class="eyebrow">Existing collection</span><h1 class="display">${resources.length ? `${plural(resources.length, "resource")} for ${esc(p.name)}.` : `Nothing collected for ${esc(p.name)} yet.`}</h1>
        <span class="note">${resources.length ? `${hb(size)} stored unchanged under ~/.aimixe. Click a row for provenance, extraction and duplicates.` : "Start with a catalogue search, the agent, an offline scan or an import."}</span></div></div>
      ${resources.length ? `<div class="rows"><div class="thead cols-col"><span>Relevance</span><span>Resource</span><span>Format</span><span>Type</span><span>Sources</span></div>
      ${resources.map((r) => `<div class="trow cols-col click" data-rid="${r.id}">${scoreHtml(r.relevance_score)}<div style="min-width:0"><div class="rtitle">${esc(r.original_name)}</div><div class="rsub">#${r.id} · ${esc(r.status)} · ${hb(r.size)}</div></div><span class="cell mono">${esc(r.format)} · ${esc(r.category)}</span><span class="cell">${esc(r.types || "—")}</span><span class="cell mono">${r.source_count}</span></div>`).join("")}</div>` : ""}
      <div id="resource-detail"></div>`;
    wireResourceRows(el);
  };
  async function showResource(rid) {
    const d = await get(`/api/resources/${rid}`);
    let box = $("#resource-detail");
    if (!box || box.closest(".hidden")) { show("collection"); await new Promise((r) => setTimeout(r, 80)); box = $("#resource-detail"); }
    const r = d.resource;
    box.innerHTML = `<div class="panel" style="gap:24px"><div class="section-head" style="padding:0"><h2 class="section">${esc(r.original_name)}</h2><span class="note mono">#${r.id}</span></div>
      <div class="kv"><span class="k">Stored at</span><span class="v mono">${esc(r.stored_path)}</span><span class="k">SHA-256</span><span class="v mono">${esc(r.sha256)}</span><span class="k">Format</span><span class="v">${esc(r.format)} · ${esc(r.category)} · ${hb(r.size)} · ${esc(r.storage_mode)}</span>
        <span class="k">Resource types</span><span class="v">${d.types.map((t) => `${esc(t.type)} <span class="tag">${Number(t.confidence).toFixed(2)} ${esc(t.source)}</span>`).join(" ") || "—"}</span>
        <span class="k">Relevance</span><span class="v">${d.languages.map((l) => `${esc(l.language_id)}: <b class="mono">${l.relevance_score}</b> ${esc(l.status)} — ${esc(JSON.parse(l.reasons_json || "[]").join("; "))}`).join("<br>")}</span></div>
      <h3>Provenance · ${plural(d.sources.length, "source record")}</h3>
      <div class="prov">${d.sources.map((s) => `<span class="prov-line"><i class="dot lg"></i><span>${Object.entries(s).filter(([k, v]) => v !== null && v !== "" && !["id", "resource_id"].includes(k)).map(([k, v]) => `<b>${esc(k)}</b> ${esc(v)}`).join(" · ")}</span></span>`).join("")}</div>
      ${d.extractions.length ? `<h3>Extracted (derived, originals untouched)</h3><div class="prov">${d.extractions.map((e) => `<span class="prov-line"><i class="dot lg grey"></i>${esc(e.kind)}: <span class="mono">${esc(e.path)}</span></span>`).join("")}</div>` : ""}
      ${d.near_duplicates.length ? `<h3>Near-duplicates</h3><div class="prov">${d.near_duplicates.map((n) => `<span class="prov-line"><i class="dot lg amber"></i>#${n.other_id} ${esc(n.original_name)} (${Math.round(n.similarity * 100)}%, ${esc(n.method)})</span>`).join("")}</div>` : ""}
      <details class="more"><summary>Metadata (${d.metadata.length})</summary><div class="prov">${d.metadata.map((m) => `<span class="prov-line"><b>${esc(m.key)}</b> ${esc(String(m.value).slice(0, 300))} <span class="tag">${esc(m.extracted_by)}</span></span>`).join("")}</div></details></div>`;
    box.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  // ------------------------------------------------------------------ review (§18)
  renderers.review = async function () {
    const el = $("#view-review");
    const filter = state.reviewLang !== undefined ? state.reviewLang : state.lang;
    const [{ items }, summary] = await Promise.all([get(filter ? `/api/review?language=${encodeURIComponent(filter)}` : "/api/review"), get("/api/review/summary")]);
    const total = summary.languages.reduce((n, l) => n + l.total, 0);
    const facts = items.filter((i) => i.kind === "profile_field").length, res = items.length - facts;
    if (!items.some((i) => i.id === state.reviewSel)) state.reviewSel = items.length ? items[0].id : null;
    const sel = items.find((i) => i.id === state.reviewSel);
    const idx = items.indexOf(sel);
    const langName = (id) => { const l = summary.languages.find((x) => x.language_id === id) || (state.status.languages || []).find((x) => x.id === id); return l ? l.name : id; };
    const fieldLabel = (g, f) => state.schema ? (state.schema.groups.find((x) => x.name === g)?.fields.find((x) => x.name === f)?.label || f) : f;
    const itemTitle = (it) => it.kind === "profile_field" ? `${fieldLabel(it.payload.group, it.payload.field)} → ${fmt(it.payload.value)}` : it.payload.name;
    const itemSub = (it) => it.kind === "profile_field" ? (it.payload.source_type === "agent" ? "agent" : it.payload.source_type || "") + (it.source_ref ? " · " + stripUrl(it.source_ref).slice(0, 48) : "") : `${(it.payload.reasons || []).slice(0, 2).join(" · ")}`;
    const pillsHtml = `<div class="pills" style="align-self:flex-start"><button class="pill ${!filter ? "on" : ""}" data-lang="">All ${total}</button>${summary.languages.map((l) => `<button class="pill ${filter === l.language_id ? "on" : ""}" data-lang="${esc(l.language_id)}">${esc(l.name)} ${l.total}</button>`).join("")}</div>`;
    el.innerHTML = `${pillsHtml}<div class="two-col wide" style="padding-left:22px">
      <div class="queue"><div class="qhead"><span class="eyebrow">Review queue${filter ? " · " + esc(langName(filter)) : ""}</span><span class="n">${items.length ? `${items.length} waiting` : "Nothing waiting"}</span><span class="note">${[facts ? plural(facts, "language fact") : "", res ? plural(res, "resource") : ""].filter(Boolean).join(" · ") || "Uncertain resources and proposed facts land here."}</span></div>
        ${items.slice(0, 40).map((it) => `<button class="qitem ${it.id === state.reviewSel ? "on" : ""}" data-sel="${it.id}"><span class="k ${it.kind === "profile_field" ? "amber" : ""}">${it.kind === "profile_field" ? `Language fact · ${Math.round((it.confidence || 0) * 100)}%` : `Resource · score ${it.payload.relevance ?? "—"}`}${!filter ? ` · ${esc(it.language_id)}` : ""}</span><span class="t">${esc(itemTitle(it))}</span><span class="s">${esc(itemSub(it))}</span></button>`).join("")}
        ${items.length > 40 ? `<span class="qmore">${items.length - 40} more</span>` : ""}</div>
      <div class="detail" id="review-detail">${sel ? "" : `<div class="empty">Nothing to review${filter ? " for " + esc(langName(filter)) : ""}. Every accepted fact is in the profile; every accepted resource is confirmed.</div>`}</div></div>`;
    $$("[data-lang]", el).forEach((b) => b.addEventListener("click", () => { state.reviewLang = b.dataset.lang || null; state.reviewSel = null; renderers.review(); }));
    $$("[data-sel]", el).forEach((b) => b.addEventListener("click", () => { state.reviewSel = Number(b.dataset.sel); renderers.review(); }));
    state.reviewKeys = null;
    if (!sel) return;
    const it = sel, det = $("#review-detail");
    const isFact = it.kind === "profile_field";
    const values = isFact && Array.isArray(it.payload.value) ? it.payload.value : null;
    const existing = isFact && state.lang === it.language_id && state.profileData ? fmt(state.profileData.profile[it.payload.group]?.[it.payload.field]) : "";
    det.innerHTML = `<div class="status ${isFact ? "" : "grey"}"><i class="dot lg ${isFact ? "amber" : "grey"}"></i><span class="eyebrow ${isFact ? "amber" : ""}">${isFact ? "Possible new language information" : "Uncertain resource"}</span><span class="count">${idx + 1} / ${items.length}</span></div>
      <div style="display:flex;flex-direction:column;gap:14px"><h1 class="display">${esc(isFact ? (values ? `${values.length === 1 ? "A new value" : `${cap(num(values.length))} values`} for ${fieldLabel(it.payload.group, it.payload.field).toLowerCase()}` : `${fieldLabel(it.payload.group, it.payload.field)}: ${fmt(it.payload.value)}`) : it.payload.name)}</h1>
        <span style="font-size:15px;color:var(--muted)">${isFact ? `Proposed for <span class="mono" style="font-size:13px;color:var(--ink)">${esc(it.payload.group)}.${esc(it.payload.field)}</span> with ${Math.round((it.confidence || 0) * 100)}% confidence · found by ${esc(it.payload.source_type === "agent" ? "the agent" : it.payload.source_type || "a catalogue")}` : `Relevance ${it.payload.relevance} (${esc(it.payload.band)}) — ${esc((it.payload.reasons || []).join("; "))}`} · ${esc(when(it.created_at))}</span></div>
      ${values ? `<div class="chips">${values.map((v) => `<span class="chip lg">${esc(fmt(v))}</span>`).join("")}</div>` : ""}
      ${it.payload.quote ? `<blockquote class="quote">“${esc(it.payload.quote)}”</blockquote>` : ""}
      <div class="kv"><span class="k">Language</span><span class="v">${esc(langName(it.language_id))} <span class="mono muted">${esc(it.language_id)}</span></span>
        <span class="k">Source</span><span class="v">${linkOrText(it.source_ref)}</span>
        ${isFact ? `<span class="k">Already recorded</span><span class="v">${existing ? esc(existing) + " — accepting adds to it; nothing is replaced" : "nothing yet for this field"}</span>` : `<span class="k">Resource</span><span class="v">${it.payload.resource_id ? `<a class="link" data-rid-open="${it.payload.resource_id}">#${it.payload.resource_id} · open in the collection</a>` : "—"}</span>`}
        ${it.session_id ? `<span class="k">Session</span><span class="v mono">${esc(it.session_id)}</span>` : ""}</div>
      <div class="actions" style="padding-top:8px"><button class="btn lg primary" data-act="accept">Accept ${kbd("A")}</button><button class="btn lg danger" data-act="reject">Reject ${kbd("R")}</button><button class="btn lg outline" data-act="view">View source ${kbd("V")}</button><button class="btn lg quiet" data-act="skip">Skip ${kbd("S")}</button><span class="grow"></span><button class="btn lg quiet" data-act="back">Back ${kbd("B")}</button></div>
      <div id="review-source" class="hidden"></div>`;
    const act = async (a) => {
      try {
        if (a === "back") { show(state.lang ? "profile" : "home"); return; }
        if (a === "view") { const box = $("#review-source"); box.classList.remove("hidden"); box.innerHTML = `<span class="note"><span class="spinner"></span> loading source …</span>`; const t = await get(`/api/review/${it.id}/source`); box.innerHTML = `<div class="source-box">${esc(t.text || "(no stored text for this item)")}</div>`; return; }
        await post(`/api/review/${it.id}/${a}`); toast(a === "accept" ? "Accepted" : a === "reject" ? "Rejected" : "Skipped");
        state.reviewSel = items[idx + 1]?.id ?? items[idx - 1]?.id ?? null;
        refreshStatus(); if (state.lang) loadProfile().catch(() => {}); renderers.review();
      } catch (e) { fail(e); }
    };
    $$("[data-act]", det).forEach((b) => b.addEventListener("click", () => act(b.dataset.act)));
    $("[data-rid-open]", det)?.addEventListener("click", async () => { state.lang !== it.language_id && await openLanguage(it.language_id, "collection"); showResource(it.payload.resource_id); });
    state.reviewKeys = (k, e) => { const m = { a: "accept", r: "reject", v: "view", s: "skip", b: "back" }; if (m[k]) { e.preventDefault(); act(m[k]); } else if (k === "j" || k === "arrowdown") { if (items[idx + 1]) { state.reviewSel = items[idx + 1].id; renderers.review(); } } else if (k === "k" || k === "arrowup") { if (items[idx - 1]) { state.reviewSel = items[idx - 1].id; renderers.review(); } } };
  };

  // ------------------------------------------------------------------ history (§17)
  renderers.history = async function () {
    const el = $("#view-history");
    const { sessions } = await get(state.lang ? `/api/history?language=${encodeURIComponent(state.lang)}` : "/api/history");
    const dl = sessions.reduce((n, s) => n + s.downloaded, 0);
    el.innerHTML = `<div class="head"><div class="head-text"><span class="eyebrow">Collection history${state.lang ? " · " + esc(state.profileData.profile.name) : " · all languages"}</span><h1 class="display">${sessions.length ? `${cap(num(sessions.length))} ${sessions.length === 1 ? "session" : "sessions"}, ${plural(dl, "resource")} stored.` : "No collection sessions yet."}</h1><span class="note">Every run is a session with its own event log. Click one to read it.</span></div>
      ${state.lang ? `<div class="head-side"><button class="btn outline" id="hist-all">All languages</button></div>` : ""}</div>
      ${sessions.length ? `<div class="rows"><div class="thead cols-hist"><span>Session</span><span>Language · mode</span><span>Started</span><span>Discovered · relevant · stored · dup · failed · review</span></div>
      ${sessions.map((s) => `<div class="trow cols-hist click" data-sid="${esc(s.id)}"><span class="cell mono" style="color:var(--ink)">${esc(s.id)}</span><div style="min-width:0"><div class="rtitle" style="font-size:15px">${esc(s.language_name)} <span class="mono muted" style="font-size:12px">${esc(s.language_id)}</span></div><div class="rsub">${esc(s.mode)} · ${esc(s.status)}</div></div><span class="cell">${esc(when(s.started_at))}</span><span class="cell mono">${s.discovered} · ${s.relevant} · ${s.downloaded} · ${s.duplicates} · ${s.failed} · ${s.pending_review}</span></div>`).join("")}</div>` : ""}
      <div id="session-detail"></div>`;
    $("#hist-all")?.addEventListener("click", () => { state.lang = null; state.profileData = null; syncSidebar(); renderers.history(); });
    $$("[data-sid]", el).forEach((r) => r.addEventListener("click", async () => {
      const d = await get(`/api/sessions/${encodeURIComponent(r.dataset.sid)}`);
      $("#session-detail").innerHTML = `<div class="panel" style="gap:20px">${summaryHtml(d.session)}<pre class="log" style="max-height:480px">${d.events.map((e) => `${esc(e.ts)}  ${esc(String(e.level).padEnd(5))}  ${esc(e.message)}`).join("\n") || "(no events)"}</pre></div>`;
      $("#session-detail").scrollIntoView({ behavior: "smooth", block: "start" });
    }));
  };

  // ------------------------------------------------------------------ settings
  const engineForm = (id) => `<form id="${id}" class="form-grid"><input name="name" placeholder="name" required><select name="kind"><option value="json">json API</option><option value="rss">rss / atom</option><option value="html">html page</option></select><input name="url" class="full" placeholder="URL template with {q} ({key} {cx} {lang})" required><input name="items" placeholder="json: result list path (results)"><input name="fields" placeholder="json: url=url, title=title, snippet=content"><input name="link_pattern" placeholder="html: regex, group 1 = URL"><input name="what" placeholder="description"><label class="check"><input type="checkbox" name="needs_key"> needs a key</label><div><button class="btn primary sm">Add engine</button></div></form>`;
  function readEngineForm(form) {
    const fd = new FormData(form); const cfg = {}; fd.forEach((v, k) => { if (String(v).trim()) cfg[k] = String(v).trim(); });
    if (cfg.needs_key) cfg.needs_key = true;
    if (cfg.fields) { const f = {}; cfg.fields.split(",").forEach((p) => { const [k, v] = p.split("=").map((s) => s.trim()); if (k && v) f[k] = v; }); cfg.fields = f; }
    return cfg;
  }
  renderers.settings = async function () {
    const el = $("#view-settings");
    const [prov, eng, cats] = await Promise.all([get("/api/agent/provider"), get("/api/agent/engines"), get("/api/catalogues")]);
    const usable = eng.engines.filter((e) => e.enabled && e.available).length;
    el.innerHTML = `<div class="head"><div class="head-text"><span class="eyebrow">Settings</span><h1 class="display">How the agent works for you.</h1><span class="note">Everything here is saved to <span class="mono">${esc(state.status.home)}/config/config.toml</span> and used by the terminal interface too.</span></div></div>
      <div class="panel"><div class="section-head" style="padding:0"><h3>Agent provider</h3></div><div class="form-row"><select id="set-provider" style="min-width:420px">${prov.choices.map((c) => `<option value="${esc(c.name)}" ${c.current ? "selected" : ""} ${c.installed ? "" : "disabled"}>${esc(c.name)} — ${esc(c.what)}${c.installed ? "" : " (not installed)"}</option>`).join("")}</select></div>
        <span class="note">rule_based needs no model and never leaves the machine. A model provider receives the language profile and the text of visited pages.</span></div>
      <div class="panel"><div class="section-head" style="padding:0"><h3>Search engines</h3><span class="note">${usable} usable of ${eng.engines.length} · ticked engines are asked in the order shown</span></div>
        <div class="rows"><div class="thead cols-eng"><span></span><span>Engine</span><span>Kind</span><span>What</span><span></span></div>${eng.engines.map((e) => `<div class="trow cols-eng" style="padding:12px 0"><input type="checkbox" class="eng" value="${esc(e.name)}" ${e.enabled ? "checked" : ""} style="width:16px;height:16px;accent-color:var(--ink);margin:0"><span style="font-weight:500">${esc(e.name)} ${e.available ? "" : `<span class="tag amber" title="${esc(e.why)}">needs key</span>`}${e.verified ? "" : ' <span class="tag">unverified</span>'}</span><span class="cell mono">${esc(e.kind)}</span><span class="cell">${esc(e.what)}${e.region ? ` · ${esc(e.region)}` : ""}</span><span class="actions" style="justify-content:flex-end"><button class="link" data-test="${esc(e.name)}">test</button>${e.source !== "builtin" ? `<button class="link danger" data-rm="${esc(e.name)}">remove</button>` : ""}</span></div>`).join("")}</div>
        <div class="actions"><button id="set-engines" class="btn primary sm">Save selection</button><span class="note">Keys go under [agent.search_keys] in config.toml or an AIMIXE_SEARCH_KEY_&lt;NAME&gt; environment variable.</span></div>
        <pre id="engine-test" class="log hidden"></pre>
        <details class="more"><summary>Add an engine</summary>${engineForm("engine-add")}</details></div>
      <div class="panel"><div class="section-head" style="padding:0"><h3>Catalogues</h3><button class="link" id="set-catalogues">Manage and add catalogues</button></div>
        <div class="chips">${cats.catalogues.map((c) => `<span class="chip ${c.enabled ? "" : "off"}">${esc(c.name)} <span class="muted">${esc(c.kind)}${c.enabled ? "" : " · disabled"}</span></span>`).join("")}</div></div>`;
    $("#set-provider").addEventListener("change", async (e) => { try { await post("/api/agent/provider", { provider: e.target.value }); toast(`Agent provider: ${e.target.value}`); refreshStatus(); } catch (err) { fail(err); } });
    $("#set-engines").addEventListener("click", async () => { const names = $$("input.eng:checked", el).map((i) => i.value); try { await post("/api/agent/engines", { enabled: names }); toast("Search engines: " + (names.join(", ") || "none")); await refreshStatus(); renderers.settings(); } catch (err) { fail(err); } });
    $$("button[data-test]", el).forEach((b) => b.addEventListener("click", async () => { const pre = $("#engine-test"); pre.classList.remove("hidden"); pre.textContent = `testing ${b.dataset.test} …`; try { const r = await get(`/api/agent/engines/${encodeURIComponent(b.dataset.test)}/test?q=language%20documentation`); pre.textContent = r.hits.length ? r.hits.map((h) => `${h.title || "(no title)"}\n    ${h.url}`).join("\n") : "no hits"; } catch (err) { pre.textContent = err.message; } }));
    $$("button[data-rm]", el).forEach((b) => b.addEventListener("click", async () => { try { const r = await del(`/api/agent/engines/${encodeURIComponent(b.dataset.rm)}`); toast(r.message); renderers.settings(); } catch (err) { fail(err); } }));
    $("#set-catalogues").addEventListener("click", () => show("catalogues"));
    $("#engine-add").addEventListener("submit", async (ev) => { ev.preventDefault(); try { await post("/api/agent/engines", { engine: readEngineForm(ev.target) }); toast("Engine saved"); renderers.settings(); } catch (err) { fail(err); } });
  };

  // ------------------------------------------------------------------ catalogues management
  renderers.catalogues = async function () {
    const el = $("#view-catalogues");
    const d = await get("/api/catalogues");
    el.innerHTML = `<div class="head"><div class="head-text"><span class="eyebrow">Settings · Catalogues</span><h1 class="display">Where the catalogue search looks.</h1><span class="note">Built-in providers ship as data; your own go to ~/.aimixe/catalogues/&lt;name&gt;.toml. Templates: {q} the search term, {name} the profile name, {code} the ISO 639-3 code.</span></div><div class="head-side"><button class="btn outline" id="cats-back">Back to settings</button></div></div>
      <div class="rows"><div class="thead cols-cats"><span>Catalogue</span><span>Kind</span><span>What</span><span></span></div>${d.catalogues.map((c) => `<div class="trow cols-cats"><span style="font-weight:500">${esc(c.name)}${c.enabled ? "" : ' <span class="tag">disabled</span>'}</span><span class="cell mono">${esc(c.kind)}${c.mode !== "python" && c.mode !== c.kind ? ` · ${esc(c.mode)}` : ""}</span><div><div style="font-size:14px">${esc(c.what)}</div>${c.licence_note ? `<div class="rsub">${esc(c.licence_note)}</div>` : ""}<div class="rsub mono">${esc(c.source === "builtin" ? "built-in" : c.source)} · asks by ${esc(c.asks_by)}</div></div><span class="actions" style="justify-content:flex-end">${c.enabled ? `<button class="link danger" data-rm="${esc(c.name)}">${c.source === "builtin" ? "disable" : "remove"}</button>` : ""}</span></div>`).join("")}</div>
      ${d.errors.map((e) => `<p class="note" style="color:var(--red)">${esc(e)}</p>`).join("")}
      <div class="panel"><h3>Add a catalogue</h3><form id="cat-add" class="form-grid">
        <input name="name" placeholder="name (e.g. my_university_repo)" required>
        <select name="kind"><option value="lookup">lookup — a URL to open; nothing fetched</option><option value="api_json">api_json — JSON search API</option><option value="html_links">html_links — links on a web page</option></select>
        <input name="url" class="full" placeholder="URL template with {q} {name} {code}" required>
        <select name="asks_by"><option value="name">search by name</option><option value="code">search by ISO code</option><option value="both">both</option></select>
        <input name="what" placeholder="short description"><input name="licence_note" placeholder="licence note">
        <input name="items" placeholder="api_json: path to results (hits.hits)">
        <input name="fields" class="full" placeholder="api_json field paths, e.g. title=metadata.title, url=links.html, download=files[].links.self">
        <input name="link_pattern" placeholder="html_links: regex a link must match">
        <div><button class="btn primary sm">Add catalogue</button></div></form></div>`;
    $("#cats-back").addEventListener("click", () => show("settings"));
    $$("button[data-rm]", el).forEach((b) => b.addEventListener("click", async () => { try { const r = await del(`/api/catalogues/${encodeURIComponent(b.dataset.rm)}`); toast(r.message); await refreshStatus(); renderers.catalogues(); } catch (e) { fail(e); } }));
    $("#cat-add").addEventListener("submit", async (e) => {
      e.preventDefault();
      const fd = new FormData(e.target); const cfg = {}; fd.forEach((v, k) => { if (String(v).trim()) cfg[k] = String(v).trim(); });
      if (cfg.fields) { const f = {}; cfg.fields.split(",").forEach((pair) => { const [k, v] = pair.split("=").map((s) => s.trim()); if (k && v) f[k] = v; }); cfg.fields = f; }
      try { await post("/api/catalogues", cfg); toast("Catalogue saved"); await refreshStatus(); renderers.catalogues(); } catch (err) { fail(err); }
    });
  };

  // ------------------------------------------------------------------ boot
  Promise.all([refreshStatus(), loadSchema()]).then(async () => {
    watchJobs();
    const m = /^#([a-z]+)(?::([^&]+))?$/.exec(location.hash || "");
    if (m && m[2] && state.status.languages.some((l) => l.id === m[2])) { await openLanguage(m[2], renderers[m[1]] ? m[1] : "profile"); return; }
    if (m && m[1] === "review") state.reviewLang = null;
    show(m && renderers[m[1]] && !$(`#nav [data-view="${m[1]}"]`)?.classList.contains("needs-lang") ? m[1] : "home");
  }).catch(fail);
})();
