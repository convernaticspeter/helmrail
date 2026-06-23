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
        .two { display:grid; grid-template-columns:1fr 1fr; gap:12px; } .hidden { display:none !important; }
        .note { border-left:3px solid #ffd057; padding-left:12px; color:#c8d2ea; }
        .policy { display:grid; gap:6px; margin: 12px 0 18px; padding:14px; border-radius:16px; background:rgba(255,208,87,.08); border:1px solid rgba(255,208,87,.18); color:#dbe4fa; }
        @media (max-width: 920px) { .grid,.two { grid-template-columns:1fr; } }
      </style>
    </head>
    <body>
      <main>
        <a href="/">← Helmrail</a>
        <div class="eyebrow">Local-only control panel</div>
        <h1>Connect subscriptions without breaking provider rules.</h1>
        <div class="policy">
          <strong>Provider policy</strong>
          <span>OpenAI subscriptions use the local Codex CLI/OAuth path — no OpenAI key field.</span>
          <span>Anthropic and Google consumer subscriptions are not bridged; only their official API products get API-key connectors.</span>
          <span>GPT-5.5 Pro runs through the existing Hermes /pro Oracle browser connector.</span>
        </div>

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
            <div class="card" id="codex">
              <h2>Codex CLI / API coding workbench</h2>
              <p>OpenAI subscription tasks route through the local Codex CLI. Z.ai, Kimi, MiniMax and OpenRouter can run through their OpenAI-compatible APIs.</p>
              <div class="two">
                <label>Provider
                  <select id="codexSubscription"></select>
                </label>
                <label>Model
                  <input id="codexModel" placeholder="gpt-5.5, glm-5.2, kimi-k2.7-code, MiniMax-M3">
                </label>
              </div>
              <label>Task
                <textarea id="codexPrompt" placeholder="Ask for a code change, review, refactor plan, or patch guidance"></textarea>
              </label>
              <label><input id="dryRun" type="checkbox" checked style="width:auto"> Dry-run first (no Codex/API call)</label>
              <div class="actions"><button id="runCodex">Run coding task</button><button class="secondary" id="codexStatusBtn">Codex status</button></div>
              <pre id="codexOutput"></pre>
            </div>
            <div class="card" id="oracle">
              <h2>GPT-5.5 Pro Oracle</h2>
              <p>Use the Hermes /pro Oracle browser path for ChatGPT Pro questions. This does not use an API key.</p>
              <label>Model
                <input id="oracleModel" value="gpt-5.5-pro">
              </label>
              <label>Question
                <textarea id="oraclePrompt" placeholder="Ask GPT-5.5 Pro for a second opinion"></textarea>
              </label>
              <div class="two">
                <label>Wait seconds
                  <input id="oracleWait" type="number" min="0" max="900" value="45">
                </label>
                <label><input id="oracleDryRun" type="checkbox" checked style="width:auto"> Dry-run first</label>
              </div>
              <div class="actions"><button id="runOracle">Run Oracle</button><button class="secondary" id="oracleStatusBtn">Oracle status</button></div>
              <pre id="oracleOutput"></pre>
            </div>
          </section>

          <aside class="card">
            <h2>Add connector</h2>
            <form id="form">
              <label>Provider preset
                <select id="preset" name="preset"></select>
              </label>
              <div class="two">
                <label>Provider slug
                  <input name="provider" required placeholder="zai">
                </label>
                <label>Connector type
                  <select name="connector_type" required>
                    <option value="codex_cli">Codex CLI / OpenAI subscription</option>
                    <option value="oracle_browser">Oracle browser / ChatGPT Pro</option>
                    <option value="api_key_local">API key stored locally</option>
                    <option value="api_key_env">API key from env var</option>
                    <option value="manual">Manual / not automated yet</option>
                  </select>
                </label>
              </div>
              <label>Account label
                <input name="account_label" placeholder="Z.ai Coding Plan" required>
              </label>
              <label>Plan / note
                <input name="plan" placeholder="Coding plan, API, ChatGPT Pro">
              </label>
              <label id="apiKeyField">API key <span class="meta">API providers only; never for OpenAI subscription or Oracle</span>
                <input name="api_key" type="password" autocomplete="off" placeholder="Provider API key">
              </label>
              <label id="credentialField">Credential reference <span class="meta" id="credentialHint">CLI command, env var, browser profile, or note</span>
                <input name="credential_ref" placeholder="codex or PROVIDER_API_KEY">
              </label>
              <label id="baseUrlField">Base URL
                <input name="base_url" placeholder="https://api.moonshot.ai/v1">
              </label>
              <label>Model aliases
                <input name="model_aliases" placeholder="glm-5.2, kimi-k2.7-code, MiniMax-M3">
              </label>
              <label>Metadata JSON
                <textarea name="metadata" placeholder='{"api_style":"openai_compatible"}'></textarea>
              </label>
              <button type="submit">Save connector</button>
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
        const oracleOutput = document.getElementById('oracleOutput');
        let presets = [];
        let subs = [];
        keyInput.value = localStorage.getItem('helmrail_api_key') || '';
        document.getElementById('saveKey').onclick = () => { localStorage.setItem('helmrail_api_key', keyInput.value.trim()); statusBox.textContent='Saved locally in this browser.'; loadAll(); };
        document.getElementById('reload').onclick = () => loadAll();
        function headers() { const token = keyInput.value.trim(); const h={'Content-Type':'application/json'}; if (token) h.Authorization='Bearer '+token; return h; }
        async function api(path, options={}) { const res = await fetch(path, {...options, headers:{...headers(), ...(options.headers || {})}}); const body = await res.json().catch(()=>({})); if (!res.ok) throw new Error((body && body.detail) || res.statusText); return body; }
        function escapeHtml(value) { return String(value ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c])); }
        function csv(value) { return Array.isArray(value) ? value.join(', ') : String(value || ''); }
        function apiStyleOf(item) { return (item.metadata && item.metadata.api_style) || item.api_style || ''; }
        async function loadPresets() {
          const body = await fetch('/v1/provider-presets').then(r => r.json());
          presets = body.data || [];
          const select = document.getElementById('preset');
          select.innerHTML = presets.map(p => `<option value="${escapeHtml(p.id)}">${escapeHtml(p.label)}</option>`).join('');
          select.onchange = applyPreset;
          document.getElementById('form').connector_type.onchange = updateFieldVisibility;
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
          form.metadata.value = JSON.stringify({api_style:p.api_style || 'openai_compatible', preset:p.id, key_policy:p.key_policy || 'api_key_allowed', help:p.help || ''}, null, 2);
          form.credential_ref.value = p.credential_ref || (p.connector_type === 'api_key_env' ? String(p.provider || '').toUpperCase() + '_API_KEY' : '');
          form.api_key.value = '';
          updateFieldVisibility();
        }
        function updateFieldVisibility() {
          const form = document.getElementById('form');
          const connector = form.connector_type.value;
          document.getElementById('apiKeyField').classList.toggle('hidden', connector !== 'api_key_local');
          document.getElementById('baseUrlField').classList.toggle('hidden', !['api_key_local','api_key_env'].includes(connector));
          const hint = document.getElementById('credentialHint');
          if (connector === 'codex_cli') hint.textContent = 'Codex command, usually codex';
          else if (connector === 'oracle_browser') hint.textContent = 'Oracle browser profile path';
          else if (connector === 'api_key_env') hint.textContent = 'Environment variable name, e.g. KIMI_API_KEY';
          else hint.textContent = 'Optional reference/note';
        }
        async function loadSubs() {
          try {
            const body = await api('/v1/subscriptions');
            subs = body.data || [];
            renderSubs(); renderCodexOptions();
          } catch (err) { list.innerHTML = '<p class="warn">'+escapeHtml(err.message)+'</p>'; }
        }
        function renderSubs() {
          if (!subs.length) { list.innerHTML = '<p>No connectors yet. Start with OpenAI Subscription / Codex CLI, GPT-5.5 Pro / Oracle, or an API provider.</p>'; return; }
          list.innerHTML = subs.map(item => {
            const secret = ['codex_cli','oracle_browser','manual'].includes(item.connector_type) ? 'not used' : (item.has_secret ? escapeHtml(item.secret_preview) : 'none');
            return `<article class="sub" data-id="${escapeHtml(item.id)}">
              <div class="sub-head"><div><div class="name">${escapeHtml(item.provider)} · ${escapeHtml(item.account_label)}</div><div class="meta">${escapeHtml(item.plan || 'no plan')} · ${escapeHtml(item.connector_type)} · ${escapeHtml(item.base_url || item.credential_ref || 'no endpoint/ref')}</div></div><span class="pill ${item.enabled ? 'ready':'warn'}">${item.enabled ? 'enabled':'disabled'}</span></div>
              <div class="meta">Secret: ${secret} · Models: ${(item.model_aliases || []).map(escapeHtml).join(', ') || 'none'}</div>
              <div class="actions"><button class="secondary" onclick="probe('${item.id}')">Probe</button><button class="danger" onclick="removeSub('${item.id}')">Delete</button></div>
            </article>`;
          }).join('');
        }
        function renderCodexOptions() {
          const select = document.getElementById('codexSubscription');
          const codingSubs = subs.filter(s => s.connector_type === 'codex_cli' || apiStyleOf(s) === 'openai_compatible');
          select.innerHTML = codingSubs.map(s => `<option value="${escapeHtml(s.id)}">${escapeHtml(s.provider)} · ${escapeHtml(s.account_label)}</option>`).join('');
          const selected = codingSubs.find(s => s.id === select.value) || codingSubs[0];
          if (selected && !document.getElementById('codexModel').value) document.getElementById('codexModel').value = (selected.model_aliases || [])[0] || '';
        }
        async function probe(id) { try { statusBox.textContent = JSON.stringify(await api('/v1/subscriptions/'+id+'/probe',{method:'POST'}), null, 2); await loadSubs(); } catch (err) { statusBox.textContent = err.message; } }
        async function removeSub(id) { if (!confirm('Delete this connector?')) return; try { await api('/v1/subscriptions/'+id,{method:'DELETE'}); await loadSubs(); } catch (err) { statusBox.textContent = err.message; } }
        window.probe = probe; window.removeSub = removeSub;
        document.getElementById('form').onsubmit = async (event) => {
          event.preventDefault(); const fd = new FormData(event.target); let metadata = {}; const metadataText = String(fd.get('metadata') || '').trim(); if (metadataText) metadata = JSON.parse(metadataText);
          const payload = { provider:String(fd.get('provider')||'').trim(), account_label:String(fd.get('account_label')||'').trim(), plan:String(fd.get('plan')||'').trim(), connector_type:String(fd.get('connector_type')||'').trim(), credential_ref:String(fd.get('credential_ref')||'').trim(), base_url:String(fd.get('base_url')||'').trim(), api_key:String(fd.get('api_key')||'').trim(), model_aliases:String(fd.get('model_aliases')||'').split(',').map(s=>s.trim()).filter(Boolean), metadata };
          try { const saved = await api('/v1/subscriptions',{method:'POST', body:JSON.stringify(payload)}); statusBox.textContent = JSON.stringify(saved, null, 2); event.target.reset(); applyPreset(); await loadSubs(); } catch (err) { statusBox.textContent = err.message; }
        };
        document.getElementById('codexStatusBtn').onclick = async () => { try { codexOutput.textContent = JSON.stringify(await api('/v1/codex/status'), null, 2); } catch (err) { codexOutput.textContent = err.message; } };
        document.getElementById('runCodex').onclick = async () => { try { codexOutput.textContent = 'Running…'; const payload={subscription_id:document.getElementById('codexSubscription').value, model:document.getElementById('codexModel').value.trim(), prompt:document.getElementById('codexPrompt').value, dry_run:document.getElementById('dryRun').checked}; codexOutput.textContent = JSON.stringify(await api('/v1/codex/run',{method:'POST', body:JSON.stringify(payload)}), null, 2); } catch (err) { codexOutput.textContent = err.message; } };
        document.getElementById('oracleStatusBtn').onclick = async () => { try { oracleOutput.textContent = JSON.stringify(await api('/v1/oracle/status'), null, 2); } catch (err) { oracleOutput.textContent = err.message; } };
        document.getElementById('runOracle').onclick = async () => { try { oracleOutput.textContent = 'Running…'; const payload={model:document.getElementById('oracleModel').value.trim() || 'gpt-5.5-pro', prompt:document.getElementById('oraclePrompt').value, wait_seconds:Number(document.getElementById('oracleWait').value || 45), dry_run:document.getElementById('oracleDryRun').checked}; oracleOutput.textContent = JSON.stringify(await api('/v1/oracle/run',{method:'POST', body:JSON.stringify(payload)}), null, 2); } catch (err) { oracleOutput.textContent = err.message; } };
        async function loadAll() { await loadPresets(); await loadSubs(); }
        loadAll();
      </script>
    </body>
    </html>
    """
