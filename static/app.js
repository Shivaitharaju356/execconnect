/* ExecConnect front end - plain JavaScript single-page app. */
const COUNTRIES = ["Germany", "Estonia", "Netherlands", "United Kingdom", "France", "Austria", "Switzerland", "Sweden",
  "Poland", "Spain", "Italy", "United States", "India", "Singapore", "United Arab Emirates"];
const S = { meta: null, user: null, signup: { step: 1, data: { intents: [] } }, conns: [], active: null, poll: null, lastMsg: 0 };
const app = document.getElementById("app");

// ---------------------------------------------------------------- utilities
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const opts = (list, sel, blank) => (blank !== undefined ? `<option value="">${esc(blank)}</option>` : "") +
  list.map((v) => `<option ${v === sel ? "selected" : ""}>${esc(v)}</option>`).join("");

async function api(method, path, data) {
  const res = await fetch(path, {
    method, credentials: "same-origin",
    headers: data !== undefined ? { "Content-Type": "application/json" } : {},
    body: data !== undefined ? JSON.stringify(data) : undefined,
  });
  let json = {};
  try { json = await res.json(); } catch (_) { /* empty */ }
  if (!res.ok) { const e = new Error(json.error || `Request failed (${res.status})`); e.status = res.status; throw e; }
  return json;
}

function toast(msg, isError) {
  const t = $("#toast");
  t.textContent = msg; t.className = "toast" + (isError ? " error" : ""); t.hidden = false;
  clearTimeout(t._h); t._h = setTimeout(() => (t.hidden = true), 3500);
}
function modal(html) { $("#modal-card").innerHTML = html; $("#modal").hidden = false; }
function closeModal() { $("#modal").hidden = true; }
$("#modal").addEventListener("click", (e) => { if (e.target.id === "modal") closeModal(); });

function stopPolling() { clearInterval(S.poll); S.poll = null; }

// ---------------------------------------------------------------- routing
async function refreshMe() { S.user = (await api("GET", "/api/me")).user; return S.user; }

async function route() {
  stopPolling();
  if (!S.meta) S.meta = await api("GET", "/api/meta");
  await refreshMe();
  const u = S.user;
  const view = location.hash.replace("#", "") || "discover";
  $("#topbar").hidden = !u || !u.email_verified || u.status !== "active";
  if (!u) return view === "signup" ? renderSignup() : renderLogin();
  if (!u.email_verified) return renderVerifyEmail();
  if (u.status !== "active") return renderReview();
  if (view === "mfa-setup") return renderMfaSetup(true);
  $("#me-alias").textContent = u.alias + (u.is_premium ? " · Premium" : "");
  $("#nav-admin").hidden = !u.is_admin;
  $$("#nav a").forEach((a) => a.classList.toggle("active", a.dataset.view === view));
  updateBadge();
  if (view === "connections") return renderConnections();
  if (view === "profile") return renderProfile();
  if (view === "admin" && u.is_admin) return renderAdmin();
  return renderDiscover();
}
window.addEventListener("hashchange", route);
function go(h) { if (location.hash.replace("#", "") === h) route(); else location.hash = h; }
$("#logout").addEventListener("click", async () => { await api("POST", "/api/logout", {}); go("login"); });

async function updateBadge() {
  try {
    const { connections } = await api("GET", "/api/connections");
    const n = connections.filter((c) => c.status === "pending" && c.direction === "incoming").length;
    const b = $("#req-badge"); b.hidden = !n; b.textContent = n;
  } catch (_) { /* ignore */ }
}

// ---------------------------------------------------------------- auth screens
function hero() {
  return `<section class="hero">
    <h1>Meet the right leaders, privately.</h1>
    <p>A verified network for Directors, VPs, C-suite, founders, investors and board members.</p>
    <ul>
      <li><b>Intent-based matching</b> - mentor, advisor, board role, partner, funding - no swiping.</li>
      <li><b>Verified members only</b> - corporate email, company domain and LinkedIn checks, plus bot protection.</li>
      <li><b>Private by default</b> - you appear under an alias; real names are revealed only when both sides agree.</li>
      <li><b>No scammers</b> - MLM, forex and promotional accounts are screened out at sign-up.</li>
    </ul></section>`;
}

function renderLogin() {
  app.innerHTML = `<div class="auth">${hero()}
    <section class="card">
      <div class="tabs"><button>Log in</button><button class="secondary" onclick="location.hash='signup'">Create account</button></div>
      <form id="login-form">
        <div class="field"><label>Work email</label><input name="email" type="email" autocomplete="username" required></div>
        <div class="field"><label>Password</label><input name="password" type="password" autocomplete="current-password" required></div>
        <div class="field" id="mfa-field" hidden><label>Authenticator code</label><input name="code" inputmode="numeric" maxlength="6" placeholder="6-digit code"></div>
        <button style="width:100%">Log in</button>
      </form>
      <p class="small muted" style="margin-top:1rem">Demo: <span class="code">demo@novapay.example.com</span> / <span class="code">Demo12345!</span><br>
      Admin: <span class="code">admin@execconnect.example.com</span> / <span class="code">Demo12345!</span></p>
    </section></div>`;
  let mfa = false;
  $("#login-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = Object.fromEntries(new FormData(e.target));
    try {
      if (mfa) { await api("POST", "/api/login/mfa", { code: f.code }); }
      else {
        const r = await api("POST", "/api/login", { email: f.email, password: f.password });
        if (r.mfa_required) { mfa = true; $("#mfa-field").hidden = false; $("[name=code]").focus(); toast("Enter the code from your authenticator app"); return; }
      }
      go("discover");
    } catch (err) { toast(err.message, true); }
  });
}

function renderSignup() {
  const d = S.signup.data, step = S.signup.step;
  const steps = `<div class="steps">${[1, 2, 3].map((i) => `<span class="${i <= step ? "on" : ""}"></span>`).join("")}</div>`;
  let body = "";
  if (step === 1) {
    body = `<h2>Your account</h2><p class="muted small">Your name, email and company stay private. Others see an alias.</p>
      <div class="field"><label>Full name</label><input name="real_name" value="${esc(d.real_name)}" required></div>
      <div class="field"><label>Work email</label><input name="email" type="email" value="${esc(d.email)}" required>
        <div class="hint">Corporate email only - Gmail, Outlook etc. are not accepted.</div></div>
      <div class="field"><label>Password</label><input name="password" type="password" value="${esc(d.password)}" required>
        <div class="hint">10+ characters with an uppercase letter and a number.</div></div>
      <div class="grid2"><div class="field"><label>Company</label><input name="company" value="${esc(d.company)}"></div>
      <div class="field"><label>Company website</label><input name="company_website" placeholder="acme.com" value="${esc(d.company_website)}">
        <div class="hint">Verifies your company when it matches your email domain.</div></div></div>
      <div class="field"><label>LinkedIn profile URL</label><input name="linkedin_url" placeholder="https://www.linkedin.com/in/your-name" value="${esc(d.linkedin_url)}"></div>`;
  } else if (step === 2) {
    body = `<h2>Professional profile</h2>
      <div class="field"><label>Headline</label><input name="headline" placeholder="e.g. CFO at a Series B fintech" value="${esc(d.headline)}" required></div>
      <div class="grid2">
        <div class="field"><label>Seniority</label><select name="seniority" required>${opts(S.meta.seniorities, d.seniority, "Select...")}</select></div>
        <div class="field"><label>Function</label><select name="function">${opts(S.meta.functions, d.function, "Select...")}</select></div>
        <div class="field"><label>Industry</label><select name="industry" required>${opts(S.meta.industries, d.industry, "Select...")}</select></div>
        <div class="field"><label>Country</label><select name="country" required>${opts(COUNTRIES, d.country || "Germany")}</select></div>
      </div>
      <div class="field"><label>City</label><input name="city" value="${esc(d.city || "Berlin")}"></div>
      <div class="field"><label>Areas of interest</label><input name="interests" placeholder="e.g. AI security, fundraising, B2B SaaS" value="${esc(d.interests)}">
        <div class="hint">Comma separated. These drive your AI matches.</div></div>
      <div class="field"><label>About you</label><textarea name="bio">${esc(d.bio)}</textarea></div>
      <div class="field"><label>Investment focus (investors)</label><input name="investment_focus" value="${esc(d.investment_focus)}"></div>
      <div class="row"><label class="check"><input type="checkbox" name="hiring" ${d.hiring ? "checked" : ""}> I'm hiring</label>
        <label class="check"><input type="checkbox" name="board_experience" ${d.board_experience ? "checked" : ""}> I have board experience</label></div>`;
  } else {
    body = `<h2>What are you looking for?</h2><p class="muted small">Pick everything that applies. We match complementary intents.</p>
      <div class="chips" id="intent-chips">${Object.entries(S.meta.intents).map(([k, v]) =>
        `<span class="chip ${d.intents.includes(k) ? "on" : ""}" data-k="${k}">${esc(v)}</span>`).join("")}</div>
      <div class="field" style="margin-top:1.2rem"><label id="challenge-q">Human check</label>
        <input name="challenge_answer" inputmode="numeric" required>
        <div class="hint">Simple check to keep bots out.</div></div>
      <input class="hp" name="website_url_hp" tabindex="-1" autocomplete="off" aria-hidden="true">`;
  }
  app.innerHTML = `<div class="auth">${hero()}<section class="card">
    <div class="tabs"><button class="secondary" onclick="location.hash='login'">Log in</button><button>Create account</button></div>
    ${steps}<form id="su">${body}
    <div class="row" style="justify-content:space-between;margin-top:1rem">
      ${step > 1 ? '<button type="button" class="secondary" id="back">Back</button>' : "<span></span>"}
      <button>${step < 3 ? "Continue" : "Create account"}</button></div></form></section></div>`;

  if (step === 3) {
    api("GET", "/api/challenge").then((c) => { $("#challenge-q").textContent = "Human check: " + c.question; S.signup.token = c.token; });
    $$("#intent-chips .chip").forEach((ch) => ch.addEventListener("click", () => {
      ch.classList.toggle("on");
      const k = ch.dataset.k;
      d.intents = ch.classList.contains("on") ? [...d.intents, k] : d.intents.filter((x) => x !== k);
    }));
  }
  const save = () => {
    const f = new FormData($("#su"));
    for (const [k, v] of f.entries()) d[k] = v;
    if (step === 2) { d.hiring = f.has("hiring"); d.board_experience = f.has("board_experience"); }
  };
  if ($("#back")) $("#back").addEventListener("click", () => { save(); S.signup.step--; renderSignup(); });
  $("#su").addEventListener("submit", async (e) => {
    e.preventDefault(); save();
    if (step < 3) { S.signup.step++; return renderSignup(); }
    if (!d.intents.length) return toast("Pick at least one intent", true);
    try {
      const r = await api("POST", "/api/signup", { ...d, challenge_token: S.signup.token });
      S.signup = { step: 1, data: { intents: [] } };
      S.demoCode = r.demo_email_code;
      toast(r.company_verified ? "Account created - company verified" : "Account created");
      go("verify");
    } catch (err) {
      toast(err.message, true);
      if (err.status === 403) { S.signup = { step: 1, data: { intents: [] } }; setTimeout(() => { go("login"); }, 2500); }
      else renderSignup();
    }
  });
}

function renderVerifyEmail() {
  $("#topbar").hidden = true;
  app.innerHTML = `<div class="card" style="max-width:480px;margin:3rem auto">
    <h2>Verify your work email</h2><p class="muted">We sent a 6-digit code to <b>${esc(S.user.email)}</b>.</p>
    ${S.demoCode ? `<div class="banner info small">Demo mode (no email server): your code is <span class="code">${esc(S.demoCode)}</span>. It is also printed in the server console.</div>` :
      `<div class="banner info small">Demo mode: the code is printed in the server console.</div>`}
    <form id="vf" style="margin-top:1rem"><div class="field"><label>Code</label><input name="code" inputmode="numeric" maxlength="6" required></div>
    <button style="width:100%">Verify</button></form>
    <p class="small" style="margin-top:1rem"><button class="link" id="lo">Use a different account</button></p></div>`;
  $("#vf").addEventListener("submit", async (e) => {
    e.preventDefault();
    try { await api("POST", "/api/verify-email", { code: e.target.code.value }); S.demoCode = null; go("mfa-setup"); }
    catch (err) { toast(err.message, true); }
  });
  $("#lo").addEventListener("click", async () => { await api("POST", "/api/logout", {}); go("login"); });
}

function renderReview() {
  $("#topbar").hidden = true;
  app.innerHTML = `<div class="card" style="max-width:520px;margin:3rem auto">
    <h2>Your profile is being reviewed</h2>
    <p>Thanks for joining. Our trust & safety team reviews some new profiles by hand to keep the network free of
    promotional and unsolicited offers. This usually takes less than a day.</p>
    <button class="secondary" id="lo">Log out</button></div>`;
  $("#lo").addEventListener("click", async () => { await api("POST", "/api/logout", {}); go("login"); });
}

// ---------------------------------------------------------------- MFA
async function renderMfaSetup(onboarding) {
  $("#topbar").hidden = onboarding;
  const r = await api("POST", "/api/mfa/setup", {});
  const html = `<h2>Protect your account with 2-step verification</h2>
    <p class="muted">Scan with Google Authenticator, Microsoft Authenticator or 1Password, then enter the 6-digit code.</p>
    <div class="row" style="align-items:flex-start"><div id="qr"></div>
      <div style="flex:1;min-width:220px"><p class="small">Can't scan? Enter this key manually:</p><p class="code" style="word-break:break-all">${esc(r.secret)}</p></div></div>
    <form id="mf" style="margin-top:1rem"><div class="field"><label>Code from your app</label><input name="code" inputmode="numeric" maxlength="6" required></div>
    <div class="row"><button>Turn on 2-step verification</button>${onboarding ? '<button type="button" class="secondary" id="skip">Skip for now</button>' : ""}</div></form>`;
  if (onboarding) app.innerHTML = `<div class="card" style="max-width:560px;margin:3rem auto">${html}</div>`;
  else modal(html);
  try {
    const qr = qrcode(0, "M"); qr.addData(r.uri); qr.make();
    $("#qr").innerHTML = qr.createSvgTag({ cellSize: 4, margin: 2 });
  } catch (_) { $("#qr").innerHTML = '<p class="small muted">(QR library offline - use the key)</p>'; }
  $("#mf").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await api("POST", "/api/mfa/enable", { code: e.target.code.value });
      toast("2-step verification is on"); closeModal();
      go(onboarding ? "discover" : "profile");
    } catch (err) { toast(err.message, true); }
  });
  if ($("#skip")) $("#skip").addEventListener("click", () => { go("discover"); });
}

// ---------------------------------------------------------------- discover
S.filters = {};
async function renderDiscover() {
  const f = S.filters, u = S.user;
  app.innerHTML = `<div class="layout">
    <aside class="card filters"><h3>Filters</h3><form id="ff">
      <div class="field"><label>Looking for people who are...</label><select name="intent"><option value="">Any intent</option>
        ${Object.entries(S.meta.intents).map(([k, v]) => `<option value="${k}" ${f.intent === k ? "selected" : ""}>${esc(v)}</option>`).join("")}</select></div>
      <div class="field"><label>Industry</label><select name="industry">${opts(S.meta.industries, f.industry, "Any")}</select></div>
      <div class="field"><label>Seniority</label><select name="seniority">${opts(S.meta.seniorities, f.seniority, "Any")}</select></div>
      <div class="field"><label>Function</label><select name="function">${opts(S.meta.functions, f.function, "Any")}</select></div>
      <div class="field"><label>City</label><input name="city" value="${esc(f.city)}" placeholder="Any city"></div>
      <div class="field"><label>Country ${u.is_premium ? "" : '<span class="tag amber">Premium</span>'}</label>
        <select name="country" ${u.is_premium ? "" : "disabled"}>${opts(COUNTRIES, f.country, u.is_premium ? "Any country" : u.country)}</select></div>
      <label class="check"><input type="checkbox" name="hiring" ${f.hiring ? "checked" : ""}> Hiring</label>
      <label class="check"><input type="checkbox" name="board" ${f.board ? "checked" : ""}> Board experience</label>
      <label class="check"><input type="checkbox" name="investment" ${f.investment ? "checked" : ""}> Has investment focus</label>
      <div class="row" style="margin-top:1rem"><button>Apply</button><button type="button" class="secondary" id="clear">Clear</button></div>
    </form></aside>
    <section><div class="row" style="justify-content:space-between;margin-bottom:1rem">
      <div><h2>Recommended for you</h2><p class="muted small" style="margin:0">Ranked by AI on your interests, intents, profile fit and trust.
        ${S.meta.ai_enabled ? "AI explanations on." : "Running in offline mode (TF-IDF matching, rule-based explanations)."}</p></div></div>
      ${u.is_premium ? "" : `<div class="banner info small" style="margin-bottom:1rem">You see members in <b>${esc(u.country)}</b>. <a href="#profile">Upgrade to Premium</a> to match across countries.</div>`}
      <div id="results"><div class="card empty">Finding your best matches...</div></div></section></div>`;
  $("#ff").addEventListener("submit", (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    S.filters = {};
    for (const [k, v] of fd.entries()) if (v) S.filters[k] = v === "on" ? "1" : v;
    renderDiscover();
  });
  $("#clear").addEventListener("click", () => { S.filters = {}; renderDiscover(); });
  try {
    const qs = new URLSearchParams(S.filters).toString();
    const { matches } = await api("GET", "/api/matches?" + qs);
    $("#results").innerHTML = matches.length ? matches.map(matchCard).join("") :
      `<div class="card empty">No matches for these filters yet. Try widening them.</div>`;
    $$("[data-connect]").forEach((b) => b.addEventListener("click", () => connectModal(matches.find((m) => m.id == b.dataset.connect))));
  } catch (err) { $("#results").innerHTML = `<div class="card empty">${esc(err.message)}</div>`; }
}

function matchCard(m) {
  const intents = m.intents.map((i) => `<span class="tag">${esc(S.meta.intents[i] || i)}</span>`).join("");
  const v = m.verified;
  const badges = [v.email && "Email", v.company && "Company", v.linkedin === "verified" && "LinkedIn"].filter(Boolean)
    .map((x) => `<span class="tag green">✓ ${x}</span>`).join("");
  const bar = (k, label) => `<div class="bar">${label} ${m.breakdown[k]}<i><b style="width:${m.breakdown[k]}%"></b></i></div>`;
  return `<article class="card match"><div>
      <h3>${esc(m.alias)} <span class="muted small">${esc(m.seniority)} · ${esc(m.function)}</span></h3>
      <p style="margin-bottom:.3rem"><b>${esc(m.headline)}</b></p>
      <p class="small muted" style="margin-bottom:.4rem">${esc(m.industry)} · ${esc(m.city)}, ${esc(m.country)}
        ${m.hiring ? " · Hiring" : ""}${m.board_experience ? " · Board experience" : ""}${m.rating ? ` · ★ ${m.rating}` : ""}</p>
      <div>${badges}</div>
      <div class="reason">${m.reason_source === "ai" ? "✨ " : ""}${esc(m.reason)}</div>
      <div><span class="small muted">Looking for: </span>${intents}</div>
      ${m.investment_focus ? `<p class="small muted" style="margin-top:.3rem">Investment focus: ${esc(m.investment_focus)}</p>` : ""}
    </div>
    <div class="score"><div class="big">${Math.round(m.score)}</div><div class="small muted">match score</div>
      <div class="bars">${bar("intent", "Intent")}${bar("semantic", "Interests")}${bar("fit", "Profile fit")}${bar("trust", "Trust")}</div>
      <button style="width:100%;margin-top:.5rem" data-connect="${m.id}">Connect</button></div></article>`;
}

function connectModal(m) {
  modal(`<h2>Connect with ${esc(m.alias)}</h2><p class="muted small">${esc(m.headline)}</p>
    <div class="reason">${esc(m.reason)}</div>
    <form id="cf"><div class="field"><label>Personal note</label>
      <textarea name="note" maxlength="500" placeholder="Say why you'd like to connect...">Hi! ${esc(m.reason)} Would be great to connect.</textarea>
      <div class="hint">Your real name and email are not shared. Promotional notes are blocked.</div></div>
    <div class="row"><button>Send request</button><button type="button" class="secondary" onclick="closeModal()">Cancel</button></div></form>`);
  $("#cf").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await api("POST", "/api/connections", { user_id: m.id, note: e.target.note.value, score: m.score, reason: m.reason });
      closeModal(); toast("Request sent"); renderDiscover();
    } catch (err) { toast(err.message, true); }
  });
}

// ---------------------------------------------------------------- connections & chat
async function renderConnections() {
  const { connections } = await api("GET", "/api/connections");
  S.conns = connections;
  const incoming = connections.filter((c) => c.status === "pending" && c.direction === "incoming");
  const outgoing = connections.filter((c) => c.status === "pending" && c.direction === "outgoing");
  const accepted = connections.filter((c) => c.status === "accepted");
  const item = (c) => `<div class="conn-item ${S.active === c.id ? "active" : ""}" data-id="${c.id}">
      <b>${esc(c.other.real_name || c.other.alias)}</b> <span class="small muted">${esc(c.other.seniority)}</span>
      <div class="small muted">${esc(c.last_message ? c.last_message.body.slice(0, 60) : c.other.headline)}</div></div>`;
  app.innerHTML = `
    ${incoming.length ? `<div class="card stack" style="margin-bottom:1.25rem"><h3>Requests for you</h3>
      ${incoming.map((c) => `<div class="row" style="justify-content:space-between;border-top:1px solid var(--line);padding-top:.75rem">
        <div style="flex:1;min-width:240px"><b>${esc(c.other.alias)}</b> · ${esc(c.other.headline)}
          <div class="small muted">${esc(c.other.industry)} · ${esc(c.other.city)}</div>
          ${c.note ? `<div class="reason">“${esc(c.note)}”</div>` : ""}</div>
        <div class="row"><button data-accept="${c.id}">Accept</button><button class="secondary" data-decline="${c.id}">Decline</button></div></div>`).join("")}
      </div>` : ""}
    <div class="conn-layout">
      <aside class="card"><h3>Connections</h3>
        ${accepted.length ? accepted.map(item).join("") : '<p class="muted small">No connections yet. Find people on Discover.</p>'}
        ${outgoing.length ? `<h3 style="margin-top:1rem">Sent requests</h3>${outgoing.map((c) =>
          `<div class="conn-item" style="cursor:default"><b>${esc(c.other.alias)}</b><div class="small muted">Waiting for reply</div></div>`).join("")}` : ""}
      </aside>
      <section class="card" id="chat-pane"><div class="empty">Select a connection to chat or start a call.</div></section>
    </div>`;
  $$("[data-accept]").forEach((b) => b.addEventListener("click", () => respond(b.dataset.accept, true)));
  $$("[data-decline]").forEach((b) => b.addEventListener("click", () => respond(b.dataset.decline, false)));
  $$(".conn-item[data-id]").forEach((el) => el.addEventListener("click", () => { S.active = +el.dataset.id; openChat(); }));
  if (S.active && accepted.find((c) => c.id === S.active)) openChat();
  else if (accepted.length) { S.active = accepted[0].id; openChat(); }
  updateBadge();
}

async function respond(id, accept) {
  try {
    await api("POST", `/api/connections/${id}/respond`, { accept });
    toast(accept ? "Connected - say hello!" : "Request declined");
    if (accept) S.active = +id;
    renderConnections();
  } catch (err) { toast(err.message, true); }
}

async function openChat() {
  stopPolling();
  $$(".conn-item[data-id]").forEach((el) => el.classList.toggle("active", +el.dataset.id === S.active));
  const c = S.conns.find((x) => x.id === S.active);
  if (!c) return;
  const o = c.other;
  $("#chat-pane").innerHTML = `<div class="chat">
    <div class="chat-head"><div><h3 style="margin:0">${esc(o.real_name || o.alias)}</h3>
      <div class="small muted">${esc(o.headline)}${c.revealed && o.company ? " · " + esc(o.company) : ""}
      ${c.revealed && o.linkedin_url ? ` · <a href="${esc(o.linkedin_url)}" target="_blank" rel="noopener">LinkedIn</a>` : ""}</div></div>
      <div class="row">
        <button class="secondary" id="call">📹 Video call</button>
        ${c.revealed ? '<span class="tag green">Identities revealed</span>' :
          c.i_revealed ? '<span class="tag amber">Waiting for them to reveal</span>' : '<button class="secondary" id="reveal">Reveal my identity</button>'}
        <button class="secondary" id="rate">${c.rated ? "Update rating" : "Rate"}</button>
      </div></div>
    <div class="msgs" id="msgs"></div>
    <form class="composer" id="composer"><input name="body" placeholder="Write a message..." autocomplete="off"><button>Send</button></form></div>`;
  S.lastMsg = 0;
  await loadMessages(true);
  S.poll = setInterval(loadMessages, 3000);
  $("#composer").addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = e.target.body.value.trim();
    if (!text) return;
    try {
      const r = await api("POST", `/api/connections/${c.id}/messages`, { body: text });
      e.target.body.value = "";
      if (r.flagged) toast("Your message was flagged as promotional and logged for review.", true);
      loadMessages();
    } catch (err) { toast(err.message, true); }
  });
  $("#call").addEventListener("click", async () => {
    const { url } = await api("POST", `/api/connections/${c.id}/call`, {});
    await api("POST", `/api/connections/${c.id}/messages`, { body: "📹 Started a video call: " + url });
    window.open(url, "_blank", "noopener");
    loadMessages();
  });
  if ($("#reveal")) $("#reveal").addEventListener("click", async () => {
    if (!confirm("Share your real name, company and LinkedIn with this person once they also agree?")) return;
    await api("POST", `/api/connections/${c.id}/reveal`, {});
    toast("Done - your identity is shared once they agree too.");
    renderConnections();
  });
  $("#rate").addEventListener("click", () => rateModal(o));
}

async function loadMessages(first) {
  if (!S.active) return;
  try {
    const { messages } = await api("GET", `/api/connections/${S.active}/messages?after=${S.lastMsg}`);
    const box = $("#msgs");
    if (!box) return stopPolling();
    if (first && !messages.length) box.innerHTML = '<div class="empty small">No messages yet - break the ice.</div>';
    if (messages.length && box.querySelector(".empty")) box.innerHTML = "";
    for (const m of messages) {
      const linked = esc(m.body).replace(/(https:\/\/meet\.jit\.si\/[A-Za-z0-9-]+)/g, '<a href="$1" target="_blank" rel="noopener" style="color:inherit">$1</a>');
      box.insertAdjacentHTML("beforeend", `<div class="msg ${m.mine ? "mine" : ""} ${m.flagged ? "flagged" : ""}">${linked}
        <time>${esc(m.created_at.slice(11, 16))}${m.flagged ? " · flagged" : ""}</time></div>`);
      S.lastMsg = m.id;
    }
    if (messages.length) box.scrollTop = box.scrollHeight;
  } catch (_) { stopPolling(); }
}

function rateModal(o) {
  const dims = [["responsiveness", "Responsiveness"], ["intro_quality", "Quality of introductions"],
    ["mentoring", "Mentoring contribution"], ["events", "Event participation"]];
  const vals = {};
  modal(`<h2>Rate ${esc(o.real_name || o.alias)}</h2><p class="muted small">Ratings are private and feed into trust scores.</p>
    ${dims.map(([k, l]) => `<div class="field"><label>${l}</label><div class="stars" data-k="${k}">
      ${[1, 2, 3, 4, 5].map((n) => `<button type="button" data-n="${n}">★</button>`).join("")}</div></div>`).join("")}
    <div class="row"><button id="save-rating">Save</button><button class="secondary" onclick="closeModal()">Cancel</button></div>`);
  $$(".stars").forEach((s) => s.addEventListener("click", (e) => {
    const n = +e.target.dataset.n; if (!n) return;
    vals[s.dataset.k] = n;
    $$("button", s).forEach((b) => b.classList.toggle("on", +b.dataset.n <= n));
  }));
  $("#save-rating").addEventListener("click", async () => {
    if (Object.keys(vals).length < 4) return toast("Please rate all four areas", true);
    try { await api("POST", "/api/ratings", { user_id: o.id, ...vals }); closeModal(); toast("Thanks for rating"); renderConnections(); }
    catch (err) { toast(err.message, true); }
  });
}

// ---------------------------------------------------------------- profile
function renderProfile() {
  const u = S.user;
  app.innerHTML = `<div class="grid2" style="align-items:start">
    <section class="card"><h2>Your profile</h2>
      <p class="small muted">Others see you as <b>${esc(u.alias)}</b>. Name, email and company stay private until you choose to reveal them.</p>
      <form id="pf">
        <div class="field"><label>Headline</label><input name="headline" value="${esc(u.headline)}"></div>
        <div class="grid2">
          <div class="field"><label>Seniority</label><select name="seniority">${opts(S.meta.seniorities, u.seniority)}</select></div>
          <div class="field"><label>Function</label><select name="function">${opts(S.meta.functions, u.function, "Select...")}</select></div>
          <div class="field"><label>Industry</label><select name="industry">${opts(S.meta.industries, u.industry, "Select...")}</select></div>
          <div class="field"><label>Country</label><select name="country">${opts(COUNTRIES, u.country)}</select></div></div>
        <div class="grid2"><div class="field"><label>City</label><input name="city" value="${esc(u.city)}"></div>
          <div class="field"><label>Company (private)</label><input name="company" value="${esc(u.company)}"></div></div>
        <div class="field"><label>Areas of interest</label><input name="interests" value="${esc(u.interests)}"></div>
        <div class="field"><label>About you</label><textarea name="bio">${esc(u.bio)}</textarea></div>
        <div class="field"><label>Investment focus</label><input name="investment_focus" value="${esc(u.investment_focus)}"></div>
        <div class="field"><label>LinkedIn URL (private)</label><input name="linkedin_url" value="${esc(u.linkedin_url)}"></div>
        <div class="row" style="margin-bottom:1rem"><label class="check"><input type="checkbox" name="hiring" ${u.hiring ? "checked" : ""}> I'm hiring</label>
          <label class="check"><input type="checkbox" name="board_experience" ${u.board_experience ? "checked" : ""}> Board experience</label></div>
        <label>Looking for</label>
        <div class="chips" id="pchips">${Object.entries(S.meta.intents).map(([k, v]) =>
          `<span class="chip ${u.intents.includes(k) ? "on" : ""}" data-k="${k}">${esc(v)}</span>`).join("")}</div>
        <button style="margin-top:1rem">Save profile</button></form></section>
    <div class="stack">
      <section class="card"><h3>Verification</h3>
        <p><span class="tag ${u.email_verified ? "green" : "amber"}">${u.email_verified ? "✓" : "…"} Work email</span>
        <span class="tag ${u.company_verified ? "green" : "amber"}">${u.company_verified ? "✓ Company domain" : "Company not verified"}</span>
        <span class="tag ${u.linkedin_status === "verified" ? "green" : "amber"}">LinkedIn: ${esc(u.linkedin_status)}</span></p>
        <p class="small muted">LinkedIn profiles are reviewed by our team (production: Sign in with LinkedIn / OpenID Connect).</p></section>
      <section class="card"><h3>Security</h3>
        <p>2-step verification: <b>${u.mfa_enabled ? "On" : "Off"}</b></p>
        ${u.mfa_enabled ? '<button class="danger" id="mfa-off">Turn off</button>' : '<button id="mfa-on">Set up authenticator app</button>'}</section>
      <section class="card"><h3>Premium</h3>
        <p class="small">Free members are matched within their own country. Premium unlocks <b>cross-country matching</b> and filters.</p>
        <button id="prem" class="${u.is_premium ? "secondary" : ""}">${u.is_premium ? "Cancel Premium (demo)" : "Upgrade to Premium (demo - no payment)"}</button></section>
    </div></div>`;
  let intents = [...u.intents];
  $$("#pchips .chip").forEach((ch) => ch.addEventListener("click", () => {
    ch.classList.toggle("on");
    intents = ch.classList.contains("on") ? [...intents, ch.dataset.k] : intents.filter((x) => x !== ch.dataset.k);
  }));
  $("#pf").addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target), d = Object.fromEntries(fd);
    d.hiring = fd.has("hiring"); d.board_experience = fd.has("board_experience"); d.intents = intents;
    try {
      const r = await api("PUT", "/api/me", d);
      S.user = r.user; toast("Profile saved");
      if (r.user.status !== "active") route();
    } catch (err) { toast(err.message, true); }
  });
  if ($("#mfa-on")) $("#mfa-on").addEventListener("click", () => renderMfaSetup(false));
  if ($("#mfa-off")) $("#mfa-off").addEventListener("click", () => {
    modal(`<h3>Turn off 2-step verification</h3><form id="mo"><div class="field"><label>Current code</label><input name="code" maxlength="6" required></div>
      <div class="row"><button class="danger">Turn off</button><button type="button" class="secondary" onclick="closeModal()">Cancel</button></div></form>`);
    $("#mo").addEventListener("submit", async (e) => {
      e.preventDefault();
      try { await api("POST", "/api/mfa/disable", { code: e.target.code.value }); closeModal(); toast("2-step verification off"); route(); }
      catch (err) { toast(err.message, true); }
    });
  });
  $("#prem").addEventListener("click", async () => {
    await api("POST", "/api/premium", { enable: !u.is_premium });
    toast(u.is_premium ? "Premium cancelled" : "Premium on - cross-country matching unlocked");
    route();
  });
}

// ---------------------------------------------------------------- admin
async function renderAdmin() {
  const [st, rq] = await Promise.all([api("GET", "/api/admin/stats"), api("GET", "/api/admin/review")]);
  const t = st.totals;
  const kpi = (v, l) => `<div class="card kpi"><div class="v">${v}</div><div class="l">${l}</div></div>`;
  const bars = (title, rows) => {
    const max = Math.max(1, ...rows.map((r) => r.n));
    return `<section class="card"><h3>${title}</h3>${rows.map((r) => `<div class="hbar"><span>${esc(r.k || "—")}</span>
      <i><b style="width:${(r.n / max) * 100}%"></b></i><span>${r.n}</span></div>`).join("") || '<p class="muted small">No data</p>'}</section>`;
  };
  app.innerHTML = `<div class="stack"><h2>Admin dashboard</h2>
    <div class="kpis">${kpi(t.active, "Active members")}${kpi(t.in_review, "In review")}${kpi(t.blocked, "Blocked sign-ups")}
      ${kpi(t.accepted + " / " + t.connections, "Accepted / requests")}${kpi(t.messages, `Messages (${t.flagged_messages} flagged)`)}
      ${kpi(t.mfa, "Members with MFA")}${kpi(t.premium, "Premium")}${kpi(t.users, "All accounts")}</div>
    <div class="grid3">${bars("Areas of interest", st.top_interests)}${bars("Intents", st.by_intent)}${bars("Industries", st.by_industry)}</div>
    <div class="grid3">${bars("Seniority", st.by_seniority)}${bars("Countries", st.by_country)}${bars("Screening flags", st.risk)}</div>
    <section class="card"><h3>Trust & safety queue</h3>
      <table><thead><tr><th>Member</th><th>Profile</th><th>Status</th><th>Screening</th><th>Actions</th></tr></thead><tbody>
      ${rq.users.map((x) => `<tr><td><b>${esc(x.real_name)}</b><div class="small muted">${esc(x.email)}</div>
          ${x.linkedin_url ? `<a class="small" href="${esc(x.linkedin_url)}" target="_blank" rel="noopener">LinkedIn</a>` : ""}</td>
        <td style="max-width:320px"><b class="small">${esc(x.headline)}</b><div class="small muted">${esc(x.bio).slice(0, 160)}</div></td>
        <td><span class="tag ${x.status === "blocked" ? "amber" : ""}">${esc(x.status)}</span>
          ${x.linkedin_status === "pending" ? '<div><span class="tag">LinkedIn pending</span></div>' : ""}</td>
        <td><b>${x.risk_score}</b> ${esc(x.risk_category)}<div class="small muted">${esc(x.risk_reasons)}</div></td>
        <td><div class="row" style="gap:.4rem">
          ${x.status !== "active" ? `<button class="secondary" data-act="approve" data-id="${x.id}">Approve</button>` : ""}
          ${x.status !== "blocked" ? `<button class="danger" data-act="block" data-id="${x.id}">Block</button>` : ""}
          ${x.linkedin_status === "pending" ? `<button class="secondary" data-act="verify_linkedin" data-id="${x.id}">Verify LinkedIn</button>` : ""}
        </div></td></tr>`).join("")}</tbody></table></section></div>`;
  $$("[data-act]").forEach((b) => b.addEventListener("click", async () => {
    await api("POST", `/api/admin/users/${b.dataset.id}`, { action: b.dataset.act });
    toast("Updated"); renderAdmin();
  }));
}

route().catch((e) => { app.innerHTML = `<div class="card empty">Could not load the app: ${esc(e.message)}</div>`; });
