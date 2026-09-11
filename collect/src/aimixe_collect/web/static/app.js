/* AImixE Data Collection — local web interface. Talks only to /api; the same services as the CLI. */
(() => {
  "use strict";
  const $ = (sel, el = document) => el.querySelector(sel);
  const $$ = (sel, el = document) => Array.from(el.querySelectorAll(sel));
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const state = { lang: null, status: null, schema: null, lastCatalogueJob: null, view: "home" };

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

  // ------------------------------------------------------------------ values
  function fmt(v) {
    if (v === null || v === undefined || (Array.isArray(v) && !v.length)) return "—";
    if (Array.isArray(v)) return v.map(fmt).join(", ");
    if (typeof v === "object") {
      if ("state" in v) return v.state + (v.detail ? ` (${v.detail})` : "");
      if ("name" in v) { const extra = ["type", "region", "country", "role"].filter((k) => v[k]).map((k) => v[k]); return v.name + (extra.length ? ` (${extra.join(", ")})` : ""); }
      if ("code" in v && "name" in v) return `${v.name} [${v.code}]`;
      if ("value" in v) { const extra = ["type", "detail", "code"].filter((k) => v[k]).map((k) => v[k]); return String(v.value) + (v.approximate ? " (approx.)" : "") + (extra.length ? ` (${extra.join(", ")})` : ""); }
      if ("min" in v) return `${v.min}–${v.max}`;
      if ("title" in v || "kind" in v) return ["kind", "title", "date", "organisation", "url"].filter((k) => v[k]).map((k) => v[k]).join(" · ");
      if ("text" in v) return v.text + Object.keys(v).filter((k) => k !== "text").map((k) => `; ${k}: ${fmt(v[k])}`).join("");
      return Object.entries(v).filter(([, x]) => x !== null && x !== "").map(([k, x]) => `${k}: ${fmt(x)}`).join("; ");
    }
    if (typeof v === "boolean") return v ? "yes" : "no";
    return String(v);
  }

  // ------------------------------------------------------------------ navigation
  function syncLayout() { $(".layout").classList.toggle("no-nav", $("#nav").classList.contains("hidden")); }
  function show(view) {
    state.view = view;
    syncLayout();
    $$(".view").forEach((v) => v.classList.add("hidden"));
    $(`#view-${view}`).classList.remove("hidden");
    $$("#nav button").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
    const render = { home: renderHome, settings: renderSettings, profile: renderProfile, catalogue: renderCatalogue, agent: renderAgent, offline: renderOffline,
      import: renderImport, collection: renderCollection, review: renderReview, history: renderHistory, catalogues: renderCatalogues }[view];
    if (render) render().catch(fail);
  }
  $$("#nav button").forEach((b) => b.addEventListener("click", () => show(b.dataset.view)));
  $("#btn-new-language").addEventListener("click", () => { state.lang = null; $("#nav").classList.add("hidden"); $("#lang-select").value = ""; show("find"); });
  $("#btn-home").addEventListener("click", () => { state.lang = null; $("#nav").classList.add("hidden"); $("#lang-select").value = ""; show("home"); });
  $("#btn-settings").addEventListener("click", () => show("settings"));

  async function refreshStatus() {
    state.status = await get("/api/status");
    $("#home-path").textContent = state.status.home;
    $("#version").textContent = "v" + (state.status.version || "");
    const sel = $("#lang-select");
    const current = sel.value;
    sel.innerHTML = '<option value="">— choose —</option>' + state.status.languages.map((l) => `<option value="${esc(l.id)}">${esc(l.name)} [${esc(l.iso639_3 || l.id)}]</option>`).join("");
    sel.value = state.lang || current || "";
    const badge = $("#review-badge");
    badge.textContent = state.status.pending_review; badge.classList.toggle("hidden", !state.status.pending_review);
  }
  $("#lang-select").addEventListener("change", (e) => { if (e.target.value) openLanguage(e.target.value); });

  async function openLanguage(id) {
    state.lang = id;
    const data = await get(`/api/languages/${encodeURIComponent(id)}`);
    state.profileData = data;
    $("#nav").classList.remove("hidden");
    syncLayout();
    $("#nav-lang").innerHTML = `${esc(data.profile.name)} <small>${esc(data.profile.iso639_3 ? "ISO 639-3 " + data.profile.iso639_3 : "local identifier " + data.profile.id)} · ${data.resource_count} resource(s)</small>`;
    $("#lang-select").value = id;
    show("profile");
  }

  // ------------------------------------------------------------------ home
  const when = (iso) => { if (!iso) return ""; const t = new Date(iso); const d = Math.floor((new Date().setHours(0,0,0,0) - new Date(t).setHours(0,0,0,0)) / 86400000); return d === 0 ? `today ${t.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}` : d === 1 ? "yesterday" : d < 7 ? `${d} days ago` : t.toLocaleDateString(); };
  async function renderHome() {
    const el = $("#view-home");
    const d = await get("/api/home");
    if (!d.languages.length) {
      el.innerHTML = `<h1>Welcome</h1><p class="muted">AImixE collects language resources three ways: online (catalogues and an agent searching the web), offline (scanning folders on this machine) and by direct import. Every file is hashed, classified, stored unchanged and indexed with where it came from. Start by naming a language; the profile you build for it steers every search.</p><p><button id="home-new">New language</button></p>`;
      $("#home-new").addEventListener("click", () => show("find"));
      return;
    }
    el.innerHTML = `<h1>Languages</h1>
      <div class="lang-list">${d.languages.map((l, i) => `<div class="lang-card" data-id="${esc(l.id)}">
        <div class="lang-idx">${i + 1}</div>
        <div class="lang-main"><div><b>${esc(l.name)}</b> <span class="mono muted">${esc(l.iso639_3 || l.id)}</span>${l.identifier_type === "local" ? ' <span class="tag uncertain">local id</span>' : ""}</div>
          <div class="muted">${l.resources} resource(s)${l.pending_review ? ` · <span class="warn">${l.pending_review} to review</span>` : ""}${l.last_session ? ` · last: ${esc(when(l.last_session.started_at))} · ${esc(l.last_session.mode)}` : " · never collected"}</div>
          <div class="hint">→ ${esc(l.next_step)}</div></div>
        <div class="lang-actions"><button class="small" data-open="${esc(l.id)}">Open</button>${l.pending_review ? `<button class="small ghost" data-review="${esc(l.id)}">Review</button>` : ""}</div>
      </div>`).join("")}</div>
      <div class="row actions-row">
        <button id="home-new">New language</button>
        <button id="home-review" class="ghost" ${d.pending_review ? "" : "disabled"}>Review everything waiting${d.pending_review ? ` (${d.pending_review})` : ""}</button>
        <button id="home-history" class="ghost">Collection history</button>
        <button id="home-settings" class="ghost">Settings</button>
      </div>`;
    $$("button[data-open]", el).forEach((b) => b.addEventListener("click", () => openLanguage(b.dataset.open)));
    $$("button[data-review]", el).forEach((b) => b.addEventListener("click", async () => { state.reviewLang = undefined; await openLanguage(b.dataset.review); show("review"); }));
    $$(".lang-card", el).forEach((c) => c.addEventListener("dblclick", () => openLanguage(c.dataset.id)));
    $("#home-new").addEventListener("click", () => show("find"));
    $("#home-review").addEventListener("click", () => { state.lang = null; state.reviewLang = null; show("review"); });
    $("#home-history").addEventListener("click", () => { state.lang = null; show("history"); });
    $("#home-settings").addEventListener("click", () => show("settings"));
  }

  // ------------------------------------------------------------------ settings
  async function renderSettings() {
    const el = $("#view-settings");
    const [prov, eng, cats] = await Promise.all([get("/api/agent/provider"), get("/api/agent/engines"), get("/api/catalogues")]);
    el.innerHTML = `<h1>Settings</h1>
      <div class="card"><h2>Agent provider</h2>
        <p class="row"><select id="set-provider">${prov.choices.map((c) => `<option value="${esc(c.name)}" ${c.current ? "selected" : ""} ${c.installed ? "" : "disabled"}>${esc(c.name)} — ${esc(c.what)}${c.installed ? "" : " (not installed)"}</option>`).join("")}</select></p>
        <p class="muted">rule_based needs no model and never leaves the machine. A model provider receives the language profile and the text of visited pages. Saved to config.toml.</p></div>
      <div class="card"><h2>Search engines <span class="muted">(${eng.engines.filter((e) => e.enabled && e.available).length} usable of ${eng.engines.length})</span></h2>
        <table><tr><th></th><th>name</th><th>kind</th><th>state</th><th>region</th><th>what</th><th></th></tr>
        ${eng.engines.map((e) => `<tr><td><input type="checkbox" class="eng" value="${esc(e.name)}" ${e.enabled ? "checked" : ""}></td><td>${esc(e.name)}</td><td>${esc(e.kind)}</td><td>${e.available ? "" : `<span class="tag uncertain" title="${esc(e.why)}">needs key</span>`}${e.verified ? "" : ' <span class="tag">unverified</span>'}</td><td class="muted">${esc(e.region)}</td><td>${esc(e.what)}</td><td><button class="small ghost" data-test="${esc(e.name)}">test</button>${e.source !== "builtin" ? ` <button class="small danger" data-rm="${esc(e.name)}">remove</button>` : ""}</td></tr>`).join("")}</table>
        <div class="row"><button id="set-engines" class="small">Save selection</button><span class="muted">Ticked engines are asked in the order shown. Keys go under [agent.search_keys] in config.toml.</span></div>
        <pre id="engine-test" class="log hidden"></pre>
        <h3>Add an engine</h3>
        <form id="engine-add" class="row"><input name="name" placeholder="name" required><select name="kind"><option value="json">json API</option><option value="rss">rss / atom</option><option value="html">html page</option></select><input name="url" placeholder="URL template with {q} ({key} {cx} {lang})" size="48" required><input name="items" placeholder="json: result list path (results)"><input name="fields" placeholder="json: url=url, title=title, snippet=content" size="40"><input name="link_pattern" placeholder="html: regex, group 1 = URL"><input name="what" placeholder="description" size="30"><label><input type="checkbox" name="needs_key"> needs key</label><button class="small">Add engine</button></form></div>
      <div class="card"><h2>Catalogues</h2>
        <table><tr><th>name</th><th>kind</th><th>enabled</th><th>what</th><th></th></tr>${cats.catalogues.map((c) => `<tr><td>${esc(c.name)}</td><td>${esc(c.kind)}</td><td>${c.enabled ? "yes" : "no"}</td><td>${esc(c.what)}</td><td>${c.enabled ? `<button class="small danger" data-cat-rm="${esc(c.name)}">${c.source === "builtin" ? "disable" : "remove"}</button>` : ""}</td></tr>`).join("")}</table>
        <p><button id="set-catalogues" class="ghost small">Add a catalogue…</button></p></div>`;
    $("#set-provider").addEventListener("change", async (e) => { try { await post("/api/agent/provider", { provider: e.target.value }); toast(`Agent provider: ${e.target.value}`); refreshStatus(); } catch (err) { fail(err); } });
    $("#set-engines").addEventListener("click", async () => { const names = $$("input.eng:checked", el).map((i) => i.value); try { await post("/api/agent/engines", { enabled: names }); toast("Search engines: " + (names.join(", ") || "none")); renderSettings(); } catch (err) { fail(err); } });
    $$("button[data-test]", el).forEach((b) => b.addEventListener("click", async () => { const pre = $("#engine-test"); pre.classList.remove("hidden"); pre.textContent = `testing ${b.dataset.test} …`; try { const r = await get(`/api/agent/engines/${encodeURIComponent(b.dataset.test)}/test?q=language%20documentation`); pre.textContent = r.hits.length ? r.hits.map((h) => `${h.title || "(no title)"}\n    ${h.url}`).join("\n") : "no hits"; } catch (err) { pre.textContent = err.message; } }));
    $$("button[data-rm]", el).forEach((b) => b.addEventListener("click", async () => { try { const r = await del(`/api/agent/engines/${encodeURIComponent(b.dataset.rm)}`); toast(r.message); renderSettings(); } catch (err) { fail(err); } }));
    $$("button[data-cat-rm]", el).forEach((b) => b.addEventListener("click", async () => { try { const r = await del(`/api/catalogues/${encodeURIComponent(b.dataset.catRm)}`); toast(r.message); renderSettings(); } catch (err) { fail(err); } }));
    $("#set-catalogues").addEventListener("click", () => show("catalogues"));
    $("#engine-add").addEventListener("submit", async (ev) => {
      ev.preventDefault(); const fd = new FormData(ev.target); const cfg = {}; fd.forEach((v, k) => { if (String(v).trim()) cfg[k] = String(v).trim(); });
      if (cfg.needs_key) cfg.needs_key = true;
      if (cfg.fields) { const f = {}; cfg.fields.split(",").forEach((p) => { const [k, v] = p.split("=").map((s) => s.trim()); if (k && v) f[k] = v; }); cfg.fields = f; }
      try { await post("/api/agent/engines", { engine: cfg }); toast("Engine saved"); renderSettings(); } catch (err) { fail(err); }
    });
  }

  // ------------------------------------------------------------------ find language (§1)
  $("#find-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const q = $("#find-input").value.trim();
    if (!q) return;
    try {
      const res = await get(`/api/resolve?q=${encodeURIComponent(q)}`);
      const box = $("#find-result");
      if (res.status === "none") {
        box.innerHTML = `<div class="card"><p>No language found for “${esc(q)}” in the local registry or the bundled ISO 639-3 / Glottolog tables.</p>
          <h3>Create a new language profile</h3>
          <form id="create-form" class="row"><input id="create-name" value="${esc(q)}" placeholder="Language name"><input id="create-code" placeholder="ISO 639-3 code, if known"><button>Create profile</button></form>
          <p class="muted">Without a valid ISO code a local identifier (x-…) is used and labelled as such.</p></div>`;
        $("#create-form").addEventListener("submit", async (ev) => {
          ev.preventDefault();
          try { const r = await post("/api/languages/create", { name: $("#create-name").value, code: $("#create-code").value }); await refreshStatus(); openLanguage(r.language_id); } catch (err) { fail(err); }
        });
        return;
      }
      const cards = res.matches.slice(0, 8).map((m, i) => `
        <div class="card detected">
          ${i === 0 && res.status === "exact" ? "<h1>Language detected</h1>" : ""}
          <dl class="kv">
            <dt>Name</dt><dd>${esc(m.name)}</dd>
            <dt>ISO 639-3</dt><dd>${esc(m.iso639_3 || "— (local identifier " + m.language_id + ")")}</dd>
            ${m.alternative_names.length ? `<dt>Alternative names</dt><dd>${esc(m.alternative_names.slice(0, 6).join(", "))}</dd>` : ""}
            ${m.region ? `<dt>Region</dt><dd>${esc(m.region)}</dd>` : ""}
            ${m.family ? `<dt>Family</dt><dd>${esc(m.family)}</dd>` : ""}
            ${m.matched_on !== "name" && m.matched_on !== "code" ? `<dt>Matched on</dt><dd>${esc(m.matched_on.replace("_", " "))} “${esc(m.matched_text)}”</dd>` : ""}
            ${m.source === "local_registry" ? `<dt>Source</dt><dd>local language registry (profile already stored)</dd>` : ""}
          </dl>
          <p><button data-open="${m.index}">Continue with this language</button></p>
        </div>`).join("");
      box.innerHTML = (res.status === "ambiguous" ? `<p>Several languages match “${esc(q)}”. Choose one:</p>` : "") + cards;
      $$("button[data-open]", box).forEach((b) => b.addEventListener("click", async () => {
        try { const r = await post("/api/languages/open", { query: q, index: Number(b.dataset.open) }); await refreshStatus(); if (r.created) toast(`Profile created for ${r.language_id}`); openLanguage(r.language_id); } catch (err) { fail(err); }
      }));
    } catch (err) { fail(err); }
  });

  // ------------------------------------------------------------------ profile (§2)
  async function renderProfile() {
    const [data, schema] = await Promise.all([get(`/api/languages/${encodeURIComponent(state.lang)}`), state.schema ? Promise.resolve(state.schema) : get("/api/schema")]);
    state.schema = schema; state.profileData = data;
    const p = data.profile, st = data.status;
    const key = (g, f) => `${g}.${f}`;
    const toAsk = new Set(st.to_ask.map(([g, f]) => key(g, f)));
    const uncertain = new Set(st.uncertain.map(([g, f]) => key(g, f)));
    const contradictory = new Set(st.contradictory.map(([g, f]) => key(g, f)));
    const el = $("#view-profile");
    el.innerHTML = `
      <h1>Language Profile — ${esc(p.name)} <span class="muted">[${esc(p.iso639_3 || p.id)}]</span></h1>
      <ul class="progress"><li class="done">✓ Basic identification</li>
        ${schema.groups.map((g) => `<li class="${st.groups[g.name]}">${st.groups[g.name] === "done" ? "✓" : "○"} ${esc(g.progress_label)}</li>`).join("")}</ul>
      <div class="card summary-groups">${schema.groups.map((g) => {
        const lbl = (gn, f) => g.fields.find((x) => x.name === f)?.label || f;
        const known = st.known.filter(([gn, f]) => gn === g.name && !uncertain.has(key(gn, f)) && !contradictory.has(key(gn, f))).map(([gn, f]) => lbl(gn, f));
        const shaky = st.known.filter(([gn, f]) => gn === g.name && (uncertain.has(key(gn, f)) || contradictory.has(key(gn, f)))).map(([gn, f]) => lbl(gn, f));
        const missing = st.to_ask.filter(([gn, f]) => gn === g.name && !uncertain.has(key(gn, f)) && !contradictory.has(key(gn, f))).map(([gn, f]) => lbl(gn, f));
        return `<div class="sg-row"><div class="sg-name">${esc(g.progress_label)}</div><div>${known.length ? `<span class="ok">✓</span> ${esc(known.join(" · "))}` : ""}${shaky.length ? `<br><span class="warn">?</span> ${esc(shaky.join(" · "))} <span class="muted">(uncertain — will be asked again)</span>` : ""}${missing.length ? `<br><span class="muted">– ${esc(missing.join(" · "))}</span>` : ""}</div></div>`; }).join("")}
      <p class="muted">${st.known.length} known · ${st.to_ask.length} to fill. Values from the bundled tables are marked <em>local_database</em>; your answers <em>user</em>. Nothing is overwritten: sources that disagree are kept side by side.</p></div>
      <div class="card row"><button id="profile-propose">Ask catalogues and the agent to propose values</button><span class="muted">Glottolog plus a short read of pages about the language; nothing is downloaded; each fact goes to the review queue.</span></div>
      <pre id="propose-log" class="log hidden"></pre>
      ${schema.groups.map((g) => `
        <div class="card"><h2>${esc(g.title)} <span class="tag">${esc(st.groups[g.name])}</span></h2>
          ${g.fields.map((f) => {
            const k = key(g.name, f.name);
            const val = p[g.name][f.name];
            const envs = (p.provenance[g.name] || {})[f.name] || [];
            const flag = contradictory.has(k) ? '<span class="tag uncertain">sources disagree</span>' : uncertain.has(k) ? '<span class="tag uncertain">uncertain</span>' : toAsk.has(k) ? '<span class="tag missing">missing</span>' : "";
            return `<div class="field" data-group="${g.name}" data-field="${f.name}">
              <div class="row"><span class="label">${esc(f.label)}</span>${flag}<button class="small ghost edit">edit</button></div>
              <div class="current">${esc(fmt(val))}</div>
              ${envs.map((e) => `<div class="prov ${e.status === "proposed" ? "proposed" : ""}">${e.preferred ? "★ " : ""}${esc(fmt(e.value))} — <span class="src">${esc(e.source_type)}${e.source ? ": " + esc(e.source) : ""}</span>${e.year ? ` (${e.year})` : ""}, confidence ${Number(e.confidence).toFixed(2)}${e.status !== "accepted" ? ` [${e.status}]` : ""}${e.note ? ` — ${esc(e.note)}` : ""}</div>`).join("")}
              <form class="editor">${editorFor(f)}</form>
            </div>`;
          }).join("")}
        </div>`).join("")}`;
    $("#profile-propose").addEventListener("click", async () => {
      const log = $("#propose-log"); log.classList.remove("hidden");
      try {
        const j = await runJob("profile_enrich", {}, log);
        const c = j.result || {};
        toast(`${c.catalogue || 0} fact(s) from Glottolog, ${c.agent || 0} from ${c.pages || 0} page(s)`);
        if ((c.catalogue || 0) + (c.agent || 0) > 0) show("review"); else renderProfile();
      } catch (e) { fail(e); }
    });
    $$(".field", el).forEach((fieldEl) => {
      const form = $(".editor", fieldEl);
      $(".edit", fieldEl).addEventListener("click", () => form.classList.toggle("open"));
      form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const fd = new FormData(form); const obj = {}; fd.forEach((v, k) => obj[k] = v);
        try {
          await post(`/api/languages/${encodeURIComponent(state.lang)}/profile`, { group: fieldEl.dataset.group, field: fieldEl.dataset.field, form: obj });
          toast("Recorded"); renderProfile();
        } catch (err) { fail(err); }
      });
    });
  }

  function editorFor(f) {
    const sug = f.suggested || [];
    const dl = sug.length ? `<datalist id="dl-${f.name}">${sug.map((s) => `<option value="${esc(s)}">`).join("")}</datalist>` : "";
    const help = `<div class="help">${esc(f.help || "")} ${sug.length && !["state", "basis", "parent", "community", "entries"].includes(f.kind) ? "Suggested: " + esc(sug.join(", ")) : ""}</div>`;
    const save = `<button>Save</button>`;
    switch (f.kind) {
      case "text": return `${help}<input name="value" placeholder="${esc(f.prompt)}">${save}`;
      case "choice": return `${help}<input name="value" list="dl-${f.name}" placeholder="pick or describe">${dl}${save}`;
      case "list": case "scripts": return `${help}<input name="value" placeholder="comma separated" size="50">${save}`;
      case "tagged_list": return `${help}<input name="value" placeholder="Hindi (lingua franca), Assamese: regional" size="50">${save}`;
      case "state": return `${help}<select name="state"><option value="">state…</option>${["yes", "no", "unknown", "limited", "reported", "historical"].map((s) => `<option>${s}</option>`).join("")}</select><input name="detail" placeholder="detail (optional)" size="40">${save}`;
      case "speakers": return `${help}<input name="value" placeholder="8500 · ~8500 · 8000-9000">${save}`;
      case "parent": return `${help}<input name="value" placeholder="parent language / group"><select name="type"><option value="">type…</option>${sug.map((s) => `<option>${esc(s)}</option>`).join("")}</select>${save}`;
      case "places": return `${help}<textarea name="value" placeholder="one per line: name, type, region, country&#10;Changlang, district, Arunachal Pradesh, India"></textarea>${save}`;
      case "basis": return `${help}<input name="type" list="dl-${f.name}" placeholder="type (census, fieldwork, …)">${dl}<input name="year" placeholder="year" size="6"><input name="source" placeholder="source" size="30">${save}`;
      case "age_spread": return `${help}${["children", "young_adults", "adults", "elderly"].map((k) => `<label>${k.replace("_", " ")} <select name="${k}"><option value="">?</option><option>yes</option><option>no</option><option>unknown</option></select></label>`).join("")}<input name="note" placeholder="note" size="30">${save}`;
      case "entries": return `${help}<textarea name="value" placeholder="no · unknown · or one per line: kind | title | date | organisation | url&#10;Bible translation | New Testament | 2005 | Bible Society of India"></textarea><div class="help">Kinds: ${esc(sug.join(", "))}</div>${save}`;
      case "community": return `${help}<textarea name="value" placeholder="community information"></textarea>${sug.map((a) => `<input name="${a.replace(/ /g, "_")}" placeholder="${esc(a)} (comma separated)" size="34">`).join("")}${save}`;
      default: return `${help}<input name="value">${save}`;
    }
  }

  // ------------------------------------------------------------------ jobs
  function runJob(kind, params, logEl, onDone) {
    return post("/api/jobs", { kind, language_id: state.lang, params }).then(({ job_id }) => new Promise((resolve, reject) => {
      logEl.textContent = "starting …";
      const tick = async () => {
        try {
          const j = await get(`/api/jobs/${job_id}`);
          logEl.textContent = j.log.join("\n") || "…";
          logEl.scrollTop = logEl.scrollHeight;
          renderProgress(logEl, j);
          if (j.status === "running") return setTimeout(tick, 800);
          if (j.status === "failed") { toast(j.error, true); return reject(new Error(j.error)); }
          refreshStatus().catch(() => {});
          if (onDone) onDone(j);
          resolve(j);
        } catch (e) { reject(e); }
      };
      tick();
    }));
  }
  const hb = (n) => n == null ? "?" : n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(0)} KB` : n < 1073741824 ? `${(n / 1048576).toFixed(1)} MB` : `${(n / 1073741824).toFixed(1)} GB`;
  const ht = (s) => s == null ? "—" : s < 60 ? `${Math.round(s)}s` : `${Math.floor(s / 60)}m${String(Math.round(s % 60)).padStart(2, "0")}s`;
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
    box.innerHTML = `<div class="muted">${bits.join(" · ") || "working …"}</div>` + active.map((t) => `
      <div class="xfer"><div class="xfer-name">${esc(t.name)}</div>
        <div class="bar"><div class="bar-fill" style="width:${t.percent != null ? t.percent.toFixed(0) : 100}%"></div></div>
        <div class="xfer-stats">${t.total ? `${t.percent.toFixed(0)}% · ${hb(t.done)} / ${hb(t.total)}` : hb(t.done)} · ${hb(t.speed)}/s${t.eta != null ? ` · eta ${ht(t.eta)}` : ""}</div></div>`).join("");
  }
  function summaryHtml(s) {
    return `<h3>Collection Session: ${esc(s.id)}</h3><p class="muted">Language: ${esc(s.language_name)} [${esc(s.language_id)}] · Mode: ${esc(s.mode)} · ${esc(s.status)}</p>
      <div class="summary">${[["Discovered", s.discovered], ["Relevant", s.relevant], ["Downloaded", s.downloaded], ["Duplicates", s.duplicates], ["Failed", s.failed], ["Pending review", s.pending_review]].map(([k, v]) => `<div><b>${v}</b><span>${k}</span></div>`).join("")}</div>`;
  }
  function outcomesHtml(outs) {
    if (!outs || !outs.length) return "<p class='muted'>No resources.</p>";
    return `<table><tr><th>status</th><th>relevance</th><th>name</th><th>resource type</th><th>note</th></tr>${outs.map((o) => `<tr class="${o.resource_id ? "clickable" : ""}" data-rid="${o.resource_id || ""}"><td class="status-${o.status}">${esc(o.status.replace("_", " "))}</td><td class="score">${o.relevance ?? ""}</td><td>${esc(o.name)}</td><td>${esc((o.types || []).join(", "))}</td><td class="muted">${esc(["failed", "duplicate_linked", "rejected"].includes(o.status) ? o.message : "")}</td></tr>`).join("")}</table>`;
  }
  function wireResourceRows(el) { $$("tr[data-rid]", el).forEach((r) => r.dataset.rid && r.addEventListener("click", () => showResource(Number(r.dataset.rid)))); }

  // ------------------------------------------------------------------ catalogue search (§4.1)
  async function renderCatalogue() {
    const el = $("#view-catalogue");
    const cats = state.status.catalogues;
    el.innerHTML = `<h1>Online Collection — Catalogue Search</h1>
      <div class="card"><div class="checks">${cats.map((c) => `<label><input type="checkbox" name="prov" value="${esc(c.name)}" ${c.enabled ? "checked" : "disabled"}> ${esc(c.name)} <span class="tag">${c.kind}</span></label>`).join("")}</div>
      <p class="muted">Providers search with the whole language profile: ISO code, name, alternative names, varieties, known publications. “lookup” providers have no machine-readable search and return a URL to open.</p>
      <button id="cat-search">Search</button></div>
      <pre id="cat-log" class="log hidden"></pre><div id="cat-results"></div>`;
    $("#cat-search").addEventListener("click", async () => {
      const providers = $$("input[name=prov]:checked", el).map((i) => i.value);
      const log = $("#cat-log"); log.classList.remove("hidden");
      try {
        const j = await runJob("catalogue_search", { providers }, log);
        state.lastCatalogueJob = j.id;
        const r = j.result;
        const cfg = state.status.config;
        $("#cat-results").innerHTML = `<h2>${r.results.length} result(s), ${r.lookups.length} place(s) to open</h2>
          ${r.errors.map((e) => `<p class="muted">! ${esc(e)}</p>`).join("")}
          <table><tr><th>score</th><th>band</th><th>catalogue</th><th>title</th><th>licence</th></tr>${r.results.map((s) => `<tr><td class="score band-${s.band.toLowerCase().replace(/ /g, "_").replace("_confidence", "").replace("_match", "")}">${s.score}</td><td>${esc(s.band)}</td><td>${esc(s.provider)}</td><td>${s.url ? `<a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.title)}</a>` : esc(s.title)}<div class="muted">${esc(s.reasons.join("; "))}</div></td><td class="muted">${esc(s.licence || "")}</td></tr>`).join("")}</table>
          ${r.lookups.length ? `<h3>Places to open in a browser</h3><ul>${r.lookups.map((l) => `<li>${esc(l.provider)}: <a href="${esc(l.url)}" target="_blank" rel="noopener">${esc(l.url)}</a></li>`).join("")}</ul>` : ""}
          <div class="card row"><label>Minimum relevance to download and store <input type="number" id="cat-min" value="${cfg.review_at}" min="0" max="100" size="4"></label><button id="cat-collect">Download and store</button><span class="muted">≥ ${cfg.confirmed_at} confirmed; ${cfg.review_at}–${cfg.confirmed_at - 1} go to the review queue</span></div>
          <pre id="cat-collect-log" class="log hidden"></pre><div id="cat-collect-result"></div>`;
        $("#cat-collect").addEventListener("click", async () => {
          const log2 = $("#cat-collect-log"); log2.classList.remove("hidden");
          try {
            const j2 = await runJob("catalogue_collect", { search_job: state.lastCatalogueJob, min_score: Number($("#cat-min").value) }, log2);
            const out = $("#cat-collect-result");
            out.innerHTML = summaryHtml(j2.result.session) + (j2.result.proposals ? `<p>${j2.result.proposals} language fact(s) proposed for review.</p>` : "") + outcomesHtml(j2.result.outcomes);
            wireResourceRows(out);
          } catch (e) { fail(e); }
        });
      } catch (e) { fail(e); }
    });
  }

  // ------------------------------------------------------------------ agent search (§6)
  async function renderAgent() {
    const el = $("#view-agent");
    el.innerHTML = `<h1>Online Collection — Agent Search</h1><p class="muted">Planning queries from the language profile …</p>`;
    const [plan, prov, eng] = await Promise.all([get(`/api/languages/${encodeURIComponent(state.lang)}/agent/plan`), get("/api/agent/provider"), get("/api/agent/engines")]);
    const lim = plan.limits;
    el.innerHTML = `<h1>Online Collection — Agent Search</h1>
      <div class="card"><p class="row">Agent provider:
        <select id="agent-provider">${prov.choices.map((c) => `<option value="${esc(c.name)}" ${c.current ? "selected" : ""} ${c.installed ? "" : "disabled"}>${esc(c.name)} — ${esc(c.what)}${c.installed ? "" : " (not installed)"}</option>`).join("")}</select>
        ${plan.agent.available ? "" : `<span class="tag uncertain">not available (${esc(plan.agent.why)}); the rule-based agent is used</span>`}
        <span class="muted">· Web search backends: ${plan.backends.map(esc).join(", ") || "<em>none configured</em>"}</span></p>
      <p class="muted">A model provider receives the language profile and the text of visited pages. The choice is saved to config.toml.</p>
      <p class="muted">Search engines: ${eng.engines.filter((e) => e.enabled && e.available).map((e) => esc(e.name)).join(", ") || "<b>none usable</b>"} · <a href="#" id="agent-to-settings">change in Settings</a></p>
      <details class="hidden"><summary>Search engines</summary>
        <div class="checks" id="engine-checks">${eng.engines.map((e) => `<label title="${esc(e.what)}${e.region ? " — " + esc(e.region) : ""}"><input type="checkbox" value="${esc(e.name)}" ${e.enabled ? "checked" : ""}> ${esc(e.name)} <span class="tag">${esc(e.kind)}</span>${e.available ? "" : ` <span class="tag uncertain" title="${esc(e.why)}">needs key</span>`}${e.verified ? "" : ` <span class="tag">unverified</span>`} <button class="small ghost" data-test="${esc(e.name)}">test</button>${e.source !== "builtin" ? ` <button class="small danger" data-rm="${esc(e.name)}">remove</button>` : ""}</label>`).join("")}</div>
        <div class="row"><button id="engines-save" class="small">Save selection</button><span class="muted">Engines are asked in the order shown. Add your own (SearXNG, Baidu via SerpAPI, a keyed API …) with <code>aimixe collect search add</code>, or below.</span></div>
        <pre id="engine-test" class="log hidden"></pre>
        <form id="engine-add" class="row"><input name="name" placeholder="name" required><select name="kind"><option value="json">json API</option><option value="rss">rss / atom</option><option value="html">html page</option></select><input name="url" placeholder="URL template with {q} ({key} {cx} {lang})" size="48" required><input name="items" placeholder="json: result list path (results)"><input name="fields" placeholder="json: url=url, title=title, snippet=content" size="40"><input name="link_pattern" placeholder="html: regex, group 1 = URL"><input name="what" placeholder="description" size="30"><label><input type="checkbox" name="needs_key"> needs key</label><button class="small">Add engine</button></form>
      </details>
      <p class="muted">Limits: ${lim.max_pages} pages, depth ${lim.max_depth}, ${lim.per_host} per host, ${lim.max_files} files, ${lim.max_rounds} rounds. Names and varieties discovered during the run feed later rounds and are proposed for review, never written to the profile.</p>
      <h3>Queries</h3>
      <table id="agent-queries"><tr><th></th><th>basis</th><th>query</th><th>why</th></tr>${plan.queries.map((q, i) => `<tr><td><input type="checkbox" checked data-i="${i}"></td><td>${esc(q.basis)}</td><td>${esc(q.text)}</td><td class="muted">${esc(q.rationale || "")}</td></tr>`).join("")}</table>
      <div class="row"><input id="agent-extra" placeholder="your own queries, separated by ;" size="60"><button id="agent-run" ${plan.backends.length ? "" : "disabled"}>Run</button></div></div>
      <pre id="agent-log" class="log hidden"></pre><div id="agent-result"></div>`;
    $("#agent-to-settings").addEventListener("click", (e) => { e.preventDefault(); show("settings"); });
    $("#engines-save").addEventListener("click", async () => {
      const names = $$("#engine-checks input[type=checkbox]:checked", el).map((i) => i.value);
      try { await post("/api/agent/engines", { enabled: names }); toast("Search engines: " + names.join(", ")); renderAgent(); } catch (err) { fail(err); }
    });
    $$("button[data-test]", el).forEach((b) => b.addEventListener("click", async (ev) => {
      ev.preventDefault(); const pre = $("#engine-test"); pre.classList.remove("hidden"); pre.textContent = `testing ${b.dataset.test} …`;
      try { const r = await get(`/api/agent/engines/${encodeURIComponent(b.dataset.test)}/test?q=${encodeURIComponent((state.profileData && state.profileData.profile.name) || "language")}%20language`); pre.textContent = r.hits.length ? r.hits.map((h) => `${h.title || "(no title)"}\n    ${h.url}`).join("\n") : "no hits"; } catch (err) { pre.textContent = err.message; }
    }));
    $$("button[data-rm]", el).forEach((b) => b.addEventListener("click", async (ev) => {
      ev.preventDefault(); try { const r = await del(`/api/agent/engines/${encodeURIComponent(b.dataset.rm)}`); toast(r.message); renderAgent(); } catch (err) { fail(err); }
    }));
    $("#engine-add").addEventListener("submit", async (ev) => {
      ev.preventDefault(); const fd = new FormData(ev.target); const cfg = {}; fd.forEach((v, k) => { if (String(v).trim()) cfg[k] = String(v).trim(); });
      if (cfg.needs_key) cfg.needs_key = true;
      if (cfg.fields) { const f = {}; cfg.fields.split(",").forEach((p) => { const [k, v] = p.split("=").map((s) => s.trim()); if (k && v) f[k] = v; }); cfg.fields = f; }
      try { await post("/api/agent/engines", { engine: cfg }); toast("Engine saved"); renderAgent(); } catch (err) { fail(err); }
    });
    $("#agent-provider").addEventListener("change", async (e) => {
      try { await post("/api/agent/provider", { provider: e.target.value }); toast(`Agent provider: ${e.target.value}`); renderAgent(); } catch (err) { fail(err); }
    });
    $("#agent-run").addEventListener("click", async () => {
      const queries = plan.queries.filter((q, i) => $(`input[data-i="${i}"]`, el).checked).map((q) => ({ text: q.text, basis: q.basis, rationale: q.rationale }));
      $("#agent-extra").value.split(";").map((s) => s.trim()).filter(Boolean).forEach((t) => queries.push({ text: t, basis: "user" }));
      const log = $("#agent-log"); log.classList.remove("hidden");
      try {
        const j = await runJob("agent_search", { queries }, log);
        const r = j.result, out = $("#agent-result");
        out.innerHTML = summaryHtml(r.session) + `<p>Hits ${r.hits} · pages fetched ${r.pages_fetched} · relevant ${r.pages_relevant} · files found ${r.files_found}${r.learned.length ? ` · learned: ${esc(r.learned.join(", "))}` : ""}${r.proposals_queued ? ` · ${r.proposals_queued} fact(s) proposed for review` : ""}</p>` + r.errors.map((e) => `<p class="muted">! ${esc(e)}</p>`).join("") + outcomesHtml(r.outcomes);
        wireResourceRows(out);
      } catch (e) { fail(e); }
    });
  }

  // ------------------------------------------------------------------ offline (§8) and import (§9)
  async function renderOffline() {
    const el = $("#view-offline"), terms = state.profileData ? state.profileData.offline_terms : [];
    el.innerHTML = `<h1>Offline Collection</h1><div class="card">
      <p class="muted">Scans local folders for the profile's terms (${terms.length}): ${esc(terms.slice(0, 12).join(", "))}${terms.length > 12 ? ", …" : ""}</p>
      <label>Folders to scan (one per line)<textarea id="off-roots" placeholder="/home/you/Documents"></textarea></label>
      <div class="row"><label>Storage mode <select id="off-mode">${["copy", "move", "reference"].map((m) => `<option ${m === state.status.config.storage_mode ? "selected" : ""}>${m}</option>`).join("")}</select></label>
      <label><input type="checkbox" id="off-content" checked> also look inside text and document files</label><button id="off-run">Scan</button></div></div>
      <pre id="off-log" class="log hidden"></pre><div id="off-result"></div>`;
    $("#off-run").addEventListener("click", async () => {
      const roots = $("#off-roots").value.split("\n").map((s) => s.trim()).filter(Boolean);
      if (!roots.length) return toast("Enter at least one folder", true);
      const log = $("#off-log"); log.classList.remove("hidden");
      try {
        const j = await runJob("offline", { roots, mode: $("#off-mode").value, content: $("#off-content").checked }, log);
        const out = $("#off-result");
        out.innerHTML = summaryHtml(j.result.session) + (j.result.scan ? `<p class="muted">Files seen ${j.result.scan.files_seen} · matches ${j.result.scan.hits} · folders skipped ${j.result.scan.dirs_skipped}</p>` : "") + outcomesHtml(j.result.outcomes);
        wireResourceRows(out);
      } catch (e) { fail(e); }
    });
  }
  async function renderImport() {
    const el = $("#view-import");
    el.innerHTML = `<h1>Import Files / Folder</h1><div class="card row">
      <input id="imp-path" placeholder="/path/to/folder or dictionary.pdf" size="50">
      <label>Storage mode <select id="imp-mode">${["copy", "move", "reference"].map((m) => `<option ${m === state.status.config.storage_mode ? "selected" : ""}>${m}</option>`).join("")}</select></label>
      <button id="imp-run">Import</button></div>
      <p class="muted">Every file is hashed (SHA-256), duplicate-checked, typed, classified and stored with its original location recorded. The original is never modified.</p>
      <pre id="imp-log" class="log hidden"></pre><div id="imp-result"></div>`;
    $("#imp-run").addEventListener("click", async () => {
      const path = $("#imp-path").value.trim();
      if (!path) return toast("Enter a path", true);
      const log = $("#imp-log"); log.classList.remove("hidden");
      try {
        const j = await runJob("import", { path, mode: $("#imp-mode").value }, log);
        const out = $("#imp-result"); out.innerHTML = summaryHtml(j.result.session) + outcomesHtml(j.result.outcomes); wireResourceRows(out);
      } catch (e) { fail(e); }
    });
  }

  // ------------------------------------------------------------------ collection (§3 item 4)
  async function renderCollection() {
    const el = $("#view-collection");
    const { resources } = await get(`/api/languages/${encodeURIComponent(state.lang)}/resources`);
    el.innerHTML = `<h1>Existing Collection <span class="muted">${resources.length} resource(s)</span></h1>
      ${resources.length ? `<table><tr><th>#</th><th>name</th><th>format</th><th>category</th><th>resource type</th><th>relevance</th><th>sources</th></tr>
      ${resources.map((r) => `<tr class="clickable" data-rid="${r.id}"><td>${r.id}</td><td>${esc(r.original_name)}</td><td>${esc(r.format)}</td><td>${esc(r.category)}</td><td>${esc(r.types || "—")}</td><td><span class="score band-${r.band}">${r.relevance_score}</span> ${esc(r.status)}</td><td>${r.source_count}</td></tr>`).join("")}</table>` : "<p class='muted'>Nothing collected yet.</p>"}
      <div id="resource-detail"></div>`;
    wireResourceRows(el);
  }
  async function showResource(rid) {
    const d = await get(`/api/resources/${rid}`);
    let box = $("#resource-detail");
    if (!box || box.closest(".hidden")) { show("collection"); await new Promise((r) => setTimeout(r, 50)); box = $("#resource-detail"); }
    const r = d.resource;
    box.innerHTML = `<div class="card"><h2>#${r.id} ${esc(r.original_name)}</h2>
      <dl class="kv"><dt>Stored at</dt><dd class="mono">${esc(r.stored_path)}</dd><dt>SHA-256</dt><dd class="mono">${esc(r.sha256)}</dd><dt>Format</dt><dd>${esc(r.format)} · ${esc(r.category)} · ${r.size} bytes · ${esc(r.storage_mode)}</dd>
      <dt>Resource types</dt><dd>${d.types.map((t) => `${esc(t.type)} <span class="tag">${Number(t.confidence).toFixed(2)} ${esc(t.source)}</span>`).join(" ") || "—"}</dd>
      <dt>Relevance</dt><dd>${d.languages.map((l) => `${esc(l.language_id)}: <span class="score">${l.relevance_score}</span> ${esc(l.status)} — ${esc(JSON.parse(l.reasons_json || "[]").join("; "))}`).join("<br>")}</dd></dl>
      <h3>Provenance (${d.sources.length} source record(s))</h3>
      ${d.sources.map((s) => `<div class="prov">${Object.entries(s).filter(([k, v]) => v !== null && v !== "" && !["id", "resource_id"].includes(k)).map(([k, v]) => `<b>${esc(k)}</b>=${esc(v)}`).join(" · ")}</div>`).join("")}
      ${d.extractions.length ? `<h3>Extracted (derived, originals untouched)</h3>${d.extractions.map((e) => `<div class="prov">${esc(e.kind)}: <span class="mono">${esc(e.path)}</span></div>`).join("")}` : ""}
      ${d.near_duplicates.length ? `<h3>Near-duplicates</h3>${d.near_duplicates.map((n) => `<div class="prov">#${n.other_id} ${esc(n.original_name)} (${Math.round(n.similarity * 100)}%, ${esc(n.method)})</div>`).join("")}` : ""}
      <details><summary>Metadata (${d.metadata.length})</summary>${d.metadata.map((m) => `<div class="prov"><b>${esc(m.key)}</b> = ${esc(String(m.value).slice(0, 300))} <span class="tag">${esc(m.extracted_by)}</span></div>`).join("")}</details></div>`;
    box.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  // ------------------------------------------------------------------ review (§18)
  async function renderReview() {
    const el = $("#view-review");
    const filter = state.reviewLang !== undefined ? state.reviewLang : state.lang;
    const [{ items }, summary] = await Promise.all([get(filter ? `/api/review?language=${encodeURIComponent(filter)}` : "/api/review"), get("/api/review/summary")]);
    const total = summary.languages.reduce((n, l) => n + l.total, 0);
    el.innerHTML = `<h1>Review Queue <span class="muted">${items.length} item(s)</span></h1>
      <p class="row"><label>Language <select id="review-filter"><option value="">all languages (${total})</option>${summary.languages.map((l) => `<option value="${esc(l.language_id)}" ${filter === l.language_id ? "selected" : ""}>${esc(l.name)} [${esc(l.iso639_3 || l.language_id)}] — ${l.total} waiting${l.resources ? `, ${l.resources} resource(s)` : ""}${l.facts ? `, ${l.facts} fact(s)` : ""}</option>`).join("")}</select></label></p>
      <p class="muted">Uncertain resources and language facts proposed by catalogues or the agent. Nothing reaches the canonical profile without an accept here.</p>
      ${items.length ? items.map((it) => `<div class="card review-card" data-id="${it.id}">
        ${state.lang ? "" : `<div class="muted">${esc(it.language_id)}</div>`}
        ${it.kind === "profile_field" ? `<h3>Possible new language information detected</h3><dl class="kv"><dt>Field</dt><dd>${esc(it.payload.field)}</dd><dt>Value</dt><dd>${esc(fmt(it.payload.value))}</dd>${it.payload.quote ? `<dt>Quote</dt><dd class="quote">${esc(it.payload.quote)}</dd>` : ""}</dl>`
          : `<h3>Uncertain resource</h3><dl class="kv"><dt>Resource</dt><dd>${esc(it.payload.name)}</dd><dt>Relevance</dt><dd>${it.payload.relevance} (${esc(it.payload.band)}) — ${esc((it.payload.reasons || []).join("; "))}</dd></dl>`}
        <p class="muted">Confidence: ${Math.round((it.confidence || 0) * 100)}% · Source: ${/^https?:/.test(it.source_ref || "") ? `<a href="${esc(it.source_ref)}" target="_blank" rel="noopener">${esc(it.source_ref)}</a>` : esc(it.source_ref || "—")}</p>
        <div class="actions"><button data-act="accept">Accept</button><button data-act="reject" class="danger">Reject</button><button data-act="view" class="ghost">View source</button><button data-act="skip" class="ghost">Skip</button></div><pre class="log hidden"></pre></div>`).join("") : "<p>Nothing to review.</p>"}`;
    $("#review-filter").addEventListener("change", (e) => { state.reviewLang = e.target.value || null; renderReview(); });
    $$(".review-card", el).forEach((card) => $$("button", card).forEach((b) => b.addEventListener("click", async () => {
      const id = card.dataset.id, act = b.dataset.act;
      try {
        if (act === "view") { const t = await get(`/api/review/${id}/source`); const pre = $("pre", card); pre.textContent = t.text; pre.classList.remove("hidden"); return; }
        await post(`/api/review/${id}/${act}`); toast(act === "accept" ? "Accepted" : act === "reject" ? "Rejected" : "Skipped"); renderReview(); refreshStatus();
      } catch (e) { fail(e); }
    })));
  }

  // ------------------------------------------------------------------ history (§17)
  async function renderHistory() {
    const el = $("#view-history");
    const { sessions } = await get(state.lang ? `/api/history?language=${encodeURIComponent(state.lang)}` : "/api/history");
    el.innerHTML = `<h1>Collection History${state.lang ? "" : ' <span class="muted">· all languages</span>'}</h1>${sessions.length ? `<table><tr><th>session</th><th>language</th><th>mode</th><th>status</th><th>started</th><th>disc</th><th>rel</th><th>down</th><th>dup</th><th>fail</th><th>review</th></tr>
      ${sessions.map((s) => `<tr class="clickable" data-sid="${esc(s.id)}"><td class="mono">${esc(s.id)}</td><td>${esc(s.language_name)} [${esc(s.language_id)}]</td><td>${esc(s.mode)}</td><td>${esc(s.status)}</td><td>${esc(s.started_at.slice(0, 19))}</td><td>${s.discovered}</td><td>${s.relevant}</td><td>${s.downloaded}</td><td>${s.duplicates}</td><td>${s.failed}</td><td>${s.pending_review}</td></tr>`).join("")}</table>` : "<p class='muted'>No collection sessions yet.</p>"}<div id="session-detail"></div>`;
    $$("tr[data-sid]", el).forEach((r) => r.addEventListener("click", async () => {
      const d = await get(`/api/sessions/${encodeURIComponent(r.dataset.sid)}`);
      $("#session-detail").innerHTML = `<div class="card">${summaryHtml(d.session)}<pre class="log">${d.events.map((e) => `${esc(e.ts)}  ${esc(e.level.padEnd(5))}  ${esc(e.message)}`).join("\n")}</pre></div>`;
    }));
  }

  // ------------------------------------------------------------------ catalogues management
  async function renderCatalogues() {
    const el = $("#view-catalogues");
    const d = await get("/api/catalogues");
    el.innerHTML = `<h1>Catalogues</h1>
      <table><tr><th>name</th><th>kind</th><th>enabled</th><th>source</th><th>what</th><th></th></tr>${d.catalogues.map((c) => `<tr><td>${esc(c.name)}</td><td>${esc(c.kind)}${c.mode !== "python" && c.mode !== c.kind ? ` <span class="tag">${esc(c.mode)}</span>` : ""}</td><td>${c.enabled ? "yes" : "no"}</td><td class="mono">${esc(c.source === "builtin" ? "built-in" : c.source)}</td><td>${esc(c.what)}${c.licence_note ? `<div class="muted">${esc(c.licence_note)}</div>` : ""}</td><td>${c.enabled ? `<button class="small danger" data-rm="${esc(c.name)}">${c.source === "builtin" ? "disable" : "remove"}</button>` : ""}</td></tr>`).join("")}</table>
      ${d.errors.map((e) => `<p class="muted">! ${esc(e)}</p>`).join("")}
      <div class="card"><h2>Add a catalogue</h2>
      <form id="cat-add" class="row">
        <input name="name" placeholder="name (e.g. my_university_repo)" required>
        <select name="kind"><option value="lookup">lookup — a URL to open; nothing fetched</option><option value="api_json">api_json — JSON search API</option><option value="html_links">html_links — links on a web page</option></select>
        <input name="url" placeholder="URL template with {q} {name} {code}" size="50" required>
        <select name="asks_by"><option value="name">search by name</option><option value="code">search by ISO code</option><option value="both">both</option></select>
        <input name="what" placeholder="short description" size="40">
        <input name="licence_note" placeholder="licence note" size="30">
        <input name="items" placeholder="api_json: path to results (hits.hits)">
        <input name="fields" placeholder='api_json field paths, e.g. title=metadata.title, url=links.html, download=files[].links.self' size="70">
        <input name="link_pattern" placeholder="html_links: regex a link must match">
        <button>Add</button></form>
      <p class="muted">Saved to ~/.aimixe/catalogues/&lt;name&gt;.toml. Templates: {q} the search term, {name} the profile name, {code} the ISO 639-3 code.</p></div>`;
    $$("button[data-rm]", el).forEach((b) => b.addEventListener("click", async () => { try { const r = await del(`/api/catalogues/${encodeURIComponent(b.dataset.rm)}`); toast(r.message); await refreshStatus(); renderCatalogues(); } catch (e) { fail(e); } }));
    $("#cat-add").addEventListener("submit", async (e) => {
      e.preventDefault();
      const fd = new FormData(e.target); const cfg = {}; fd.forEach((v, k) => { if (v.trim()) cfg[k] = v.trim(); });
      if (cfg.fields) { const f = {}; cfg.fields.split(",").forEach((pair) => { const [k, v] = pair.split("=").map((s) => s.trim()); if (k && v) f[k] = v; }); cfg.fields = f; }
      try { await post("/api/catalogues", cfg); toast("Catalogue saved"); await refreshStatus(); renderCatalogues(); } catch (err) { fail(err); }
    });
  }

  // ------------------------------------------------------------------ boot
  refreshStatus().then(() => show("home")).catch(fail);
})();
