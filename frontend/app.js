/* EDA Agent 前端逻辑（浅色版） */
(function () {
  'use strict';

  var state = {
    difficulty: 'intermediate',
    style: 'classic',
    design: null,          // 当前设计（用于对话式修改）
    projectName: null,
    zipPath: null,
    generating: false
  };

  function $(sel) { return document.querySelector(sel); }
  function $$(sel) { return document.querySelectorAll(sel); }

  function toast(msg, isError) {
    var t = $('#toast');
    t.textContent = msg;
    t.className = 'toast show' + (isError ? ' error' : '');
    clearTimeout(t._timer);
    t._timer = setTimeout(function () { t.className = 'toast'; }, 3400);
  }

  function esc(s) { return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }

  /* ---------- 轻量 Markdown 渲染 ---------- */
  function inline(s) {
    var t = esc(s);
    t = t.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    t = t.replace(/`([^`]+)`/g, '<code>$1</code>');
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
      if (/^>\s?/.test(line)) {
        closeList(); closeTable();
        if (!inQuote) { html += '<blockquote>'; inQuote = true; }
        html += inline(line.replace(/^>\s?/, '')) + '<br/>';
        return;
      } else { closeQuote(); }
      if (/^\|.*\|/.test(line)) {
        closeList();
        var cells = line.split('|').slice(1, -1).map(function (c) { return c.trim(); });
        if (cells.every(function (c) { return /^:?-{2,}:?$/.test(c); })) return;
        if (!inTable) { html += '<table>'; inTable = true; }
        html += '<tr>' + cells.map(function (c) { return '<td>' + inline(c) + '</td>'; }).join('') + '</tr>';
        return;
      } else { closeTable(); }
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

  /* ---------- 状态 ---------- */
  function loadStatus() {
    fetch('/api/status')
      .then(function (r) { return r.json(); })
      .then(function (s) {
        var c = $('#chipLlm');
        if (s.llm_mode === 'custom') { c.classList.add('ok'); c.querySelector('.chip-txt').textContent = 'LLM · ' + s.llm_model; }
        else if (s.llm_mode === 'free') { c.classList.add('ok'); c.querySelector('.chip-txt').textContent = '免费在线 LLM'; }
        else { c.classList.add('warn'); c.querySelector('.chip-txt').textContent = 'LLM 不可用（离线模板）'; }
      })
      .catch(function () {
        var c = $('#chipLlm');
        c.classList.add('warn'); c.querySelector('.chip-txt').textContent = '状态获取失败';
      });
  }

  /* ---------- 聊天 ---------- */
  function addMessage(role, text, highlightKw) {
    var box = $('#chatMessages');
    var div = document.createElement('div');
    div.className = 'msg ' + role;
    var avatar = document.createElement('div');
    avatar.className = 'avatar';
    avatar.textContent = role === 'user' ? '我' : 'W';
    var bubble = document.createElement('div');
    bubble.className = 'bubble';
    if (highlightKw) {
      // 高亮关键词
      var t = esc(text);
      highlightKw.forEach(function (k) {
        var re = new RegExp('(' + k.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ')', 'gi');
        t = t.replace(re, '<span class="kw">$1</span>');
      });
      bubble.innerHTML = t;
    } else {
      bubble.textContent = text;
    }
    div.appendChild(avatar);
    div.appendChild(bubble);
    box.appendChild(div);
    box.scrollTop = box.scrollHeight;
  }

  function showKeywords(kws) {
    var box = $('#keywordChips');
    box.innerHTML = '';
    (kws || []).forEach(function (k) {
      var chip = document.createElement('span');
      chip.className = 'kchip';
      chip.textContent = k;
      box.appendChild(chip);
    });
  }

  /* ---------- 进度步骤 ---------- */
  function resetSteps() {
    $$('.step').forEach(function (s) { s.classList.remove('active', 'done'); });
  }
  function setStep(n) {
    $$('.step').forEach(function (s, i) {
      var idx = i + 1;
      if (idx < n) { s.classList.add('done'); s.classList.remove('active'); }
      else if (idx === n) s.classList.add('active');
    });
  }
  function allStepsDone() {
    $$('.step').forEach(function (s) { s.classList.add('done'); s.classList.remove('active'); });
  }

  /* ---------- 实时构图动画 ---------- */
  function playSvgAnimation(svgText) {
    var container = $('#stageSvg');
    container.innerHTML = svgText;
    container.hidden = false;
    $('#stageEmpty').hidden = true;
    $('#stageBadge').hidden = false;
    $('#replayBtn').hidden = false;

    var svg = container.querySelector('svg');
    if (!svg) return;

    // 元件/模块动画顺序
    svg.querySelectorAll('.comp, .group').forEach(function (el) {
      el.style.setProperty('--i', el.getAttribute('data-i') || '0');
    });
    // 网络连线：计算实际长度，做逐条画线动画
    svg.querySelectorAll('.net').forEach(function (el) {
      el.style.setProperty('--i', el.getAttribute('data-i') || '0');
      var len;
      try { len = el.getTotalLength(); } catch (e) { len = 200; }
      el.style.setProperty('--len', len);
      el.style.strokeDasharray = len;
      el.style.strokeDashoffset = len;
    });

    // 动画总时长（元件 + 连线）
    var total = (svg.querySelectorAll('.comp, .group, .net').length || 1) * 120 + 800;
    $('#stageBadgeText').textContent = '构图进行中…';
    setTimeout(function () {
      $('#stageBadgeText').textContent = '构图完成';
      $('#stageBadge').querySelector('.badge-dot').style.animation = 'none';
    }, total);
  }

  function setStageBadge(text) {
    $('#stageBadgeText').textContent = text;
    var dot = $('#stageBadge').querySelector('.badge-dot');
    dot.style.animation = 'pulse 1.2s ease infinite';
  }

  /* ---------- 结果渲染 ---------- */
  function renderResults(data, requirement) {
    var title = (data.design && data.design.title) || '设计结果';
    $('#resultTitle').textContent = title;
    var modeText;
    if (data.mode && data.mode.indexOf('llm:free') >= 0) modeText = '免费在线 LLM';
    else if (data.mode && data.mode.indexOf('llm:custom') >= 0) modeText = 'LLM';
    else modeText = '离线模板';
    var comps = (data.design && data.design.components) || [];
    var nets = (data.design && data.design.nets) || [];
    $('#resultMeta').textContent = modeText + '生成 · ' + comps.length + ' 元件 · ' + nets.length + ' 网络 · ' + (state.difficulty === 'beginner' ? '入门' : state.difficulty === 'advanced' ? '挑战' : '进阶');

    $('#panel-bom').innerHTML = '<div class="md">' + renderMd(data.bom_md) + '</div>';
    $('#panel-netlist').innerHTML = '<div class="md">' + renderMd(data.netlist_md) + '</div>';
    $('#panel-report').innerHTML = '<div class="md">' + renderMd(data.report_md) + '</div>';
    $('#panel-guide').innerHTML = '<div class="md">' + renderMd(data.guide_md) + '</div>';
    $('#panel-hardware').innerHTML = '<div class="md">' + renderMd(data.hardware_md) + '</div>';

    $('#btnDownload').href = '/api/download?path=' + encodeURIComponent(data.download_zip);
    $('#resultPanel').hidden = false;
    switchTab('bom');
  }

  function switchTab(name) {
    $$('.tab').forEach(function (t) { t.classList.toggle('active', t.dataset.tab === name); });
    $$('.panel').forEach(function (p) { p.classList.toggle('active', p.id === 'panel-' + name); });
  }

  /* ---------- 核心：发送消息（新需求 or 修改指令） ---------- */
  function sendMessage(text) {
    if (state.generating) return;
    text = text.trim();
    if (!text) return;

    state.generating = true;
    $('#sendBtn').disabled = true;
    $('#hintText').textContent = '正在处理…';
    addMessage('user', text);

    var isRevision = !!state.design;
    var body;
    if (isRevision) {
      body = { design: state.design, instruction: text };
      addMessage('assistant', '收到修改指令，正在更新电路…');
    } else {
      body = { requirement: text, difficulty: state.difficulty, style: state.style };
    }

    // 进度动画
    resetSteps();
    setStep(1);
    setStageBadge(isRevision ? '正在修改…' : '正在生成…');
    var stepTimer = setInterval(function () {
      var cur = 0;
      $$('.step').forEach(function (s, i) { if (s.classList.contains('active') || s.classList.contains('done')) cur = i + 1; });
      if (cur < 5) setStep(cur + 1);
    }, 600);

    var endpoint = isRevision ? '/api/revision' : '/api/design';

    fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    })
      .then(function (r) {
        if (!r.ok) return r.json().then(function (e) { throw new Error(e.detail || ('HTTP ' + r.status)); });
        return r.json();
      })
      .then(function (data) {
        clearInterval(stepTimer);
        allStepsDone();

        // 更新状态
        state.design = data.design;
        state.projectName = data.project_name;
        state.zipPath = data.download_zip;

        // 关键词 + 助手回复
        if (!isRevision && data.keywords && data.keywords.length) {
          showKeywords(data.keywords);
          addMessage('assistant', '已识别关键词，正在为你生成电路…');
        }

        // 实时构图动画
        playSvgAnimation(data.svg);

        // 渲染结果
        renderResults(data, text);

        addMessage('assistant', '电路已生成，你可以在右侧查看构图过程和完整 BOM / 网表。想调整的话直接说，比如「把电容换成 100nF」。');
        $('#hintText').textContent = '可继续输入修改指令，或描述新电路';

        state.generating = false;
        $('#sendBtn').disabled = false;
        toast(isRevision ? '电路已更新' : '电路生成完成');
      })
      .catch(function (err) {
        clearInterval(stepTimer);
        resetSteps();
        addMessage('assistant', '出错了：' + err.message);
        state.generating = false;
        $('#sendBtn').disabled = false;
        $('#hintText').textContent = '请重试';
        toast('生成失败：' + err.message, true);
      });
  }

  /* ---------- 用 KiCad 打开 ---------- */
  function openKicad() {
    if (!state.zipPath) { toast('请先生成电路', true); return; }
    fetch('/api/open-kicad', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ zip_path: state.zipPath })
    })
      .then(function (r) { return r.json().catch(function () { return {}; }); })
      .then(function (d) {
        if (d && d.ok) toast('已在 KiCad 中打开工程');
        else toast(d && d.detail ? d.detail : '未检测到本机 KiCad，请下载后手动打开', true);
      })
      .catch(function () { toast('未检测到本机 KiCad，请下载后手动打开', true); });
  }

  /* ---------- 事件绑定 ---------- */
  function bindEvents() {
    // 难度
    $$('#difficultyGroup .seg').forEach(function (btn) {
      btn.addEventListener('click', function () {
        $$('#difficultyGroup .seg').forEach(function (b) { b.classList.remove('active'); });
        btn.classList.add('active');
        state.difficulty = btn.dataset.difficulty;
      });
    });
    // 风格
    $$('#styleGroup .style-opt').forEach(function (btn) {
      btn.addEventListener('click', function () {
        $$('#styleGroup .style-opt').forEach(function (b) { b.classList.remove('active'); });
        btn.classList.add('active');
        state.style = btn.dataset.style;
      });
    });
    // 发送
    function doSend() {
      var v = $('#chatInput').value;
      if (v.trim()) { $('#chatInput').value = ''; sendMessage(v); }
    }
    $('#sendBtn').addEventListener('click', doSend);
    $('#chatInput').addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); doSend(); }
    });
    // 标签页
    $$('.tab').forEach(function (t) {
      t.addEventListener('click', function () { switchTab(t.dataset.tab); });
    });
    // 重播构图
    $('#replayBtn').addEventListener('click', function () {
      if ($('#stageSvg').innerHTML) playSvgAnimation($('#stageSvg').innerHTML);
    });
    // 用 KiCad 打开
    $('#btnOpenKicad').addEventListener('click', openKicad);
  }

  document.addEventListener('DOMContentLoaded', function () {
    loadStatus();
    bindEvents();
    $('#chatInput').focus();
  });
})();
