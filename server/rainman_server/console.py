"""Minimal admin console (single self-contained HTML page, vanilla JS)."""

CONSOLE_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Rainman Sync — Admin</title>
<style>
  :root { color-scheme: light dark; }
  body { font: 15px/1.5 system-ui, sans-serif; max-width: 880px; margin: 2rem auto; padding: 0 1rem; }
  h1 { font-size: 1.4rem; } h2 { font-size: 1.05rem; margin-top: 2rem; }
  input, select, button { font: inherit; padding: .4rem .5rem; }
  table { border-collapse: collapse; width: 100%; margin-top: .5rem; }
  th, td { text-align: left; padding: .4rem .6rem; border-bottom: 1px solid #8884; }
  .bar { display: flex; gap: .5rem; flex-wrap: wrap; align-items: center; }
  .token { font-family: ui-monospace, monospace; word-break: break-all; background: #8881; padding: .5rem; border-radius: 6px; }
  .muted { opacity: .65; } .err { color: #c0392b; } button { cursor: pointer; }
</style>
</head>
<body>
<h1>Rainman Sync — Admin Console</h1>
<p class="muted">Admin token required. It is scoped to one workspace; everything below operates on that workspace.</p>

<div class="bar">
  <input id="tok" type="password" placeholder="admin bearer token" size="40">
  <button onclick="save()">Use token</button>
  <span id="status" class="muted"></span>
</div>

<h2>Mint a token</h2>
<div class="bar">
  <input id="newUser" placeholder="username">
  <select id="newRole">
    <option value="reader">reader</option>
    <option value="contributor" selected>contributor</option>
    <option value="admin">admin</option>
  </select>
  <button onclick="mint()">Create</button>
</div>
<div id="minted"></div>

<h2>Users</h2>
<table><thead><tr><th>User</th><th>Role</th><th></th></tr></thead><tbody id="users"></tbody></table>

<h2>Audit (latest 100)</h2>
<table><thead><tr><th>When</th><th>Actor</th><th>Action</th><th>Detail</th></tr></thead><tbody id="audit"></tbody></table>

<script>
function token() { return localStorage.getItem("rainman_admin_token") || ""; }
function save() {
  localStorage.setItem("rainman_admin_token", document.getElementById("tok").value.trim());
  refresh();
}
async function api(method, path, body) {
  const opt = { method, headers: { "Authorization": "Bearer " + token() } };
  if (body) { opt.headers["Content-Type"] = "application/json"; opt.body = JSON.stringify(body); }
  const r = await fetch(path, opt);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || r.status);
  return r.json();
}
async function mint() {
  const username = document.getElementById("newUser").value.trim();
  const role = document.getElementById("newRole").value;
  const out = document.getElementById("minted");
  try {
    const res = await api("POST", "/v1/admin/tokens", { username, role });
    out.innerHTML = '<p>Token for <b>' + res.username + '</b> (' + res.role +
      ') — copy it now, it will not be shown again:</p><div class="token">' + res.token + '</div>';
    refresh();
  } catch (e) { out.innerHTML = '<p class="err">' + e.message + '</p>'; }
}
async function revoke(username) {
  if (!confirm("Revoke all access for " + username + "?")) return;
  try { await api("POST", "/v1/admin/revoke", { username }); refresh(); }
  catch (e) { alert(e.message); }
}
async function refresh() {
  const status = document.getElementById("status");
  if (!token()) { status.textContent = "no token set"; return; }
  try {
    const u = await api("GET", "/v1/admin/users");
    document.getElementById("users").innerHTML = u.users.map(x =>
      '<tr><td>' + x.username + '</td><td>' + x.role +
      '</td><td><button onclick="revoke(\'' + x.username + '\')">revoke</button></td></tr>'
    ).join("") || '<tr><td colspan=3 class="muted">no users</td></tr>';
    const a = await api("GET", "/v1/admin/audit?limit=100");
    document.getElementById("audit").innerHTML = a.events.map(e =>
      '<tr><td>' + new Date(e.ts * 1000).toLocaleString() + '</td><td>' + e.actor +
      '</td><td>' + e.action + '</td><td class="muted">' + (e.detail || "") + '</td></tr>'
    ).join("") || '<tr><td colspan=4 class="muted">no events</td></tr>';
    status.textContent = "connected";
    status.className = "muted";
  } catch (e) { status.textContent = "error: " + e.message; status.className = "err"; }
}
document.getElementById("tok").value = token();
refresh();
</script>
</body>
</html>
"""
