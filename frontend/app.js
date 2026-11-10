/* ==========================================================================
   EDA Agent v2.0 — 前端交互工作台
   统一走 /api/chat，配合 NLU 实时预览、模板库、会话历史、设置与桌面化工具条。
   纯原生 JS，无构建、无外链依赖，离线可用。
   ========================================================================== */
(function () {
  'use strict';

  /* ---------------------------------------------------------------- 状态 */
  var state = {
    difficulty: 'intermediate',
    style: 'classic',
    projectName: '',
    forceOffline: false,
    design: null,
    result: null,
    sessionId: null,
    generating: false,
    capabilities: null,
    templates: [],
    quickGroup: '',
    svgText: '',
    zoom: 1,
    panX: 0,
    panY: 0,
    theme: localStorage.getItem('eda-theme') || 'light',
    autoPreview: true,
    lastUserText: '',
    messages: []          // {role, text} 用于导出对话
  };

  function $(s) { return document.querySelector(s); }
  function $$(s) { return Array.prototype.slice.call(document.querySelectorAll(s)); }
  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function toast(msg, isError) {
    var t = $('#toast');
    t.textContent = msg;
    t.className = 'toast show' + (isError ? ' error' : '');
    clearTimeout(t._timer);
    t._timer = setTimeout(function () { t.className = 'toast'; }, 3200);
  }

  async function api(path, opts) {
    opts = opts || {};
    var init = {
      method: opts.method || 'GET',
      headers: { 'Content-Type': 'application/json' }
    };
    if (opts.body !== undefined) init.body = JSON.stringify(opts.body);
    var r;
    try { r = await fetch(path, init); }
    catch (e) { throw new Error('无法连接本地服务：' + e.message); }
    if (!r.ok) {
      var detail = '';
      try { var d = await r.json(); detail = d.detail || ''; } catch (e) { /* ignore */ }
      throw new Error(detail || ('HTTP ' + r.status));
    }
    return r.json();
  }

  function downloadBlob(content, filename, mime) {
    var blob = new Blob([content], { type: (mime || 'text/plain') + ';charset=utf-8' });
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url; a.download = filename;
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
    setTimeout(function () { URL.revokeObjectURL(url); }, 1500);
  }

  async function copyText(text) {
    try {
      await navigator.clipboard.writeText(text);
      toast('已复制到剪贴板');
    } catch (e) {
      var ta = document.createElement('textarea');
      ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
      document.body.appendChild(ta); ta.select();
      try { document.execCommand('copy'); toast('已复制到剪贴板'); }
      catch (e2) { toast('复制失败，请手动选择', true); }
      document.body.removeChild(ta);
    }
  }

  /* ---------------------------------------------------------- Markdown 渲染 */
  function inline(s) {
    var t = esc(s);
    t = t.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    t = t.replace(/`([^`]+)`/g, '<code>$1</code>');
    t = t.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
    return t;
  }

  function renderMd(md) {
    var lines = String(md || '').split('\n');
    var html = '';
    var inList = false, inTable = false, inQuote = false;
    function closeList() { if (inList) { html += '</ul>'; inList = false; } }
    function closeTable() { if (inTable) { html += '</table>'; inTable = false; } }
    function closeQuote() { if (inQuote) { html += '</blockquote>'; inQuote = false; } }
    lines.forEach(function (raw) {
      var line = raw;
      if (/^\s*---+\s*$/.test(line)) { closeQuote(); closeList(); closeTable(); html += '<hr/>'; return; }
      if (/^>\s?/.test(line)) {
        closeList(); closeTable();
        if (!inQuote) { html += '<blockquote>'; inQuote = true; }
        html += inline(line.replace(/^>\s?/, '')) + '<br/>';
        return;
      }
      closeQuote();
      if (/^\|.*\|/.test(line)) {
        closeList();
        var cells = line.split('|').slice(1, -1).map(function (c) { return c.trim(); });
        if (cells.every(function (c) { return /^:?-{2,}:?$/.test(c); })) return;
        if (!inTable) { html += '<table>'; inTable = true; }
        html += '<tr>' + cells.map(function (c) { return '<td>' + inline(c) + '</td>'; }).join('') + '</tr>';
        return;
      }
      closeTable();
      if (/^### /.test(line)) { closeList(); html += '<h3>' + inline(line.slice(4)) + '</h3>'; return; }
      if (/^## /.test(line)) { closeList(); html += '<h2>' + inline(line.slice(3)) + '</h2>'; return; }
      if (/^# /.test(line)) { closeList(); html += '<h1>' + inline(line.slice(2)) + '</h1>'; return; }
      if (/^[-*] /.test(line)) {
        if (!inList) { html += '<ul>'; inList = true; }
        html += '<li>' + inline(line.replace(/^[-*] /, '')) + '</li>';
        return;
      }
      if (/^\d+\. /.test(line)) {
        if (!inList) { html += '<ul>'; inList = true; }
        html += '<li>' + inline(line.replace(/^\d+\. /, '')) + '</li>';
        return;
      }
      closeList();
      if (line.trim() === '') return;
      html += '<p>' + inline(line) + '</p>';
    });
    closeList(); closeTable(); closeQuote();
    return html;
  }

  /* ------------------------------------------------------------ 聊天消息 */
  function addMessage(role, text, opts) {
    opts = opts || {};
    var box = $('#chatMessages');
    var div = document.createElement('div');
    div.className = 'msg ' + role;

    var avatar = document.createElement('div');
    avatar.className = 'avatar';
    avatar.textContent = role === 'user' ? '我' : 'W';

    var wrap = document.createElement('div');
    wrap.style.minWidth = '0';
    var bubble = document.createElement('div');
    bubble.className = 'bubble';
    if (role === 'assistant') {
      bubble.innerHTML = '<div class="md">' + renderMd(text) + '</div>';
    } else {
      bubble.textContent = text;
    }
    wrap.appendChild(bubble);

    if (opts.actions !== false) {
      var acts = document.createElement('div');
      acts.className = 'msg-actions';
      var copyBtn = document.createElement('button');
      copyBtn.className = 'msg-action'; copyBtn.textContent = '复制';
      copyBtn.onclick = function () { copyText(text); };
      acts.appendChild(copyBtn);
      if (role === 'user') {
        var again = document.createElement('button');
        again.className = 'msg-action'; again.textContent = '重新发送';
        again.onclick = function () { $('#chatInput').value = text; $('#chatInput').focus(); sendMessage(text); };
        acts.appendChild(again);
      }
      wrap.appendChild(acts);
    }

    div.appendChild(avatar);
    div.appendChild(wrap);
    box.appendChild(div);
    box.scrollTop = box.scrollHeight;
    state.messages.push({ role: role, text: text });
    return div;
  }

  function addTyping() {
    var box = $('#chatMessages');
    var div = document.createElement('div');
    div.className = 'msg assistant'; div.id = 'typingMsg';
    var av = document.createElement('div'); av.className = 'avatar'; av.textContent = 'W';
    var b = document.createElement('div'); b.className = 'bubble';
    b.innerHTML = '<span class="typing"><i></i><i></i><i></i></span>';
    div.appendChild(av); div.appendChild(b); box.appendChild(div);
    box.scrollTop = box.scrollHeight;
  }
  function removeTyping() { var t = $('#typingMsg'); if (t) t.remove(); }

  function clearMessages() {
    $('#chatMessages').innerHTML = '';
    state.messages = [];
  }

  function renderSuggestions(list) {
    var row = $('#suggestionRow');
    row.innerHTML = '';
    (list || []).forEach(function (s) {
      var b = document.createElement('button');
      b.className = 'suggest-chip'; b.textContent = s;
      b.onclick = function () { sendMessage(s); };
      row.appendChild(b);
    });
  }

  /* -------------------------------------------------------- 进度步骤动画 */
  function resetSteps() { $$('.step').forEach(function (s) { s.classList.remove('active', 'done'); }); }
  function setStep(n) {
    $$('.step').forEach(function (s, i) {
      var idx = i + 1;
      if (idx < n) { s.classList.add('done'); s.classList.remove('active'); }
      else if (idx === n) { s.classList.add('active'); s.classList.remove('done'); }
    });
  }
  function allStepsDone() { $$('.step').forEach(function (s) { s.classList.add('done'); s.classList.remove('active'); }); }

  /* ---------------------------------------------------------- 实时 NLU 预览 */
  var analyzeTimer = null;
  function renderInsight(a) {
    var bar = $('#insightBar');
    bar.hidden = false;
    $('#insightIntent').textContent = a.intent.label + (a.intent.fallback ? '（推断）' : '');
    var pct = Math.round((a.confidence || 0) * 100);
    $('#confFill').style.width = pct + '%';
    $('#confText').textContent = pct + '%';

    var chips = $('#insightChips');
    chips.innerHTML = '';
    (a.keywords || []).slice(0, 8).forEach(function (k) {
      var s = document.createElement('span');
      s.className = 'i-chip';
      s.innerHTML = '<span class="i-cat">' + esc(k.category) + '</span>' + esc(k.term);
      chips.appendChild(s);
    });
    var ents = a.entities || {};
    [['values', '参数'], ['refs', '元件'], ['voltage', '电压'], ['frequency', '频率']].forEach(function (pair) {
      (ents[pair[0]] || []).slice(0, 3).forEach(function (v) {
        var s = document.createElement('span');
        s.className = 'i-chip entity';
        s.textContent = pair[1] + ':' + v;
        chips.appendChild(s);
      });
    });
    $('#insightSummary').textContent = '理解：' + (a.summary || '—');
    var cl = $('#insightClarify');
    if (a.needs_clarification && a.clarifying_question) {
      cl.hidden = false; cl.textContent = '提示：' + a.clarifying_question;
    } else { cl.hidden = true; }
  }
  function hideInsight() { $('#insightBar').hidden = true; }

  function onInputChange() {
    var v = $('#chatInput').value.trim();
    if (v.charAt(0) === '/') {
      $('#hintText').textContent = '指令：/help 帮助 · /new 新建 · /status 状态 · /reset 清空 · /export 导出';
    } else {
      $('#hintText').textContent = state.design ? '可继续输入修改指令，或描述新电路' : '输入需求后回车发送';
    }
    clearTimeout(analyzeTimer);
    if (!v || !state.autoPreview) { hideInsight(); return; }
    analyzeTimer = setTimeout(async function () {
      try {
        var a = await api('/api/analyze', { method: 'POST', body: { text: v, has_design: !!state.design } });
        if ($('#chatInput').value.trim() === v) renderInsight(a);
      } catch (e) { /* 预览失败不影响主流程 */ }
    }, 280);
  }

  /* ------------------------------------------------------------ 结果渲染 */
  function switchTab(name) {
    $$('.tab').forEach(function (t) { t.classList.toggle('active', t.dataset.tab === name); });
    $$('.panel').forEach(function (p) { p.classList.toggle('active', p.id === 'panel-' + name); });
  }

  function renderResult(data) {
    state.design = data.design;
    state.result = data;

    var title = (data.design && data.design.title) || '设计结果';
    $('#resultTitle').textContent = title;
    var mode = data.mode || '';
    var modeText = mode.indexOf('llm:') === 0 ? '大模型生成'
      : mode.indexOf('offline') === 0 ? '离线规则修改'
        : mode.indexOf('template') === 0 ? '离线模板' : mode || '手动生成';
    var comps = (data.design && data.design.components) || [];
    var nets = (data.design && data.design.nets) || [];
    var diffText = { beginner: '入门', intermediate: '进阶', advanced: '挑战' }[state.difficulty] || '进阶';
    $('#resultMeta').textContent = modeText + ' · ' + comps.length + ' 元件 · ' + nets.length + ' 网络 · ' + diffText + ' · ' + data.project_name;

    ['bom', 'netlist', 'report', 'guide', 'hardware'].forEach(function (k) {
      var el = $('#panel-' + k);
      if (el) el.innerHTML = '<div class="md">' + renderMd(data[k + '_md']) + '</div>';
    });
    try { $('#jsonEditor').value = JSON.stringify(data.design, null, 2); } catch (e) { /* ignore */ }
    $('#btnDownload').href = '/api/download?path=' + encodeURIComponent(data.download_zip);

    $('#resultPanel').hidden = false;
    switchTab('bom');
    if (data.svg) playSvgAnimation(data.svg);
  }

  /* ---------------------------------------------------------- SVG 舞台 */
  function applyTransform() {
    $('#stageSvg').style.transform = 'translate(' + state.panX + 'px,' + state.panY + 'px) scale(' + state.zoom + ')';
    $('#zoomLabel').textContent = Math.round(state.zoom * 100) + '%';
  }
  function setZoom(z) { state.zoom = Math.max(0.4, Math.min(3, z)); applyTransform(); }
  function resetView() { state.zoom = 1; state.panX = 0; state.panY = 0; applyTransform(); }

  function playSvgAnimation(svgText) {
    state.svgText = svgText || '';
    var container = $('#stageSvg');
    container.innerHTML = state.svgText;
    container.hidden = false;
    $('#stageEmpty').hidden = true;
    $('#stageBadge').hidden = false;
    resetView();

    var svg = container.querySelector('svg');
    if (!svg) return;
    svg.querySelectorAll('.comp, .group').forEach(function (el) {
      el.style.setProperty('--i', el.getAttribute('data-i') || '0');
    });
    svg.querySelectorAll('.net').forEach(function (el) {
      el.style.setProperty('--i', el.getAttribute('data-i') || '0');
      var len;
      try { len = el.getTotalLength(); } catch (e) { len = 200; }
      el.style.setProperty('--len', len);
      el.style.strokeDasharray = len;
      el.style.strokeDashoffset = len;
    });
    var total = (svg.querySelectorAll('.comp, .group, .net').length || 1) * 120 + 800;
    $('#stageBadgeText').textContent = '构图进行中…';
    setTimeout(function () {
      $('#stageBadgeText').textContent = '构图完成';
      var dot = $('#stageBadge').querySelector('.badge-dot');
      if (dot) dot.style.animation = 'none';
    }, total);
  }

  function setStageBadge(text) {
    $('#stageBadge').hidden = false;
    $('#stageBadgeText').textContent = text;
    var dot = $('#stageBadge').querySelector('.badge-dot');
    if (dot) dot.style.animation = 'pulse 1.2s ease infinite';
  }

  /* ------------------------------------------------------------ 发送消息 */
  var SLASH_MAP = {
    '/help': '查看帮助', '/new': '新建会话', '/reset': '新建会话',
    '/status': '查询运行状态', '/export': '导出当前设计的报告',
    '/templates': '查看模板库', '/explain': '解释一下当前电路的工作原理'
  };

  async function sendMessage(text) {
    if (state.generating) { toast('正在处理上一条请求，请稍候'); return; }
    text = String(text || '').trim();
    if (!text) return;
    if (SLASH_MAP[text.toLowerCase()]) text = SLASH_MAP[text.toLowerCase()];

    state.lastUserText = text;
    state.generating = true;
    $('#sendBtn').disabled = true;
    $('#chatInput').value = '';
    hideInsight();
    $('#hintText').textContent = '正在处理…';
    $('#suggestionRow').innerHTML = '';
    addMessage('user', text);
    addTyping();

    resetSteps(); setStep(1);
    var isRevision = !!state.design;
    setStageBadge(isRevision ? '正在修改…' : '正在生成…');
    var stepTimer = setInterval(function () {
      var cur = 1;
      $$('.step').forEach(function (s, i) { if (s.classList.contains('active') || s.classList.contains('done')) cur = i + 1; });
      if (cur < 5) setStep(cur + 1);
    }, 600);

    var body = {
      message: text,
      session_id: state.sessionId,
      difficulty: state.difficulty,
      style: state.style,
      project_name: state.projectName || null,
      use_llm: state.forceOffline ? false : null
    };

    try {
      var d = await api('/api/chat', { method: 'POST', body: body });
      clearInterval(stepTimer);
      removeTyping();

      state.sessionId = d.session_id;
      if (d.result) {
        allStepsDone();
        renderResult(d.result);
      } else {
        resetSteps();
      }

      addMessage('assistant', d.reply || '已处理。');
      renderSuggestions(d.suggestions);
      handleActions(d.actions);
      $('#hintText').textContent = d.has_design ? '可继续输入修改指令，或描述新电路' : '输入需求后回车发送';
      toast(d.result ? (d.intent === 'revise' ? '电路已更新' : '电路生成完成') : '已响应');
    } catch (err) {
      clearInterval(stepTimer);
      removeTyping();
      resetSteps();
      addMessage('assistant', '出错了：' + err.message);
      $('#hintText').textContent = '请重试';
      toast('请求失败：' + err.message, true);
    } finally {
      state.generating = false;
      $('#sendBtn').disabled = false;
      $('#chatInput').focus();
    }
  }

  function handleActions(actions) {
    (actions || []).forEach(function (a) {
      switch (a.type) {
        case 'tab': switchTab(a.value); break;
        case 'settings': openDrawer('settingsDrawer'); break;
        case 'download': if (state.result) window.location.href = $('#btnDownload').href; break;
        case 'render': if (state.design) rerender(); break;
        case 'template': applyTemplate(a.value); break;
        default: break;
      }
    });
  }

  /* --------------------------------------------------------- 模板 / 重绘 */
  async function applyTemplate(id) {
    if (state.generating) return;
    toast('正在套用模板…');
    try {
      var d = await api('/api/template', {
        method: 'POST',
        body: { template_id: id, style: state.style, difficulty: state.difficulty }
      });
      state.sessionId = d.session.id;
      renderResult(d.result);
      addMessage('user', '套用模板：' + id);
      addMessage('assistant', '已套用模板「' + (d.result.design.title || id) + '」，右侧已生成完整工程与报告。');
      $('#resultPanel').hidden = false;
    } catch (e) { toast('套用模板失败：' + e.message, true); }
  }

  async function rerender() {
    if (!state.design) return;
    try {
      var d = await api('/api/render', { method: 'POST', body: { design: state.design, style: state.style } });
      playSvgAnimation(d.svg);
    } catch (e) { toast('重绘失败：' + e.message, true); }
  }

  function syncStyleUI(style) {
    $$('#styleGroup .style-opt').forEach(function (b) { b.classList.toggle('active', b.dataset.style === style); });
    $$('#stageStyles .mini-swatch').forEach(function (b) { b.classList.toggle('active', b.dataset.style === style); });
  }

  /* ------------------------------------------------------------- 抽屉 */
  function openDrawer(id) {
    $('#overlay').hidden = false;
    $('#' + id).hidden = false;
    if (id === 'historyDrawer') loadHistory();
    if (id === 'settingsDrawer') loadSettings();
  }
  function closeDrawers() {
    $('#overlay').hidden = true;
    $$('.drawer').forEach(function (d) { d.hidden = true; });
  }

  async function loadHistory() {
    var list = $('#historyList');
    list.innerHTML = '<div class="empty-drawer">加载中…</div>';
    try {
      var d = await api('/api/history');
      list.innerHTML = '';
      if (!d.sessions.length) { list.innerHTML = '<div class="empty-drawer">暂无历史会话</div>'; return; }
      d.sessions.forEach(function (s) {
        var item = document.createElement('div');
        item.className = 'history-item' + (s.id === state.sessionId ? ' active' : '');
        var body = document.createElement('div'); body.className = 'hi-body';
        var title = document.createElement('span'); title.className = 'hi-title'; title.textContent = s.title;
        var meta = document.createElement('div'); meta.className = 'hi-meta';
        meta.textContent = new Date(s.updated_at * 1000).toLocaleString('zh-CN') + ' · ' + s.turns + ' 条消息' + (s.has_design ? ' · ' + (s.design_title || '有设计') : '');
        body.appendChild(title); body.appendChild(meta);
        var del = document.createElement('button'); del.className = 'hi-del'; del.textContent = '✕'; del.title = '删除会话';
        del.onclick = async function (ev) {
          ev.stopPropagation();
          try { await api('/api/history/' + s.id, { method: 'DELETE' }); loadHistory(); toast('会话已删除'); }
          catch (e) { toast('删除失败：' + e.message, true); }
        };
        item.appendChild(body); item.appendChild(del);
        item.onclick = function () { activateSession(s.id); };
        list.appendChild(item);
      });
    } catch (e) { list.innerHTML = '<div class="empty-drawer">加载失败：' + esc(e.message) + '</div>'; }
  }

  async function activateSession(id) {
    try {
      var d = await api('/api/history/activate', { method: 'POST', body: { session_id: id } });
      state.sessionId = id;
      clearMessages();
      (d.session.turns || []).forEach(function (t) { addMessage(t.role, t.text, { actions: false }); });
      if (d.result) {
        renderResult(d.result);
        $('#resultPanel').hidden = false;
      } else {
        $('#resultPanel').hidden = true;
        state.design = null; state.result = null;
        $('#stageSvg').hidden = true;
        $('#stageEmpty').hidden = false;
      }
      closeDrawers();
      toast('已切换到该会话');
    } catch (e) { toast('切换失败：' + e.message, true); }
  }

  async function loadSettings() {
    try {
      var s = await api('/api/settings');
      $('#setBaseUrl').value = s.base_url || '';
      $('#setModel').value = s.model || '';
      $('#setTimeout').value = s.timeout || 60;
      $('#setNoFree').checked = !!s.no_free_llm;
      $('#setAutoPreview').checked = s.auto_preview !== false;
      state.autoPreview = s.auto_preview !== false;
      $('#setDarkTheme').checked = state.theme === 'dark';
      $('#pathOutput').textContent = s.output_dir || '—';
      $('#pathData').textContent = s.data_dir || '—';
      $('#pathMode').textContent = (s.frozen ? '桌面打包运行' : '源码运行') + ' · v' + s.version;
      $('#settingsNote').textContent = s.api_key_set
        ? '当前已配置 API Key（留空表示保持不变）。密钥仅保存在内存中，重启后需重新填写。'
        : '未配置 API Key，将使用免费在线 LLM；网络不可用时自动降级到离线模板。';
    } catch (e) { toast('读取设置失败：' + e.message, true); }
  }

  async function saveSettings() {
    var payload = {
      base_url: $('#setBaseUrl').value.trim(),
      model: $('#setModel').value.trim(),
      timeout: Number($('#setTimeout').value) || 60,
      no_free_llm: $('#setNoFree').checked,
      auto_preview: $('#setAutoPreview').checked,
      theme: $('#setDarkTheme').checked ? 'dark' : 'light'
    };
    var key = $('#setApiKey').value.trim();
    if (key) payload.api_key = key;
    try {
      await api('/api/settings', { method: 'POST', body: payload });
      state.autoPreview = payload.auto_preview;
      applyTheme(payload.theme);
      $('#setApiKey').value = '';
      $('#settingsNote').textContent = '设置已保存并立即生效。';
      loadStatus();
      toast('设置已保存');
    } catch (e) { toast('保存失败：' + e.message, true); }
  }

  function applyTheme(t) {
    state.theme = t || 'light';
    document.documentElement.setAttribute('data-theme', state.theme);
    localStorage.setItem('eda-theme', state.theme);
    var cb = $('#setDarkTheme'); if (cb) cb.checked = state.theme === 'dark';
  }

  /* ------------------------------------------------------------- 能力 / 帮助 */
  function renderQuick() {
    var caps = state.capabilities;
    if (!caps) return;
    var cmds = caps.quick_commands || [];
    var groups = [];
    cmds.forEach(function (c) { if (groups.indexOf(c.group) < 0) groups.push(c.group); });
    if (!state.quickGroup || groups.indexOf(state.quickGroup) < 0) state.quickGroup = groups[0] || '';
    var tabs = $('#quickTabs'); tabs.innerHTML = '';
    groups.forEach(function (g) {
      var b = document.createElement('button');
      b.className = 'quick-tab' + (g === state.quickGroup ? ' active' : '');
      b.textContent = g;
      b.onclick = function () { state.quickGroup = g; renderQuick(); };
      tabs.appendChild(b);
    });
    var list = $('#quickList'); list.innerHTML = '';
    cmds.filter(function (c) { return c.group === state.quickGroup; }).forEach(function (c) {
      var b = document.createElement('button');
      b.className = 'quick-chip';
      var icon = document.createElement('span'); icon.className = 'qc-icon';
      icon.textContent = c.icon === 'edit' ? '✎' : c.icon === 'help' ? '?' : '⚡';
      b.appendChild(icon);
      b.appendChild(document.createTextNode(c.label));
      b.title = c.text;
      b.onclick = function () { sendMessage(c.text); };
      list.appendChild(b);
    });
  }

  function renderTemplates() {
    var list = $('#templateList'); list.innerHTML = '';
    state.templates.forEach(function (t) {
      var card = document.createElement('button');
      card.className = 'template-card';
      card.innerHTML =
        '<span class="tc-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M8 8h8M8 12h8M8 16h4"/></svg></span>' +
        '<span class="tc-body"><span class="tc-name">' + esc(t.name) + '</span>' +
        '<span class="tc-desc">' + esc(t.description) + '</span>' +
        '<span class="tc-meta">' + t.components + ' 元件 · ' + t.nets + ' 网络</span></span>';
      card.onclick = function () { applyTemplate(t.id); };
      list.appendChild(card);
    });
  }

  function renderHelp() {
    var c = state.capabilities;
    if (!c) { $('#helpBody').innerHTML = '<div class="empty-drawer">加载中…</div>'; return; }
    var h = '<div class="help-block">';
    h += '<h3>助手简介</h3><p>' + esc(c.profile.description) + '</p>';
    h += '<h3>核心能力（' + c.capabilities.length + ' 项）</h3><div class="cap-grid">';
    c.capabilities.forEach(function (x, i) {
      h += '<div class="cap-item"><span class="cap-idx">' + (i + 1) + '</span><div><b>' + esc(x.title) + '</b><span>' + esc(x.desc) + '</span></div></div>';
    });
    h += '</div>';
    h += '<h3>工作流程</h3><ol>';
    c.workflow.forEach(function (x) { h += '<li>' + esc(x) + '</li>'; });
    h += '</ol>';
    h += '<h3>可识别的意图</h3><div class="intent-tags">';
    (c.intents || []).forEach(function (x) { h += '<span class="intent-tag">' + esc(x.label) + '</span>'; });
    h += '</div>';
    h += '<h3>术语词典</h3>';
    (c.keyword_groups || []).forEach(function (g) {
      h += '<p><b>' + esc(g.category) + '</b>：' + esc((g.terms || []).join('、')) + '</p>';
    });
    h += '<h3>使用小贴士</h3><ul>';
    (c.tips || []).forEach(function (x) { h += '<li>' + esc(x) + '</li>'; });
    h += '</ul>';
    h += '<h3>关于</h3><p>EDA Agent v' + esc(c.profile.version) + ' · 本地 NLU + LLM 双引擎 · 支持桌面安装与完全离线运行。</p>';
    h += '</div>';
    $('#helpBody').innerHTML = h;
  }

  /* ------------------------------------------------------------- 状态栏 */
  async function loadStatus() {
    try {
      var s = await api('/api/status');
      var c = $('#chipLlm');
      c.className = 'chip';
      if (s.llm_mode === 'custom') { c.classList.add('ok'); c.querySelector('.chip-txt').textContent = 'LLM · ' + (s.llm_model || '自定义'); }
      else if (s.llm_mode === 'free') { c.classList.add('ok'); c.querySelector('.chip-txt').textContent = '免费在线 LLM'; }
      else { c.classList.add('warn'); c.querySelector('.chip-txt').textContent = '离线模板模式'; }
      $('#verBadge').textContent = 'v' + (s.version || '2.0');
      var kn = $('#chipNlu');
      if (kn) { kn.classList.add('ok'); kn.querySelector('.chip-txt').textContent = 'NLU · 本地引擎'; }
      var kc = $('#chipKicad');
      if (kc) kc.querySelector('.chip-txt').textContent = s.kicad_cli && s.kicad_cli.indexOf('未探测') === 0 ? 'KiCad 导出就绪' : 'KiCad 已就绪';
    } catch (e) {
      var c2 = $('#chipLlm'); c2.classList.add('warn'); c2.querySelector('.chip-txt').textContent = '服务连接失败';
    }
  }

  /* ------------------------------------------------------------- 结果工具 */
  async function exportKind(kind) {
    if (!state.design) { toast('请先生成电路', true); return; }
    try {
      var d = await api('/api/export', {
        method: 'POST',
        body: {
          design: state.design, kind: kind,
          requirement: state.lastUserText || '', mode: (state.result && state.result.mode) || 'template'
        }
      });
      downloadBlob(d.content, d.filename, d.mime);
      toast('已导出 ' + d.filename);
    } catch (e) { toast('导出失败：' + e.message, true); }
  }

  async function openKicad() {
    if (!state.result) { toast('请先生成电路', true); return; }
    try {
      var d = await api('/api/open-kicad', { method: 'POST', body: { zip_path: state.result.download_zip } });
      if (d && d.ok) toast('已在 KiCad 中打开工程');
    } catch (e) { toast(e.message || '未检测到本机 KiCad，请下载工程包后手动打开', true); }
  }

  async function applyJson() {
    try {
      var design = JSON.parse($('#jsonEditor').value);
      var d = await api('/api/design-from-json', {
        method: 'POST',
        body: { design: design, style: state.style, difficulty: state.difficulty }
      });
      state.sessionId = d.session.id;
      renderResult(d.result);
      toast('设计 JSON 已应用，工程与原理图已重新生成');
    } catch (e) { toast('JSON 无效：' + e.message, true); }
  }

  function printPanel() {
    var active = $$('.panel.active')[0];
    if (!active) { toast('暂无可打印内容', true); return; }
    var w = window.open('', '_blank');
    if (!w) { toast('请允许弹出窗口以打印', true); return; }
    var css = 'body{font-family:"Segoe UI","Microsoft YaHei",sans-serif;padding:32px;color:#171C19;line-height:1.7}' +
      'h1,h2,h3{color:#0E7A46}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ddd;padding:8px}' +
      'code{background:#f2f4f3;padding:2px 5px;border-radius:4px}blockquote{border-left:3px solid #0E7A46;padding-left:12px}';
    w.document.write('<html><head><title>EDA Agent 报告</title><style>' + css + '</style></head><body>' + active.innerHTML + '</body></html>');
    w.document.close();
    setTimeout(function () { w.print(); }, 300);
  }

  /* ------------------------------------------------------------- 新建 / 清空 */
  async function newSession(silent) {
    try {
      var d = await api('/api/session/new', { method: 'POST', body: {} });
      state.sessionId = d.session_id;
      state.design = null; state.result = null; state.svgText = '';
      clearMessages();
      addMessage('assistant', d.greeting || '已开启新会话。');
      $('#resultPanel').hidden = true;
      $('#stageSvg').innerHTML = ''; $('#stageSvg').hidden = true;
      $('#stageEmpty').hidden = false;
      $('#stageBadge').hidden = true;
      $('#suggestionRow').innerHTML = '';
      hideInsight(); resetSteps();
      if (!silent) toast('已新建会话');
    } catch (e) { toast('新建会话失败：' + e.message, true); }
  }

  /* ------------------------------------------------------------- 事件绑定 */
  function bind() {
    // 顶栏
    $('#btnNew').onclick = function () { newSession(false); };
    $('#btnHistory').onclick = function () { openDrawer('historyDrawer'); };
    $('#btnSettings').onclick = function () { openDrawer('settingsDrawer'); };
    $('#btnHelp').onclick = function () { renderHelp(); openDrawer('helpDrawer'); };
    $('#btnTheme').onclick = function () { applyTheme(state.theme === 'dark' ? 'light' : 'dark'); };

    // 抽屉关闭
    $('#overlay').onclick = closeDrawers;
    $$('[data-close-drawer]').forEach(function (b) { b.onclick = closeDrawers; });
    $('#btnClearHistory').onclick = async function () {
      try { await api('/api/history', { method: 'DELETE' }); state.sessionId = null; await newSession(true); loadHistory(); toast('历史会话已清空'); }
      catch (e) { toast('清空失败：' + e.message, true); }
    };

    // 折叠面板
    $('#quickToggle').onclick = function () {
      var l = $('#quickList'), t = $('#quickTabs');
      var hide = !l.hidden;
      l.hidden = hide; t.hidden = hide;
      this.textContent = hide ? '展开' : '收起';
    };
    $('#paramToggle').onclick = function () {
      var b = $('#paramBody'); b.hidden = !b.hidden;
      this.textContent = b.hidden ? '展开' : '收起';
    };

    // 难度 / 风格 / 参数
    $$('#difficultyGroup .seg').forEach(function (b) {
      b.onclick = function () {
        $$('#difficultyGroup .seg').forEach(function (x) { x.classList.remove('active'); });
        b.classList.add('active'); state.difficulty = b.dataset.difficulty;
      };
    });
    $$('#styleGroup .style-opt').forEach(function (b) {
      b.onclick = function () { state.style = b.dataset.style; syncStyleUI(state.style); if (state.design) rerender(); };
    });
    $$('#stageStyles .mini-swatch').forEach(function (b) {
      b.onclick = function () { state.style = b.dataset.style; syncStyleUI(state.style); if (state.design) rerender(); };
    });
    $('#projectName').oninput = function () { state.projectName = this.value.trim(); };
    $('#forceOffline').onchange = function () { state.forceOffline = this.checked; toast(state.forceOffline ? '已切换为纯离线模板' : '已恢复自动模式'); };

    // 输入
    $('#sendBtn').onclick = function () { sendMessage($('#chatInput').value); };
    $('#chatInput').oninput = onInputChange;
    $('#chatInput').onkeydown = function (e) {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(this.value); }
    };
    $('#btnClearChat').onclick = function () { newSession(false); };
    $('#btnExportChat').onclick = function () {
      if (!state.messages.length) { toast('暂无对话可导出', true); return; }
      var md = '# EDA Agent 对话记录\n\n' + state.messages.map(function (m) {
        return '**' + (m.role === 'user' ? '我' : 'W') + '**：\n\n' + m.text;
      }).join('\n\n---\n\n');
      downloadBlob(md, 'EDA-Agent-对话记录.md', 'text/markdown');
      toast('对话已导出');
    };

    // 标签页
    $$('.tab').forEach(function (t) { t.onclick = function () { switchTab(t.dataset.tab); }; });

    // 舞台
    $('#zoomIn').onclick = function () { setZoom(state.zoom + 0.15); };
    $('#zoomOut').onclick = function () { setZoom(state.zoom - 0.15); };
    $('#zoomFit').onclick = resetView;
    $('#replayBtn').onclick = function () { if (state.svgText) playSvgAnimation(state.svgText); };
    $('#btnDownloadSvg').onclick = function () {
      if (!state.svgText) { toast('请先生成电路', true); return; }
      downloadBlob(state.svgText, 'EDA-Agent-原理图.svg', 'image/svg+xml');
      toast('SVG 已下载');
    };
    $('#btnFullscreen').onclick = function () {
      var el = $('#schematicStage');
      if (document.fullscreenElement) document.exitFullscreen();
      else if (el.requestFullscreen) el.requestFullscreen();
      else toast('当前环境不支持全屏', true);
    };
    var vp = $('#stageViewport');
    vp.addEventListener('wheel', function (e) {
      if (!state.svgText) return;
      e.preventDefault();
      setZoom(state.zoom + (e.deltaY < 0 ? 0.1 : -0.1));
    }, { passive: false });
    var dragging = false, sx = 0, sy = 0, ox = 0, oy = 0;
    vp.addEventListener('mousedown', function (e) {
      if (!state.svgText || e.button !== 0) return;
      dragging = true; sx = e.clientX; sy = e.clientY; ox = state.panX; oy = state.panY;
      vp.classList.add('dragging');
    });
    window.addEventListener('mousemove', function (e) {
      if (!dragging) return;
      state.panX = ox + (e.clientX - sx); state.panY = oy + (e.clientY - sy);
      applyTransform();
    });
    window.addEventListener('mouseup', function () { dragging = false; vp.classList.remove('dragging'); });

    // 结果工具条
    $$('#resultToolbar [data-export]').forEach(function (b) {
      b.onclick = function () { exportKind(b.dataset.export); };
    });
    $('#btnCopyMd').onclick = function () {
      if (!state.result) { toast('请先生成电路', true); return; }
      copyText(state.result.bom_md || '');
    };
    $('#btnOpenFolder').onclick = async function () {
      try {
        var d = await api('/api/open-folder', { method: 'POST', body: { path: state.result ? state.result.output_dir : '' } });
        toast('已打开：' + d.path);
      } catch (e) { toast('打开目录失败：' + e.message, true); }
    };
    $('#btnPrint').onclick = printPanel;
    $('#btnOpenKicad').onclick = openKicad;
    $('#btnFormatJson').onclick = function () {
      try { $('#jsonEditor').value = JSON.stringify(JSON.parse($('#jsonEditor').value), null, 2); toast('已格式化'); }
      catch (e) { toast('JSON 无效：' + e.message, true); }
    };
    $('#btnApplyJson').onclick = applyJson;

    // 设置
    $('#btnSaveSettings').onclick = saveSettings;
    $('#setAutoPreview').onchange = function () { state.autoPreview = this.checked; };
    $('#setDarkTheme').onchange = function () { applyTheme(this.checked ? 'dark' : 'light'); };

    // 键盘快捷键
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') { closeDrawers(); return; }
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); $('#chatInput').focus(); }
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'n') { e.preventDefault(); newSession(false); }
    });
  }

  /* ------------------------------------------------------------- 启动 */
  async function init() {
    applyTheme(state.theme);
    bind();
    loadStatus();

    try {
      var caps = await api('/api/capabilities');
      state.capabilities = caps;
      state.templates = caps.templates || [];
      renderQuick();
      renderTemplates();
      renderHelp();
      addMessage('assistant', caps.greeting || '你好，我是 W，你的电路设计助手。', { actions: false });
      renderSuggestions(['做一个 5V 转 3.3V 的 LDO 稳压电路', '设计一个 LED 闪烁最小系统', '查看帮助']);
    } catch (e) {
      addMessage('assistant', '服务连接失败：' + e.message, { actions: false });
      toast('无法连接本地服务', true);
    }

    // 桌面端体验：自动恢复上一次的设计会话
    try {
      var h = await api('/api/history');
      var last = h.current_id ? h.sessions.filter(function (s) { return s.id === h.current_id && s.has_design; })[0] : null;
      if (last) {
        var d = await api('/api/history/activate', { method: 'POST', body: { session_id: last.id } });
        state.sessionId = last.id;
        clearMessages();
        (d.session.turns || []).slice(-12).forEach(function (t) { addMessage(t.role, t.text, { actions: false }); });
        if (d.result) { renderResult(d.result); $('#resultPanel').hidden = false; }
        toast('已恢复上次的设计会话');
      }
    } catch (e) { /* 恢复失败不影响使用 */ }

    $('#chatInput').focus();
  }

  document.addEventListener('DOMContentLoaded', init);
})();
