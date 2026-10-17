// 单专家对话接入知识库问答接口 /api/chat；专家团对话仍走预设流程。
(() => {
  const ROLES = {
    zhangsan: '张三 · 销售部',
    lisi: '李四 · 财务部',
    reception: 'AI 接待助手 · 面向买家',
  };
  const MODES = {
    qa: ['标准问答直答', 'green'],
    rag: ['知识库检索作答', 'blue'],
    choose: ['请选择问题', 'orange'],
    empty: ['知识库无依据', 'gray'],
  };
  const LIVE = { root: null, turns: [], role: localStorage.getItem('accio-live-role') || 'zhangsan' };
  const baseAction = action;
  const baseGeneric = genericResponse;

  const clock = () => new Date().toTimeString().slice(0, 8);
  const isLive = () => S.route === 'chat' && S.genericChat && !S.genericTeam && LIVE.root === S.lastPrompt;

  function scrollEnd() {
    const box = $('#chat-scroll');
    const last = [...document.querySelectorAll('#chat-scroll .agent-message')].pop();
    if (!box || !last) return;
    const prev = last.previousElementSibling;
    const anchor = prev?.classList.contains('user-message') ? prev : last;
    box.scrollTop = anchor.getBoundingClientRect().top - box.getBoundingClientRect().top + box.scrollTop - 12;
  }

  async function ask(turn) {
    const history = LIVE.turns
      .filter((t) => t !== turn && t.state === 'done')
      .flatMap((t) => [{ role: 'user', content: t.q }, { role: 'assistant', content: t.answer }]);
    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: turn.q, role: LIVE.role, history }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
      Object.assign(turn, data, { state: 'done' });
    } catch (err) {
      turn.state = 'error';
      turn.error = /fetch|HTTP (404|405|50\d)/.test(err.message) ? '知识库服务未启动或暂时不可用' : err.message;
    }
    if (isLive()) {
      render();
      scrollEnd();
    }
  }

  function push(q) {
    const turn = { q, state: 'loading', time: clock(), role: LIVE.role };
    LIVE.turns.push(turn);
    ask(turn);
  }

  function inline(text) {
    return text
      .replace(/&amp;nbsp;/g, ' ')
      .replace(/\*\*(.+?)\*\*/g, '<b>$1</b>')
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      .replace(/\[(\d+)\]/g, '<sup class="live-cite">$1</sup>');
  }

  function markdown(src) {
    const lines = h(src).split('\n');
    const out = [];
    let list = null;
    let table = [];
    const closeList = () => {
      if (list) out.push(`</${list}>`);
      list = null;
    };
    const flushTable = () => {
      if (!table.length) return;
      const rows = table
        .filter((l) => !/^\|?\s*:?-{2,}/.test(l))
        .map((l) => l.replace(/^\||\|$/g, '').split('|').map((c) => inline(c.trim())));
      const [head, ...body] = rows;
      out.push(
        `<div class="live-table"><table><thead><tr>${head.map((c) => `<th>${c}</th>`).join('')}</tr></thead>` +
          `<tbody>${body.map((r) => `<tr>${r.map((c) => `<td>${c}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`,
      );
      table = [];
    };
    for (const raw of lines) {
      const line = raw.trim();
      if (line.startsWith('|')) {
        closeList();
        table.push(line);
        continue;
      }
      flushTable();
      const bullet = line.match(/^[-*•]\s+(.*)/);
      const numbered = line.match(/^\d+[.、]\s*(.*)/);
      if (bullet || numbered) {
        const tag = bullet ? 'ul' : 'ol';
        if (list !== tag) {
          closeList();
          out.push(`<${tag}>`);
          list = tag;
        }
        out.push(`<li>${inline((bullet || numbered)[1])}</li>`);
        continue;
      }
      closeList();
      if (!line) continue;
      const heading = line.match(/^#{1,4}\s+(.*)/);
      if (heading) out.push(`<h4>${inline(heading[1])}</h4>`);
      else if (line.startsWith('&gt;')) out.push(`<blockquote>${inline(line.replace(/^&gt;\s*/, ''))}</blockquote>`);
      else out.push(`<p>${inline(line)}</p>`);
    }
    closeList();
    flushTable();
    return out.join('');
  }

  function sources(t) {
    if (!t.sources?.length) return '';
    const items = t.sources
      .map(
        (s) =>
          `<li><span class="live-cite">${s.n}</span><b>${h(s.doc_name)}</b> v${s.version}` +
          `<small>${h(s.kind)} · ${h(s.locator)}${s.score != null ? ` · 相关分 ${s.score}` : ''}</small></li>`,
      )
      .join('');
    return `<div class="live-sources"><h5>来源</h5><ol>${items}</ol></div>`;
  }

  function trace(t) {
    const tr = t.trace;
    if (!tr) return '';
    const filtered = !tr.filtered_count
      ? '检索前没有文档被过滤'
      : tr.filtered.length
        ? `检索前过滤 ${tr.filtered_count} 份：${tr.filtered.map((f) => `${h(f.name)}（${h(f.reason)}）`).join('；')}`
        : `检索前按权限过滤 ${tr.filtered_count} 份（面向买家时不展示文档名）`;
    const top = tr.qa.top.map(([q, s]) => `${h(q)} ${s}`).join('；');
    const rag =
      tr.rag.message ||
      `重排后保留 ${tr.rag.kept} 条相关分 ≥${tr.rag.threshold} 的片段${tr.rag.rerank_status === 'failed' ? '（未经重排）' : ''}`;
    const timing = Object.entries(tr.timing)
      .map(([k, v]) => `${k} ${v} ms`)
      .join(' · ');
    return (
      `<details class="live-trace"><summary>检索过程</summary><ul>` +
      `<li><b>身份</b>${h(tr.role)}；${filtered}</li>` +
      `<li><b>标准问答</b>${h(tr.qa.message || '无可用问答')}${top ? `<br><small>相似度前 3：${top}</small>` : ''}</li>` +
      `<li><b>表格查询</b>命中 ${tr.structured.hits} 行${tr.structured.excluded ? `，排除过期或未生效 ${tr.structured.excluded} 行` : ''}</li>` +
      `<li><b>文档检索</b>${h(rag)}</li>` +
      `<li><b>耗时</b>${timing}</li></ul></details>`
    );
  }

  function chips(i, list, label) {
    if (!list?.length) return '';
    const buttons = list
      .map((q, j) => `<button class="live-chip" data-action="live-ask|${i}|${j}|${label === '你是不是想问' ? 's' : 'o'}">${h(q)}</button>`)
      .join('');
    return `<div class="live-chips"><span>${label}</span>${buttons}</div>`;
  }

  function roleBar() {
    const options = Object.entries(ROLES)
      .map(([k, v]) => `<option value="${k}" ${k === LIVE.role ? 'selected' : ''}>${v}</option>`)
      .join('');
    return `<div class="live-bar">${icon('search', true)}<span>检索知识库的身份</span><select id="live-role">${options}</select></div>`;
  }

  function body(t, i) {
    const head = i === 0 ? roleBar() : '';
    if (t.state === 'loading') return `${head}<p class="live-loading"><span></span>正在检索知识库…</p>`;
    if (t.state === 'error')
      return `${head}<div class="live-error">${h(t.error)}<button class="live-chip" data-action="live-retry|${i}">重试</button></div>`;
    const [label, tone] = MODES[t.mode] || MODES.rag;
    return (
      `${head}<div class="live-mode ${tone}">${label}${t.unreranked ? ' · 未经重排' : ''}</div>` +
      `<div class="live-answer">${markdown(t.answer)}</div>` +
      chips(i, t.options, '选择你要问的') +
      chips(i, t.suggestions, '你是不是想问') +
      sources(t) +
      trace(t)
    );
  }

  function userBubble(q) {
    return (
      `<div class="user-message"><div class="row"><span>${h(profile.name)}</span>` +
      `<span class="user-avatar" style="width:28px;height:28px">${h(profile.name[0])}</span></div>` +
      `<div class="user-bubble">${h(q)}</div></div>`
    );
  }

  genericResponse = function () {
    if (!isLive() || !LIVE.turns.length) return baseGeneric();
    return LIVE.turns
      .map((t, i) => (i ? userBubble(t.q) : '') + agentMessage(S.expert, body(t, i), t.time).replace(`昨天 ${t.time}`, t.time))
      .join('');
  };

  action = async function (a, el) {
    const [name, v, w, x] = a.split('|');
    if (name === 'live-ask') {
      const t = LIVE.turns[+v];
      push((x === 's' ? t.suggestions : t.options)[+w]);
      render();
      scrollEnd();
      return;
    }
    if (name === 'live-retry') {
      const t = LIVE.turns[+v];
      t.state = 'loading';
      render();
      ask(t);
      return;
    }
    if (name === 'send' && v === 'chat' && isLive()) {
      const input = $('#chat-prompt');
      const text = input?.value.trim() || '';
      if (!text) {
        toast('请先输入问题');
        input?.focus();
        return;
      }
      input.value = '';
      push(text);
      render();
      scrollEnd();
      return;
    }
    const text = name === 'send' && v === 'home' ? $('#prompt')?.value.trim() || '' : '';
    await baseAction(a, el);
    if (text && S.route === 'chat' && S.genericChat && !S.genericTeam) {
      LIVE.root = S.lastPrompt;
      LIVE.turns = [];
      push(S.lastPrompt);
      render();
    }
  };

  document.addEventListener('change', (e) => {
    if (e.target.id !== 'live-role') return;
    LIVE.role = e.target.value;
    localStorage.setItem('accio-live-role', LIVE.role);
    toast(`之后的提问按「${ROLES[LIVE.role]}」的权限检索`);
  });
})();
