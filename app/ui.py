from __future__ import annotations


def setup_page() -> str:
    return """
    <!doctype html>
    <html lang="en">
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <title>Helmrail Setup</title>
      <style>
        :root { color-scheme: dark; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
        body { margin:0; min-height:100vh; background: radial-gradient(circle at top left,#202b55,#070a12 45%,#05060a); color:#eef3ff; }
        main { width:min(1180px, calc(100vw - 34px)); margin:0 auto; padding:34px 0 64px; }
        a { color:#ffd057; } h1 { margin:.15em 0; font-size:clamp(36px,7vw,72px); letter-spacing:-.05em; line-height:.94; }
        h2 { margin-top:0; } p { color:#b8c2dc; line-height:1.6; } code { color:#ffd057; }
        .eyebrow { color:#ffd057; text-transform:uppercase; letter-spacing:.16em; font-size:12px; font-weight:900; }
        .grid { display:grid; grid-template-columns: minmax(0,1fr) minmax(360px,440px); gap:18px; align-items:start; }
        .card { border:1px solid rgba(255,255,255,.13); border-radius:24px; padding:22px; background:rgba(255,255,255,.06); box-shadow:0 20px 80px rgba(0,0,0,.30); }
        .cards { display:grid; gap:12px; }
        label { display:grid; gap:7px; margin-bottom:12px; color:#ccd5ed; font-weight:750; }
        input, select, textarea { width:100%; box-sizing:border-box; border:1px solid rgba(255,255,255,.16); background:rgba(0,0,0,.30); color:#eef3ff; border-radius:13px; padding:12px 13px; font:inherit; }
        textarea { min-height:96px; resize:vertical; }
        button { border:0; border-radius:13px; padding:11px 14px; background:#ffd057; color:#08101f; font-weight:900; cursor:pointer; }
        button.secondary { background:rgba(255,255,255,.11); color:#eef3ff; border:1px solid rgba(255,255,255,.16); }
        button.danger { background:rgba(255, 92, 92, .16); color:#ffaaaa; border:1px solid rgba(255,92,92,.32); }
        .toolbar { display:flex; flex-wrap:wrap; gap:10px; align-items:end; margin:18px 0; }
        .toolbar label { flex:1 1 360px; margin:0; }
        .sub { display:grid; gap:10px; border:1px solid rgba(255,255,255,.12); border-radius:18px; padding:16px; background:rgba(0,0,0,.18); }
        .sub-head { display:flex; justify-content:space-between; gap:12px; align-items:start; }
        .name { font-size:19px; font-weight:950; } .meta { color:#9da9c5; font-size:14px; overflow-wrap:anywhere; }
        .pill { display:inline-flex; width:fit-content; padding:5px 9px; border-radius:999px; background:rgba(255,255,255,.10); color:#ccd5ed; font-size:12px; font-weight:850; }
        .ready { background:rgba(73,255,170,.12); color:#83ffc2; } .warn { background:rgba(255,208,87,.12); color:#ffd057; }
        .actions { display:flex; flex-wrap:wrap; gap:8px; } pre { white-space:pre-wrap; overflow-wrap:anywhere; background:rgba(0,0,0,.36); border-radius:14px; padding:12px; color:#dfe7fb; max-height:360px; overflow:auto; }
        .two { display:grid; grid-template-columns:1fr 1fr; gap:12px; } .three { display:grid; grid-template-columns:1fr 1fr 1fr; gap:12px; }
        .note { border-left:3px solid #ffd057; padding-left:12px; color:#c8d2ea; } .hidden { display:none; }
        @media (max-width: 920px) { .grid,.two,.three { grid-template-columns:1fr; } }
      </style>
    </head>
    <body>
      <main>
        <a href="/">← Helmrail</a>
        <div class="eyebrow">Local-only control panel</div>
        <h1>Connect providers. Run Codex-style coding tasks.</h1>
        <p class="note">Helmrail is currently bound to <code>127.0.0.1</code>. Provider API keys are stored locally and returned only as masked previews. For production-hardening, use OS keychain/encrypted storage next.</p>

        <div class="toolbar card">
          <label>Local admin key
            <input id="apiKey" type="password" placeholder="Paste key from ~/.hermes/secrets/helmrail-admin-api-key.txt">
          </label>
          <button id="saveKey">Save in this browser</button>
          <button class="secondary" id="reload">Reload</button>
        </div>

        <div class="grid">
          <section class="cards">
            <div class="card">
              <h2>Connected providers</h2>
              <div id="subscriptions" class="cards">Loading…</div>
            </div>
            <div class="card">
              <h2>Codex workbench</h2>
              <p>Use an OpenAI/OpenAI-compatible provider as the coding backend. If the real Codex CLI is installed later, Helmrail detects it in status.</p>
              <div class="two">
                <label>Provider
                  <select id="codexSubscription"></select>
                </label>
                <label>Model
                  <input id="codexModel" placeholder="e.g. your Codex/OpenAI model name">
                </label>
              </div>
              <label>Task
                <textarea id="codexPrompt" placeholder="Ask for a code change, review, refactor plan, or patch guidance"></textarea>
              </label>
              <label><input id="dryRun" type="checkbox" checked style="width:auto"> Dry-run first (no provider call)</label>
              <div class="actions"><button id="runCodex">Run Codex task</button><button class="secondary" id="codexStatusBtn">Codex status</button></div>
              <pre id="codexOutput"></pre>
            </div>
          </section>

          <aside class="card">
            <h2>Add API key / subscription</h2>
            <form id="form">
              <label>Provider preset
                <select id="preset" name="preset"></select>
              </label>
              <div class="two">
                <label>Provider slug
                  <input name="provider" required placeholder="openai">
                </label>
                <label>Connector type
                  <select name="connector_type" required>
                    <option value="api_key_local">Paste API key locally</option>
                    <option value="api_key_env">API key from env var</option>
                    <option value="codex_cli">Codex CLI on this computer</option>
                    <option value="browser_profile">Browser profile</option>
                    <option value="oauth">OAuth placeholder</option>
                    <option value="manual">Manual / not automated yet</option>
                  </select>
                </label>
              </div>
              <label>Account label
                <input name="account_label" placeholder="Peter · OpenAI Codex" required>
              </label>
              <label>Plan / note
                <input name="plan" placeholder="Codex, Claude Max, Gemini Advanced, OpenRouter">
              </label>
              <label>API key <span class="meta">stored locally, never shown back</span>
                <input name="api_key" type="password" autocomplete="off" placeholder="sk-...">
              </label>
              <label>Credential reference <span class="meta">env var, CLI command, browser profile, or note</span>
                <input name="credential_ref" placeholder="OPENAI_API_KEY or codex or /path/to/profile">
              </label>
              <label>Base URL
                <input name="base_url" placeholder="https://api.openai.com/v1">
              </label>
              <label>Model aliases
                <input name="model_aliases" placeholder="codex, gpt-4.1, provider/model-name">
              </label>
              <label>Metadata JSON
                <textarea name="metadata" placeholder='{"api_style":"openai_compatible"}'></textarea>
              </label>
              <button type="submit">Save provider</button>
            </form>
            <pre id="status"></pre>
          </aside>
        </div>
      </main>
      <script>
        const keyInput = document.getElementById('apiKey');
        const statusBox = document.getElementById('status');
        const list = document.getElementById('subscriptions');
        const codexOutput = document.getElementById('codexOutput');
        let presets = [];
        let subs = [];
        keyInput.value = localStorage.getItem('helmrail_api_key') || '';
        document.getElementById('saveKey').onclick = () => { localStorage.setItem('helmrail_api_key', keyInput.value.trim()); statusBox.textContent='Saved locally in this browser.'; loadAll(); };
        document.getElementById('reload').onclick = () => loadAll();
        function headers() { const token = keyInput.value.trim(); const h={'Content-Type':'application/json'}; if (token) h.Authorization='Bearer '+token; return h; }
        async function api(path, options={}) { const res = await fetch(path, {...options, headers:{...headers(), ...(options.headers || {})}}); const body = await res.json().catch(()=>({})); if (!res.ok) throw new Error((body && body.detail) || res.statusText); return body; }
        function escapeHtml(value) { return String(value ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c])); }
        function csv(value) { return Array.isArray(value) ? value.join(', ') : String(value || ''); }
        async function loadPresets() {
          const body = await fetch('/v1/provider-presets').then(r => r.json());
          presets = body.data || [];
          const select = document.getElementById('preset');
          select.innerHTML = presets.map(p => `<option value="${escapeHtml(p.id)}">${escapeHtml(p.label)}</option>`).join('');
          select.onchange = applyPreset;
          applyPreset();
        }
        function applyPreset() {
          const form = document.getElementById('form');
          const p = presets.find(x => x.id === document.getElementById('preset').value) || presets[0];
          if (!p) return;
          form.provider.value = p.provider || '';
          form.connector_type.value = p.connector_type || 'api_key_local';
          form.plan.value = p.plan || '';
          form.account_label.value = p.label || '';
          form.base_url.value = p.base_url || '';
          form.model_aliases.value = csv(p.model_aliases || []);
          form.metadata.value = JSON.stringify({api_style:p.api_style || 'openai_compatible', preset:p.id, help:p.help || ''}, null, 2);
          form.credential_ref.value = p.connector_type === 'api_key_env' ? String(p.provider || '').toUpperCase() + '_API_KEY' : '';
        }
        async function loadSubs() {
          try {
            const body = await api('/v1/subscriptions');
            subs = body.data || [];
            renderSubs(); renderCodexOptions();
          } catch (err) { list.innerHTML = '<p class="warn">'+escapeHtml(err.message)+'</p>'; }
        }
        function renderSubs() {
          if (!subs.length) { list.innerHTML = '<p>No provider keys linked yet. Start with OpenAI / Codex on the right.</p>'; return; }
          list.innerHTML = subs.map(item => `
            <article class="sub" data-id="${escapeHtml(item.id)}">
              <div class="sub-head"><div><div class="name">${escapeHtml(item.provider)} · ${escapeHtml(item.account_label)}</div><div class="meta">${escapeHtml(item.plan || 'no plan')} · ${escapeHtml(item.connector_type)} · ${escapeHtml(item.base_url || item.credential_ref || 'no endpoint/ref')}</div></div><span class="pill ${item.enabled ? 'ready':'warn'}">${item.enabled ? 'enabled':'disabled'}</span></div>
              <div class="meta">Secret: ${item.has_secret ? escapeHtml(item.secret_preview) : 'none'} · Models: ${(item.model_aliases || []).map(escapeHtml).join(', ') || 'none'}</div>
              <div class="actions"><button class="secondary" onclick="probe('${item.id}')">Probe</button><button class="danger" onclick="removeSub('${item.id}')">Delete</button></div>
            </article>`).join('');
        }
        function renderCodexOptions() {
          const select = document.getElementById('codexSubscription');
          select.innerHTML = subs.map(s => `<option value="${escapeHtml(s.id)}">${escapeHtml(s.provider)} · ${escapeHtml(s.account_label)}</option>`).join('');
          const selected = subs.find(s => s.id === select.value) || subs[0];
          if (selected && !document.getElementById('codexModel').value) document.getElementById('codexModel').value = (selected.model_aliases || [])[0] || '';
        }
        async function probe(id) { try { statusBox.textContent = JSON.stringify(await api('/v1/subscriptions/'+id+'/probe',{method:'POST'}), null, 2); await loadSubs(); } catch (err) { statusBox.textContent = err.message; } }
        async function removeSub(id) { if (!confirm('Delete this provider?')) return; try { await api('/v1/subscriptions/'+id,{method:'DELETE'}); await loadSubs(); } catch (err) { statusBox.textContent = err.message; } }
        window.probe = probe; window.removeSub = removeSub;
        document.getElementById('form').onsubmit = async (event) => {
          event.preventDefault(); const fd = new FormData(event.target); let metadata = {}; const metadataText = String(fd.get('metadata') || '').trim(); if (metadataText) metadata = JSON.parse(metadataText);
          const payload = { provider:String(fd.get('provider')||'').trim(), account_label:String(fd.get('account_label')||'').trim(), plan:String(fd.get('plan')||'').trim(), connector_type:String(fd.get('connector_type')||'').trim(), credential_ref:String(fd.get('credential_ref')||'').trim(), base_url:String(fd.get('base_url')||'').trim(), api_key:String(fd.get('api_key')||'').trim(), model_aliases:String(fd.get('model_aliases')||'').split(',').map(s=>s.trim()).filter(Boolean), metadata };
          try { const saved = await api('/v1/subscriptions',{method:'POST', body:JSON.stringify(payload)}); statusBox.textContent = JSON.stringify(saved, null, 2); event.target.reset(); applyPreset(); await loadSubs(); } catch (err) { statusBox.textContent = err.message; }
        };
        document.getElementById('codexStatusBtn').onclick = async () => { try { codexOutput.textContent = JSON.stringify(await api('/v1/codex/status'), null, 2); } catch (err) { codexOutput.textContent = err.message; } };
        document.getElementById('runCodex').onclick = async () => { try { codexOutput.textContent = 'Running…'; const payload={subscription_id:document.getElementById('codexSubscription').value, model:document.getElementById('codexModel').value.trim(), prompt:document.getElementById('codexPrompt').value, dry_run:document.getElementById('dryRun').checked}; codexOutput.textContent = JSON.stringify(await api('/v1/codex/run',{method:'POST', body:JSON.stringify(payload)}), null, 2); } catch (err) { codexOutput.textContent = err.message; } };
        async function loadAll() { await loadPresets(); await loadSubs(); }
        loadAll();
      </script>
    </body>
    </html>
    """
