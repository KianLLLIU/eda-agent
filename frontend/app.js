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
    templateCats: [],
    templateCat: '全部',
    quickGroup: '',
    svgText: '',
    zoom: 1,
    panX: 0,
    panY: 0,
    theme: localStorage.getItem('eda-theme') || 'light',
    autoPreview: true,
    kicad: null,
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
    // v2.3：显示 Freerouting 自动布线状态
    var badge = $('#routeBadge');
    if (badge) {
      var rt = data.routing;
      if (rt && rt.ok) {
        var rs = rt.stats || {};
        badge.textContent = '✓ Freerouting 已自动布线 · ' + (rs.segments || 0) + ' 段走线'
          + (rs.vias ? ' · ' + rs.vias + ' 过孔' : '');
        badge.className = 'route-badge ok';
        badge.hidden = false;
      } else if (rt && !rt.skipped) {
        badge.textContent = '○ 已摆件，布线未完成（可设 EDA_AI_AUTOROUTE 或手动布）';
        badge.className = 'route-badge warn';
        badge.hidden = false;
      } else {
        badge.hidden = true;
      }
    }
    // v2.4：自检 / 通电模拟徽标
    var cb = $('#checkBadge');
    if (cb) {
      var sc = data.selfcheck;
      if (sc && sc.summary && sc.summary.indexOf('未执行') < 0) {
        cb.textContent = (sc.ok ? '✓ ' : '⚠ ') + '自检 ' + (sc.score || 0)
          + ' 分 · ' + (sc.error_count || 0) + ' 错误 / ' + (sc.warning_count || 0)
          + ' 警告 · ' + (sc.power_on && sc.power_on.ok ? '通电模拟正常' : '通电模拟异常');
        cb.className = 'check-badge ' + (sc.ok ? 'ok' : 'warn');
        cb.hidden = false;
        cb.onclick = function () {
          $$('#tabs .tab').forEach(function (t) { t.classList.toggle('active', t.dataset.tab === 'selfcheck'); });
          $$('.tab-panels .panel').forEach(function (p) { p.classList.remove('active'); });
          var sp = $('#panel-selfcheck'); if (sp) sp.classList.add('active');
        };
      } else {
        cb.hidden = true;
      }
    }

    ['bom', 'netlist', 'report', 'guide', 'hardware', 'selfcheck'].forEach(function (k) {
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
        var vb = $('#btnVersion');
        if (vb) { vb.hidden = false; vb.textContent = 'v' + (d.result.iteration || 1) + ' 历史'; }
      } else {
        resetSteps();
      }
      // v2.5 需求理解卡：把跨轮累积的需求展示给用户
      if (d.analysis && d.analysis.requirement) renderRequirement(d.analysis.requirement);

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
        case 'library': openDrawer('libraryDrawer'); break;
        case 'archive': archiveCurrent(); break;
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
    if (id === 'settingsDrawer') { loadSettings(); loadKicad(false); }
    if (id === 'modelDrawer') loadModelConfig();
    if (id === 'libraryDrawer') loadLibrary(false);
    if (id === 'versionDrawer') loadVersions();
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
      $('#setKicadPath').value = s.kicad_path || '';
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

  /* --------------------------------------------- v2.4 大模型 API 配置 */
  function escapeHtml(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  async function loadModelConfig() {
    try {
      var s = await api('/api/settings');
      if (!$('#mdlBaseUrl').value) $('#mdlBaseUrl').value = s.base_url || '';
      if (!$('#mdlModel').value) $('#mdlModel').value = s.model || '';
      $('#mdlTimeout').value = s.timeout || 90;
      $('#mdlNoFree').checked = !!s.no_free_llm;
      $('#mdlCurBase').textContent = s.base_url || '—';
      $('#mdlCurModel').textContent = s.model || '—';
      $('#mdlCurKey').textContent = s.api_key_set ? '已配置（仅内存）' : '未配置';
      $('#mdlCurMode').textContent = s.llm_mode || (s.api_key_set ? '自定义 Key' : '免费在线');
      // 高亮匹配的预设
      $$('#modelPresets .preset-card').forEach(function (b) {
        b.classList.toggle('active', b.dataset.base === s.base_url);
      });
    } catch (e) { toast('读取模型配置失败：' + e.message, true); }
  }

  function showModelResult(html, ok) {
    var el = $('#modelResult');
    el.innerHTML = html;
    el.className = 'model-result ' + (ok ? 'ok' : 'err');
    el.hidden = false;
  }

  function collectModelPayload(includeKey) {
    var p = {
      base_url: $('#mdlBaseUrl').value.trim(),
      model: $('#mdlModel').value.trim(),
      timeout: Number($('#mdlTimeout').value) || 90,
      no_free_llm: $('#mdlNoFree').checked
    };
    if (includeKey) {
      var key = $('#mdlApiKey').value.trim();
      if (key) p.api_key = key;
    }
    return p;
  }

  async function testLlm() {
    var payload = collectModelPayload(true);
    if (!payload.base_url || !payload.model) {
      showModelResult('请先填写接口地址和模型 ID', false); return;
    }
    showModelResult('正在连接…', true);
    $('#btnTestLlm').disabled = true;
    try {
      var d = await api('/api/settings/test-llm', { method: 'POST', body: payload });
      if (d.ok) {
        showModelResult('✓ 连接成功 · ' + (d.latency_ms || 0) + 'ms · 模型回复：'
          + escapeHtml(d.reply || '(空)'), true);
      } else {
        showModelResult('✗ 连接失败（HTTP ' + (d.status || '-') + '，'
          + (d.latency_ms || 0) + 'ms）：' + escapeHtml(d.error || ''), false);
      }
    } catch (e) {
      showModelResult('✗ 测试失败：' + escapeHtml(e.message), false);
    } finally {
      $('#btnTestLlm').disabled = false;
    }
  }

  async function saveModelConfig() {
    var payload = collectModelPayload(true);
    if (!payload.base_url || !payload.model) {
      showModelResult('请先填写接口地址和模型 ID', false); return;
    }
    try {
      await api('/api/settings', { method: 'POST', body: payload });
      $('#mdlApiKey').value = '';
      showModelResult('✓ 已保存并立即生效，当前所有新对话都会使用该模型。', true);
      loadSettings(); loadStatus(); loadModelConfig();
      toast('大模型配置已更新');
    } catch (e) {
      showModelResult('✗ 保存失败：' + escapeHtml(e.message), false);
    }
  }

  /* ============================================================= v2.5 新能力 */

  /* ---------- 跨轮需求理解卡 ---------- */
  function renderRequirement(req) {
    if (!req) return;
    var card = $('#requirementCard');
    card.hidden = false;
    var score = req.completeness || 0;
    $('#reqScore').textContent = score + '%';
    $('#reqFill').style.width = score + '%';
    $('#reqFill').className = 'req-fill' + (score >= 80 ? ' ready' : '');
    $('#reqSummary').textContent = req.summary || '';
    var miss = $('#reqMissing');
    if (req.missing && req.missing.length) {
      miss.hidden = false;
      miss.textContent = '还差：' + req.missing.slice(0, 3).join('、');
    } else { miss.hidden = true; }
    $('#reqFoot').textContent = req.hint || '';
  }
  function hideRequirement() { $('#requirementCard').hidden = true; }

  /* ---------- 语音输入（Web Speech API，桌面 WebView2 / Chrome 可用） ---------- */
  function initVoice() {
    var SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    var btn = $('#btnVoice');
    if (!SR) {
      btn.hidden = true;  // 不支持则隐藏，不影响其它功能
      return;
    }
    var rec = new SR();
    rec.lang = 'zh-CN';
    rec.continuous = false;
    rec.interimResults = true;
    rec.maxAlternatives = 1;
    state.voiceRec = rec;
    state.voiceOn = false;

    rec.onresult = function (e) {
      var finalText = '', interim = '';
      for (var i = e.resultIndex; i < e.results.length; i++) {
        var seg = e.results[i][0].transcript;
        if (e.results[i].isFinal) finalText += seg; else interim += seg;
      }
      var input = $('#chatInput');
      if (interim) input.value = (state.voiceBase || '') + interim;
      if (finalText) {
        input.value = (input.value || (state.voiceBase || '') + finalText).trim();
        onInputChange();
        // 说话结束自动发送，减少一次点击；用户可在识别中再次点按钮停止
        setTimeout(function () { if (input.value.trim()) sendMessage(input.value); }, 200);
      }
    };
    rec.onerror = function (e) {
      stopVoice();
      toast(e.error === 'not-allowed' ? '麦克风权限被拒绝，请在浏览器设置里允许'
        : ('语音识别失败：' + e.error), true);
    };
    rec.onend = function () { stopVoice(); };

    btn.onclick = function () {
      if (state.voiceOn) { stopVoice(); return; }
      try {
        state.voiceBase = $('#chatInput').value ? $('#chatInput').value.trim() + ' ' : '';
        rec.start();
        state.voiceOn = true;
        btn.classList.add('listening');
        btn.title = '点击停止录音';
        $('#hintText').textContent = '正在听… 说完自动发送';
      } catch (e) { toast('无法启动语音识别：' + e.message, true); }
    };
  }
  function stopVoice() {
    if (state.voiceRec) { try { state.voiceRec.stop(); } catch (e) { /* ignore */ } }
    state.voiceOn = false;
    var btn = $('#btnVoice');
    if (btn) { btn.classList.remove('listening'); btn.title = '点击说话（语音输入）'; }
  }

  /* ---------- 离线板子库 ---------- */
  var libState = { items: [], category: '', editing: null };

  async function loadLibrary(keepSearch) {
    var q = keepSearch ? ($('#libSearch').value || '').trim() : '';
    var listEl = $('#libList');
    listEl.innerHTML = '<div class="empty-drawer">加载中…</div>';
    try {
      var d;
      if (q) { d = await api('/api/library/search?q=' + encodeURIComponent(q) + '&top_k=40'); }
      else {
        d = await api('/api/library' + (libState.category ? '?category=' + encodeURIComponent(libState.category) : ''));
      }
      libState.items = d.items || [];
      renderLibStats(d.stats);
      renderLibFilters();
      renderLibList();
    } catch (e) { listEl.innerHTML = '<div class="empty-drawer">加载失败：' + esc(e.message) + '</div>'; }
  }

  function renderLibStats(stats) {
    if (!stats) return;
    $('#libStats').innerHTML =
      '<span>共 <b>' + stats.total + '</b> 块</span>' +
      '<span>内置 <b>' + stats.builtin + '</b></span>' +
      '<span>我的 <b>' + stats.user + '</b></span>';
  }

  function renderLibFilters() {
    var f = $('#libFilters'); f.innerHTML = '';
    var cats = ['', '电源', 'LED 灯光', '传感器', '驱动', '接口', '其他'];
    cats.forEach(function (c) {
      var b = document.createElement('button');
      b.className = 'lib-filter' + (libState.category === c ? ' active' : '');
      b.textContent = c || '全部';
      b.onclick = function () { libState.category = c; $('#libSearch').value = ''; loadLibrary(false); };
      f.appendChild(b);
    });
  }

  function renderLibList() {
    var el = $('#libList');
    if (!libState.items.length) { el.innerHTML = '<div class="empty-drawer">没有匹配的板子</div>'; return; }
    el.innerHTML = '';
    libState.items.forEach(function (it) {
      var card = document.createElement('div');
      card.className = 'lib-card';
      var isBuiltin = it.source === 'builtin';
      var tags = (it.tags || []).slice(0, 5).map(function (t) { return '<span class="lib-tag">' + esc(t) + '</span>'; }).join('');
      card.innerHTML =
        '<div class="lib-card-head">' +
          '<span class="lib-name">' + esc(it.name || it.title || '未命名') + '</span>' +
          '<span class="lib-badge ' + (isBuiltin ? 'b' : 'u') + '">' + (isBuiltin ? '内置' : '我的') + '</span>' +
        '</div>' +
        '<div class="lib-desc">' + esc(it.description || '（无描述）') + '</div>' +
        '<div class="lib-meta">' + esc(it.category || '其他') +
          ' · ' + (it.component_count != null ? it.component_count : '—') + ' 元件' +
          ' · ' + (it.net_count != null ? it.net_count : '—') + ' 网络' +
          ' · 调用 ' + (it.use_count || 0) + ' 次' + '</div>' +
        '<div class="lib-tags">' + tags + '</div>' +
        '<div class="lib-actions"></div>';
      var act = card.querySelector('.lib-actions');
      var use = document.createElement('button');
      use.className = 'btn-outline'; use.textContent = '调用出图';
      use.onclick = function () { useLibraryItem(it.id); };
      act.appendChild(use);
      if (!isBuiltin) {
        var edit = document.createElement('button');
        edit.className = 'btn-outline'; edit.textContent = '编辑';
        edit.onclick = function () { openLibEditor(it); };
        act.appendChild(edit);
        var del = document.createElement('button');
        del.className = 'btn-danger'; del.textContent = '删除';
        del.onclick = function () { deleteLibraryItem(it); };
        act.appendChild(del);
      }
      el.appendChild(card);
    });
  }

  function openLibEditor(item) {
    libState.editing = item ? item.id : null;
    $('#libEditorTitle').textContent = item ? '编辑板子' : '新增板子';
    $('#libName').value = item ? (item.name || '') : '';
    $('#libDesc').value = item ? (item.description || '') : '';
    $('#libCategory').value = item ? (item.category || '') : '';
    $('#libTags').value = item ? ((item.tags || []).join(', ')) : '';
    $('#libJsonWrap').hidden = !!item;  // 编辑不改 design
    if (!item && state.design) {
      $('#libJson').value = JSON.stringify(state.design, null, 2);
      if (!$('#libName').value) $('#libName').value = state.design.title || '';
    }
    $('#libEditor').hidden = false;
    $('#libEditor').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  async function saveLibraryItem() {
    var name = $('#libName').value.trim();
    if (!name) { toast('请填写名称', true); return; }
    var payload = {
      item_id: libState.editing || undefined,
      name: name,
      description: $('#libDesc').value.trim(),
      category: $('#libCategory').value.trim() || '其他',
      tags: $('#libTags').value.split(/[,，]/).map(function (x) { return x.trim(); }).filter(Boolean)
    };
    try {
      if (libState.editing) {
        await api('/api/library/' + encodeURIComponent(libState.editing),
                  { method: 'PUT', body: payload });
        toast('已保存修改');
      } else {
        var json = $('#libJson').value.trim();
        if (!json) { toast('新增板子必须填设计 JSON', true); return; }
        payload.design = JSON.parse(json);
        await api('/api/library', { method: 'POST', body: payload });
        toast('已新增到离线库');
      }
      $('#libEditor').hidden = true;
      libState.editing = null;
      loadLibrary(false);
    } catch (e) { toast('保存失败：' + e.message, true); }
  }

  async function deleteLibraryItem(it) {
    if (!window.confirm('确定删除「' + (it.name || it.id) + '」？此操作不可恢复。')) return;
    try {
      await api('/api/library/' + encodeURIComponent(it.id), { method: 'DELETE' });
      toast('已删除');
      loadLibrary(false);
    } catch (e) { toast('删除失败：' + e.message, true); }
  }

  async function useLibraryItem(id) {
    if (state.generating) { toast('正在处理上一条请求，请稍候'); return; }
    closeDrawers();
    state.generating = true;
    $('#sendBtn').disabled = true;
    setStageBadge('正在从库调出…');
    try {
      var d = await api('/api/library/use', {
        method: 'POST',
        body: { item_id: id, style: state.style, difficulty: state.difficulty }
      });
      state.sessionId = d.session_id;
      state.design = d.result.design;
      state.result = d.result;
      allStepsDone();
      renderResult(d.result);
      addMessage('user', '调用离线库：' + (d.item.name || id));
      addMessage('assistant', '已从离线库调出「' + (d.item.name || id) + '」并生成工程。');
      toast('已从库调出并生成');
    } catch (e) { toast('调用失败：' + e.message, true); }
    finally { state.generating = false; $('#sendBtn').disabled = false; }
  }

  async function archiveCurrent() {
    if (!state.design) { toast('当前没有可归档的设计', true); return; }
    try {
      var d = await api('/api/library/archive-current', { method: 'POST', body: {} });
      toast('已归档到离线库：' + (d.item.name || d.item.id));
    } catch (e) { toast('归档失败：' + e.message, true); }
  }

  /* ---------- 版本历史 ---------- */
  async function loadVersions() {
    var el = $('#versionList');
    el.innerHTML = '<div class="empty-drawer">加载中…</div>';
    try {
      var d = await api('/api/versions?session_id=' + encodeURIComponent(state.sessionId || ''));
      if (!d.versions.length) { el.innerHTML = '<div class="empty-drawer">还没有版本快照</div>'; return; }
      el.innerHTML = '';
      d.versions.slice().reverse().forEach(function (v) {
        var row = document.createElement('div');
        row.className = 'version-row';
        row.innerHTML =
          '<div class="version-info"><b>v' + v.v + '</b> ' + esc(v.label) +
            '<div class="version-sub">' + v.components + ' 元件 · ' +
            new Date(v.ts * 1000).toLocaleString('zh-CN') + '</div>' +
            (v.changes && v.changes.length ? '<div class="version-changes">' +
              esc(v.changes.slice(0, 2).join('；')) + '</div>' : '') + '</div>';
        var btn = document.createElement('button');
        btn.className = 'btn-outline'; btn.textContent = '恢复';
        btn.onclick = function () { rollbackVersion(v.v); };
        row.appendChild(btn);
        el.appendChild(row);
      });
    } catch (e) { el.innerHTML = '<div class="empty-drawer">加载失败：' + esc(e.message) + '</div>'; }
  }

  async function rollbackVersion(v) {
    if (!window.confirm('确定回退到 v' + v + '？当前工程会被覆盖（可再回退到其它版本）。')) return;
    closeDrawers();
    try {
      var d = await api('/api/version/rollback', {
        method: 'POST', body: { version: v, session_id: state.sessionId }
      });
      state.result = d.result;
      state.design = d.result.design;
      renderResult(d.result);
      toast('已回退到 v' + v);
    } catch (e) { toast('回退失败：' + e.message, true); }
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
    // 分类筛选
    var tabs = $('#templateTabs');
    if (tabs) {
      tabs.innerHTML = '';
      var cats = [{ name: '全部', count: state.templates.length }].concat(state.templateCats || []);
      cats.forEach(function (c) {
        var b = document.createElement('button');
        b.className = 'tpl-tab' + (state.templateCat === c.name ? ' active' : '');
        b.textContent = c.name + ' ' + c.count;
        b.onclick = function () { state.templateCat = c.name; renderTemplates(); };
        tabs.appendChild(b);
      });
    }

    var cnt = $('#templateCount');
    var list = $('#templateList');
    list.innerHTML = '';
    var items = state.templates.filter(function (t) {
      return state.templateCat === '全部' || t.category === state.templateCat;
    });
    if (cnt) cnt.textContent = items.length;
    if (!items.length) {
      list.innerHTML = '<div class="empty-drawer">该分类暂无板子</div>';
      return;
    }
    items.forEach(function (t) {
      var card = document.createElement('button');
      card.className = 'template-card';
      card.innerHTML =
        '<span class="tc-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M8 8h8M8 12h8M8 16h4"/></svg></span>' +
        '<span class="tc-body"><span class="tc-name">' + esc(t.name) +
        '<span class="tc-cat">' + esc(t.category || '') + '</span></span>' +
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

  /* --------------------------------------------------------- KiCad 集成 */
  function renderKicadChip(k) {
    var c = $('#chipKicad');
    if (!c) return;
    c.classList.remove('ok', 'warn');
    if (k && k.found) {
      c.classList.add('ok');
      c.querySelector('.chip-txt').textContent = 'KiCad ' + (k.version || '已就绪');
      c.title = '已检测到：' + k.path + '\n来源：' + k.source + '\n点击可查看 / 修改路径';
    } else {
      c.classList.add('warn');
      c.querySelector('.chip-txt').textContent = 'KiCad 未检测到 · 点此设置';
      c.title = (k && k.hint) || '点击设置 KiCad 路径';
    }
  }

  async function loadKicad(force) {
    var st = $('#kicadState');
    if (st) st.textContent = '检测中…';
    try {
      var k = force
        ? await api('/api/kicad/detect', { method: 'POST', body: {} })
        : await api('/api/kicad');
      state.kicad = k;
      renderKicadChip(k);
      if (st) {
        st.className = 'kicad-state ' + (k.found ? 'ok' : 'warn');
        st.innerHTML = k.found
          ? '<b>已检测到 KiCad ' + esc(k.version || '') + '</b><br/><span class="kicad-path">' + esc(k.path || '') +
            '</span><br/><small>来源：' + esc(k.source) + ' · 自动检查 ' + k.checked_count + ' 处</small>'
          : '<b>未检测到 KiCad</b><br/><small>' + esc(k.hint || '') + '</small>';
      }
      var diag = $('#kicadDiag');
      if (diag) {
        var html = '<div class="diag-title">自动探测检查过的位置（' + k.checked_count + '）</div>';
        html += (k.checked || []).slice(0, 20).map(function (x) {
          return '<div class="diag-line">' + esc(x) + '</div>';
        }).join('') || '<div class="diag-line">（本次由手动配置 / 缓存直接命中，未展开扫描）</div>';
        if ((k.candidates || []).length) {
          html += '<div class="diag-title">候选可执行文件</div>';
          html += k.candidates.map(function (x) { return '<div class="diag-line ok">' + esc(x) + '</div>'; }).join('');
        }
        diag.innerHTML = html;
      }
      return k;
    } catch (e) {
      if (st) { st.className = 'kicad-state warn'; st.textContent = '探测失败：' + e.message; }
      return null;
    }
  }

  async function saveKicadPath(path) {
    try {
      await api('/api/kicad/config', { method: 'POST', body: { path: path || '' } });
      await loadKicad(false);
      toast(path ? 'KiCad 路径已保存并立即生效' : '已清除手动路径，恢复自动探测');
    } catch (e) {
      toast('保存失败：' + e.message, true);
    }
  }

  async function browseKicad() {
    try {
      var apiObj = window.pywebview && window.pywebview.api;
      if (apiObj && apiObj.pick_kicad_exe) {
        var p = await apiObj.pick_kicad_exe();
        if (p) { $('#setKicadPath').value = p; toast('已选择：' + p); }
      } else {
        toast('浏览器模式拿不到本地绝对路径，请手动粘贴 kicad.exe 完整路径', true);
        $('#setKicadPath').focus();
      }
    } catch (e) {
      toast('打开文件对话框失败：' + e.message, true);
    }
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
      renderKicadChip(s.kicad);
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
    } catch (e) {
      toast(e.message || '未检测到本机 KiCad', true);
      if (e.message && e.message.indexOf('KiCad') >= 0) openDrawer('settingsDrawer');
    }
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
      hideInsight(); hideRequirement(); resetSteps();
      var vb = $('#btnVersion'); if (vb) vb.hidden = true;
      if (!silent) toast('已新建会话');
    } catch (e) { toast('新建会话失败：' + e.message, true); }
  }

  /* ------------------------------------------------------------- 事件绑定 */
  function bind() {
    // 顶栏
    $('#btnNew').onclick = function () { newSession(false); };
    $('#btnHistory').onclick = function () { openDrawer('historyDrawer'); };
    $('#btnLibrary').onclick = function () { openDrawer('libraryDrawer'); };
    $('#btnVersion').onclick = function () { openDrawer('versionDrawer'); };
    $('#btnArchive').onclick = archiveCurrent;
    $('#btnSettings').onclick = function () { openDrawer('settingsDrawer'); };
    $('#btnHelp').onclick = function () { renderHelp(); openDrawer('helpDrawer'); };
    $('#btnTheme').onclick = function () { applyTheme(state.theme === 'dark' ? 'light' : 'dark'); };
    $('#chipKicad').onclick = function () { openDrawer('settingsDrawer'); };
    $('#chipLlm').onclick = function () { openDrawer('modelDrawer'); };

    // v2.4 大模型配置抽屉
    $('#btnTestLlm').onclick = testLlm;
    $('#btnSaveModel').onclick = saveModelConfig;
    $$('#modelPresets .preset-card').forEach(function (b) {
      b.onclick = function () {
        $$('#modelPresets .preset-card').forEach(function (x) { x.classList.remove('active'); });
        b.classList.add('active');
        $('#mdlBaseUrl').value = b.dataset.base;
        $('#mdlModel').value = b.dataset.model;
        showModelResult('已选择预设：' + b.querySelector('b').textContent
          + '。填入 API Key 后点「测试连接」。', true);
      };
    });

    // v2.5 离线库表单
    $('#btnLibRefresh').onclick = function () { loadLibrary(false); };
    $('#btnLibNew').onclick = function () { openLibEditor(null); };
    $('#btnLibCancel').onclick = function () { $('#libEditor').hidden = true; libState.editing = null; };
    $('#btnLibSave').onclick = saveLibraryItem;
    $('#libSearch').oninput = function () {
      clearTimeout($('#libSearch')._t);
      $('#libSearch')._t = setTimeout(function () { loadLibrary(true); }, 350);
    };

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
    // v2.3：板子库降级为备用，默认收起
    var tplToggle = $('#tplToggle');
    if (tplToggle) tplToggle.onclick = function () {
      var b = $('#tplBody'); b.hidden = !b.hidden;
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

    // KiCad 集成
    $('#btnSaveKicad').onclick = function () { saveKicadPath($('#setKicadPath').value.trim()); };
    $('#btnDetectKicad').onclick = function () { loadKicad(true); toast('已重新自动探测'); };
    $('#btnClearKicad').onclick = function () { $('#setKicadPath').value = ''; saveKicadPath(''); };
    $('#btnBrowseKicad').onclick = browseKicad;
    $('#btnToggleKicadDiag').onclick = function () {
      var d = $('#kicadDiag');
      d.hidden = !d.hidden;
      this.textContent = d.hidden ? '查看探测诊断' : '收起探测诊断';
    };

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
    initVoice();
    loadStatus();

    try {
      var caps = await api('/api/capabilities');
      state.capabilities = caps;
      state.templates = caps.templates || [];
      state.templateCats = caps.template_categories || [];
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
