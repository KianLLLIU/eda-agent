/* EDA Agent 前端逻辑 */
(function () {
  'use strict';

  var state = { mode: null }; // null=auto, true=llm, false=template

  /* ---------- 工具 ---------- */
  function $(sel) { return document.querySelector(sel); }
  function toast(msg, isError) {
    var t = $('#toast');
    t.textContent = msg;
    t.className = 'toast show' + (isError ? ' error' : '');
    clearTimeout(t._timer);
    t._timer = setTimeout(function () { t.className = 'toast'; }, 3200);
  }

  /* ---------- 轻量 Markdown 渲染 ---------- */
  function esc(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
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
      // 引用
      if (/^>\s?/.test(line)) {
        closeList(); closeTable();
        if (!inQuote) { html += '<blockquote>'; inQuote = true; }
        html += inline(line.replace(/^>\s?/, '')) + '<br/>';
        return;
      } else { closeQuote(); }

      // 表格
      if (/^\|.*\|/.test(line)) {
        closeList();
        var cells = line.split('|').slice(1, -1).map(function (c) { return c.trim(); });
        var isSep = cells.every(function (c) { return /^:?-{2,}:?$/.test(c); });
        if (isSep) return;
        if (!inTable) { html += '<table>'; inTable = true; }
        var tag = /^\|.*\|\s*$/.test(line) && html.indexOf('<table>') === html.lastIndexOf('<table>')
          ? 'td' : 'td';
        // 用上一行是否为表头判断：这里简化，首行表头
        html += '<tr>' + cells.map(function (c) {
          return '<' + tag + '>' + inline(c) + '</' + tag + '>';
        }).join('') + '</tr>';
        return;
      } else { closeTable(); }

      // 标题
      if (/^### /.test(line)) { closeList(); html += '<h3>' + inline(line.slice(4)) + '</h3>'; return; }
      if (/^## /.test(line)) { closeList(); html += '<h2>' + inline(line.slice(3)) + '</h2>'; return; }
      if (/^# /.test(line)) { closeList(); html += '<h1>' + inline(line.slice(2)) + '</h1>'; return; }

      // 无序列表
      if (/^[-*] /.test(line)) {
        if (!inList) { html += '<ul>'; inList = true; }
        html += '<li>' + inline(line.replace(/^[-*] /, '')) + '</li>';
        return;
      }
      // 有序列表
      if (/^\d+\. /.test(line)) {
        if (!inList) { html += '<ul>'; inList = true; }
        html += '<li>' + inline(line.replace(/^\d+\. /, '')) + '</li>';
        return;
      }
      closeList();

      if (line.trim() === '') { html += ''; return; }
      html += '<p>' + inline(line) + '</p>';
    });
    closeList(); closeTable(); closeQuote();
    return html;
  }
  function inline(s) {
    var t = esc(s);
    t = t.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    t = t.replace(/`([^`]+)`/g, '<code>$1</code>');
    return t;
  }

  /* ---------- 流水线动画 ---------- */
  function resetSteps() {
    document.querySelectorAll('.step').forEach(function (s) {
      s.classList.remove('active', 'done');
    });
  }
  function setStep(n, status) {
    var steps = document.querySelectorAll('.step');
    steps.forEach(function (s, i) {
      var idx = i + 1;
      if (idx < n) s.classList.add('done'), s.classList.remove('active');
      else if (idx === n) s.classList.add(status === 'done' ? 'done' : 'active');
    });
  }

  /* ---------- 状态 ---------- */
  function loadStatus() {
    fetch('/api/status')
      .then(function (r) { return r.json(); })
      .then(function (s) {
        var c = $('#chipLlm');
        if (s.llm_mode === 'custom') { c.classList.add('ok'); c.innerHTML = '<i class="dot"></i>LLM · ' + esc(s.llm_model); }
        else if (s.llm_mode === 'free') { c.classList.add('ok'); c.innerHTML = '<i class="dot"></i>免费在线 LLM · ' + esc(s.llm_model); }
        else { c.classList.add('warn'); c.innerHTML = '<i class="dot"></i>LLM 不可用（用离线模板）'; }
        $('#chipKicad').classList.add('ok');
        $('#chipKicad').innerHTML = '<i class="dot"></i>KiCad 导出就绪';
      })
      .catch(function () {
        $('#chipLlm').classList.add('warn');
        $('#chipLlm').innerHTML = '<i class="dot"></i>状态获取失败';
      });
  }

  /* ---------- 生成 ---------- */
  function generate() {
    var req = $('#requirement').value.trim();
    if (!req) { toast('请先输入电路需求', true); return; }

    var btn = $('#btnGenerate');
    btn.disabled = true;
    $('#btnText').textContent = '生成中…';
    resetSteps();
    $('#results').hidden = false;
    $('#resultMeta').textContent = '正在分析需求…';

    var body = { requirement: req };
    if (state.mode === true) body.use_llm = true;
    else if (state.mode === false) body.use_llm = false;

    setStep(1, 'active');
    var timer = setInterval(function () {
      var steps = document.querySelectorAll('.step');
      var cur = 1;
      steps.forEach(function (s, i) { if (s.classList.contains('active') || s.classList.contains('done')) cur = i + 1; });
      if (cur < 5) setStep(cur + 1, 'active');
    }, 400);

    fetch('/api/design', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    })
      .then(function (r) {
        if (!r.ok) return r.json().then(function (e) { throw new Error(e.detail || ('HTTP ' + r.status)); });
        return r.json();
      })
      .then(function (data) {
        clearInterval(timer);
        document.querySelectorAll('.step').forEach(function (s) { s.classList.add('done'); s.classList.remove('active'); });
        renderResults(data);
        btn.disabled = false;
        $('#btnText').textContent = '生成电路';
        toast('电路生成完成');
      })
      .catch(function (err) {
        clearInterval(timer);
        resetSteps();
        btn.disabled = false;
        $('#btnText').textContent = '生成电路';
        toast('生成失败：' + err.message, true);
      });
  }

  function renderResults(data) {
    var title = (data.design && data.design.title) || '设计结果';
    $('#resultTitle').textContent = title;
    var modeText;
    if (data.mode && data.mode.indexOf('llm:free') >= 0) modeText = '免费在线 LLM 生成';
    else if (data.mode && data.mode.indexOf('llm:custom') >= 0) modeText = 'LLM 生成';
    else modeText = '离线模板生成';
    $('#resultMeta').textContent = modeText + ' · ' + (data.design.components || []).length + ' 个元件 · ' + (data.design.nets || []).length + ' 条网络';

    $('#panel-bom').innerHTML = '<div class="md">' + renderMd(data.bom_md) + '</div>';
    $('#panel-netlist').innerHTML = '<div class="md">' + renderMd(data.netlist_md) + '</div>';
    $('#panel-report').innerHTML = '<div class="md">' + renderMd(data.report_md) + '</div>';
    $('#panel-guide').innerHTML = '<div class="md">' + renderMd(data.guide_md) + '</div>';
    $('#panel-hardware').innerHTML = '<div class="md">' + renderMd(data.hardware_md) + '</div>';

    var dl = $('#btnDownload');
    dl.href = '/api/download?path=' + encodeURIComponent(data.download_zip);
    dl.removeAttribute('hidden');

    // 切回第一个 tab
    switchTab('bom');
  }

  function switchTab(name) {
    document.querySelectorAll('.tab').forEach(function (t) {
      t.classList.toggle('active', t.dataset.tab === name);
    });
    document.querySelectorAll('.panel').forEach(function (p) {
      p.classList.toggle('active', p.id === 'panel-' + name);
    });
  }

  /* ---------- 事件绑定 ---------- */
  document.addEventListener('DOMContentLoaded', function () {
    loadStatus();

    $('#btnGenerate').addEventListener('click', generate);
    $('#requirement').addEventListener('keydown', function (e) {
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') generate();
    });

    document.querySelectorAll('.chip-example').forEach(function (c) {
      c.addEventListener('click', function () {
        $('#requirement').value = c.dataset.tpl;
      });
    });

    document.querySelectorAll('.tab').forEach(function (t) {
      t.addEventListener('click', function () { switchTab(t.dataset.tab); });
    });

    function setMode(m) {
      state.mode = m;
      $('#modeAuto').classList.toggle('active', m === null);
      $('#modeLlm').classList.toggle('active', m === true);
      $('#modeTpl').classList.toggle('active', m === false);
    }
    $('#modeAuto').addEventListener('click', function () { setMode(null); });
    $('#modeLlm').addEventListener('click', function () { setMode(true); });
    $('#modeTpl').addEventListener('click', function () { setMode(false); });
  });
})();
