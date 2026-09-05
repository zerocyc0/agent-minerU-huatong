// 主界面逻辑: 视图切换 / 文件分析 / 数据查询 / 用户管理
(function () {
  const $ = (id) => document.getElementById(id);
  const state = {
    user: null,
    files: [],          // 待分析文件 [{name, size, file}]
    taskId: null,
    pollTimer: null,
    pollStart: 0,
    analyzing: false,
    rows: [],           // 分析结果行
    queried: false,     // 查询页是否已加载过
  };

  // ---------------- 通用 ----------------
  async function api(url, opts = {}) {
    const res = await fetch(url, opts);
    let j;
    try { j = await res.json(); } catch (e) { j = { code: res.status, message: '响应异常' }; }
    if (res.status === 401) { location.href = '/login'; throw new Error('未登录'); }
    return j;
  }
  function post(url, body) {
    return api(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  }
  function toast(msg, type) {
    const el = document.createElement('div');
    el.className = 'toast' + (type === 'ok' ? ' toast-ok' : type === 'err' ? ' toast-err' : '');
    el.textContent = msg;
    $('toasts').appendChild(el);
    setTimeout(() => { el.style.opacity = '0'; el.style.transition = 'opacity .3s'; }, 2900);
    setTimeout(() => el.remove(), 3300);
  }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g,
      c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }
  function todayStr() {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  }
  function fmtSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / 1048576).toFixed(1) + ' MB';
  }

  // ---------------- 初始化 ----------------
  async function init() {
    const j = await api('/api/auth/me');
    state.user = j.data.user;
    renderUser();
    applyPerms();
    bindNav();
    bindAnalysis();
    bindQuery();
    bindUsers();

    const d = new Date();
    const week = ['日', '一', '二', '三', '四', '五', '六'][d.getDay()];
    $('topDate').textContent =
      `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日 星期${week}`;
    $('qStart').value = todayStr();
    $('qEnd').value = todayStr();
    showView('analysis');
  }

  function renderUser() {
    const u = state.user;
    $('avatarText').textContent = (u.real_name || u.username || '?').charAt(0).toUpperCase();
    $('sbUserName').textContent = u.real_name ? `${u.real_name}（${u.username}）` : u.username;
    $('sbUserSub').textContent = u.role === 'admin'
      ? `管理员 · ${u.staff_id}` : `员工 · ${u.staff_id}`;
  }

  function applyPerms() {
    const u = state.user;
    const isAdmin = u.role === 'admin';
    document.querySelectorAll('.admin-only').forEach(el => {
      el.classList.toggle('hidden', !isAdmin);
    });
    const navAnalysis = document.querySelector('.nav-item[data-view="analysis"]');
    const navQuery = document.querySelector('.nav-item[data-view="query"]');
    navAnalysis.classList.toggle('hidden', !isAdmin && !u.perm_analysis);
    navQuery.classList.toggle('hidden', !isAdmin && !u.perm_query);
    if (!isAdmin && !u.perm_analysis && !u.perm_query) {
      toast('您还没有任何功能权限，请联系管理员授权', 'err');
    }
  }

  // ---------------- 视图切换 ----------------
  function showView(name) {
    document.querySelectorAll('.nav-item').forEach(n =>
      n.classList.toggle('active', n.dataset.view === name));
    document.querySelectorAll('.view').forEach(v =>
      v.classList.toggle('active', v.id === `view-${name}`));
    const nav = document.querySelector(`.nav-item[data-view="${name}"]`);
    $('pageTitle').textContent = nav ? nav.dataset.title : '';
    if (name === 'query' && !state.queried) { state.queried = true; doQuery(); }
    if (name === 'users') loadUsers();
  }
  function bindNav() {
    document.querySelectorAll('.nav-item').forEach(n =>
      n.addEventListener('click', () => showView(n.dataset.view)));
    $('btnLogout').addEventListener('click', async () => {
      await post('/api/auth/logout', {});
      location.href = '/login';
    });
  }

  // ================= 视图1: 文件分析 =================
  const FIELDS = ['model', 'spec', 'voltage', 'color', 'standard', 'quantity', 'unit'];
  const CN = { model: '型号', spec: '规格', voltage: '电压', color: '颜色', standard: '标准', quantity: '数量', unit: '单位' };

  function bindAnalysis() {
    const dz = $('dropZone'), fi = $('fileInput');
    dz.addEventListener('click', () => fi.click());
    fi.addEventListener('change', () => { addFiles(fi.files); fi.value = ''; });
    dz.addEventListener('dragover', e => { e.preventDefault(); dz.classList.add('dragover'); });
    dz.addEventListener('dragleave', () => dz.classList.remove('dragover'));
    dz.addEventListener('drop', e => {
      e.preventDefault(); dz.classList.remove('dragover');
      addFiles(e.dataTransfer.files);
    });
    $('btnAnalyze').addEventListener('click', startAnalyze);
    $('btnSave').addEventListener('click', saveRows);
  }

  function addFiles(list) {
    for (const f of list) {
      const dup = state.files.some(x => x.name === f.name && x.size === f.size);
      if (!dup) state.files.push({ name: f.name, size: f.size, file: f });
    }
    renderChips();
  }
  function renderChips() {
    $('fileChips').innerHTML = state.files.map((f, i) =>
      `<span class="chip">${esc(f.name)}（${fmtSize(f.size)}）
        <button class="chip-x" data-i="${i}" title="移除">✕</button></span>`).join('');
    $('fileChips').querySelectorAll('.chip-x').forEach(b =>
      b.addEventListener('click', () => {
        state.files.splice(+b.dataset.i, 1); renderChips();
      }));
  }

  async function startAnalyze() {
    if (state.analyzing) return;
    if (!state.files.length) { toast('请先选择要分析的文件', 'err'); return; }
    state.analyzing = true;
    $('btnAnalyze').disabled = true;
    $('progressBox').classList.remove('hidden');
    $('progressElapsed').textContent = '';
    state.pollStart = Date.now();
    $('resultArea').innerHTML = '';
    $('saveBar').classList.add('hidden');

    try {
      const fd = new FormData();
      state.files.forEach(f => fd.append('files', f.file, f.name));
      fd.append('question', $('questionInput').value.trim());
      const j = await api('/api/analysis/upload', { method: 'POST', body: fd });
      if (j.code !== 200) { toast(j.message || '提交失败', 'err'); resetAnalyzeUI(); return; }
      state.taskId = j.data.task.task_id;
      toast(`已提交 ${state.files.length} 个文件，正在分析…`);
      state.pollTimer = setInterval(pollTask, 2000);
    } catch (e) {
      toast('提交失败: ' + e.message, 'err');
      resetAnalyzeUI();
    }
  }
  function resetAnalyzeUI() {
    state.analyzing = false;
    $('btnAnalyze').disabled = false;
    $('progressBox').classList.add('hidden');
  }

  async function pollTask() {
    const j = await api(`/api/analysis/task/${state.taskId}`);
    const t = j.data.task;
    const elapsed = t.elapsed != null ? t.elapsed : Math.round((Date.now() - state.pollStart) / 1000);
    $('progressElapsed').textContent = `已用时 ${elapsed} 秒`;
    if (t.status === 'running') return;
    clearInterval(state.pollTimer);
    resetAnalyzeUI();
    if (t.status === 'error') {
      toast(t.error || '分析失败', 'err');
      $('resultArea').innerHTML = `<div class="card"><div class="badge badge-err">分析失败</div>
        <div class="muted" style="margin-top:10px">${esc(t.error || '')}</div></div>`;
      return;
    }
    renderResults(t.result);
  }

  function renderResults(result) {
    if (!result) { toast('未收到分析结果', 'err'); return; }
    const data = result.data || {};
    const area = $('resultArea');
    area.innerHTML = '';
    state.rows = [];

    const summary = document.createElement('div');
    summary.className = 'card';
    summary.innerHTML = `<div class="result-head">
      <span class="badge badge-ok">分析完成</span>
      <span class="result-meta">共 ${data.total || 0} 个文件，成功 ${data.success_count || 0} 个，失败 ${data.fail_count || 0} 个</span>
    </div>`;
    area.appendChild(summary);

    (data.results || []).forEach(r => {
      const card = document.createElement('div');
      card.className = 'card result-card';
      const ok = r.code === 200;
      let head = `<div class="result-head">
        <svg viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
          <polyline points="14 2 14 8 20 8"/>
        </svg>
        <span class="result-name">${esc(r.file_name)}</span>
        <span class="badge ${ok ? 'badge-ok' : 'badge-err'}">${ok ? '解析成功' : '解析失败 ' + (r.code || '')}</span>
        <span class="result-meta">${esc(r.message || '')}</span>
        ${r.db_saved != null ? `<span class="result-meta">已自动写入 material_analysis ${r.db_saved} 条</span>` : ''}
      </div>`;
      card.innerHTML = head;

      if (ok) {
        const items = (r.analysis && r.analysis.items) || [];
        if (items.length) {
          const tbl = document.createElement('div');
          tbl.className = 'tbl-wrap';
          let body = '';
          items.forEach((it, i) => {
            const fileSn = r.file_sn || '';
            const dataSn = (r.data_sns || [])[i] || '';
            const row = {
              file_sn: fileSn, data_sn: dataSn, file_name: r.file_name,
              modified: false, saved: false, tr: null,
              model: it['型号'] || '', spec: it['规格'] || '', voltage: it['电压'] || '',
              color: it['颜色'] || '', standard: it['标准'] || '',
              quantity: it['数量'] == null ? '' : it['数量'], unit: it['单位'] || '',
            };
            const idx = state.rows.push(row) - 1;
            body += `<tr>
              <td style="min-width:110px"><input class="cell-input" data-i="${idx}" data-f="model" value="${esc(row.model)}"></td>
              <td style="min-width:110px"><input class="cell-input" data-i="${idx}" data-f="spec" value="${esc(row.spec)}"></td>
              <td style="min-width:90px"><input class="cell-input" data-i="${idx}" data-f="voltage" value="${esc(row.voltage)}"></td>
              <td style="min-width:90px"><input class="cell-input" data-i="${idx}" data-f="color" value="${esc(row.color)}"></td>
              <td style="min-width:110px"><input class="cell-input" data-i="${idx}" data-f="standard" value="${esc(row.standard)}"></td>
              <td style="min-width:80px"><input class="cell-input" data-i="${idx}" data-f="quantity" value="${esc(row.quantity)}"></td>
              <td style="min-width:80px"><input class="cell-input" data-i="${idx}" data-f="unit" value="${esc(row.unit)}"></td>
              <td class="row-sn" style="min-width:170px;font-family:Consolas,monospace;font-size:12.5px">${esc(fileSn) || '<span class="muted">—</span>'}</td>
              <td class="row-dsn" style="font-family:Consolas,monospace;font-size:12.5px;text-align:center">${esc(dataSn) || '<span class="muted">—</span>'}</td>
              <td class="row-status">${fileSn ? '待确认' : '新记录'}</td>
              <td class="row-op"><button class="btn btn-danger-ghost btn-sm btn-del-row" data-i="${idx}" title="删除此行">删除</button></td>
            </tr>`;
          });
          tbl.innerHTML = `<table class="tbl editable"><thead><tr>
              <th>型号</th><th>规格</th><th>电压</th><th>颜色</th><th>标准</th><th>数量</th><th>单位</th><th>文件编号</th><th>数据序号</th><th>状态</th><th>操作</th>
            </tr></thead><tbody>${body}</tbody></table>`;
          card.appendChild(tbl);
        } else {
          card.insertAdjacentHTML('beforeend',
            `<div class="muted" style="padding:10px 0">该文件未解析出物料条目</div>`);
        }
        if (r.answer) {
          card.insertAdjacentHTML('beforeend',
            `<div class="muted" style="margin-top:10px; line-height:1.7">AI 说明：${esc(r.answer)}</div>`);
        }
      }
      area.appendChild(card);
    });

    // 可编辑输入绑定
    area.querySelectorAll('.cell-input').forEach(inp => {
      inp.addEventListener('input', () => {
        const row = state.rows[+inp.dataset.i];
        row[inp.dataset.f] = inp.value;
        if (!row.modified) {
          row.modified = true;
          row.tr = row.tr || inp.closest('tr');
          row.tr.classList.add('row-dirty');
          row.tr.querySelector('.row-status').textContent = '已修改';
        }
        updateSaveBar();
      });
    });
    // 删除行按钮：软删除（置 null 保持索引稳定），同步移除 DOM
    area.querySelectorAll('.btn-del-row').forEach(btn => {
      btn.addEventListener('click', () => {
        const i = +btn.dataset.i;
        const row = state.rows[i];
        if (!row) return;
        const tr = btn.closest('tr');
        const tbody = tr && tr.parentNode;
        if (tr) tr.remove();
        state.rows[i] = null;
        // 该文件所有行都被删除后，展示空提示，保持卡片结构
        if (tbody && !tbody.querySelector('tr')) {
          const tblWrap = tbody.closest('.tbl-wrap');
          if (tblWrap) {
            tblWrap.innerHTML = '<div class="muted" style="padding:10px 0">该文件结果已全部删除</div>';
          }
        }
        updateSaveBar();
        toast('已删除该条数据');
      });
    });
    // 缓存行 DOM
    area.querySelectorAll('tbody tr').forEach(tr => {
      const inp = tr.querySelector('.cell-input');
      if (inp) state.rows[+inp.dataset.i].tr = tr;
    });
    updateSaveBar();
    if ((data.fail_count || 0) > 0) toast(`有 ${data.fail_count} 个文件解析失败，请查看结果`, 'err');
  }

  function updateSaveBar() {
    // 过滤已删除行（null）
    const rows = state.rows.filter(r => r);
    const total = rows.length;
    const modified = rows.filter(r => r.modified).length;
    $('saveBar').classList.toggle('hidden', total === 0);
    $('saveInfo').innerHTML = total
      ? `共 <b>${total}</b> 条分析结果 · 已修改 <b>${modified}</b> 条 · 修改后点“保存到数据库”按钮`
      : '';
  }

  async function saveRows() {
    // 过滤已删除行（null），仅保存有效行
    const validRows = state.rows.filter(r => r);
    if (!validRows.length) return;
    // 首次保存：行还没保存到 material_analysis_last（saved=false）→ 需要保存
    // 已保存且未修改：saved=true && modified=false → 跳过
    const hasWork = validRows.some(r => !r.saved || r.modified);
    if (!hasWork) {
      toast('数据已经保存过了，无需重复保存', 'ok');
      return;
    }
    const payload = validRows.map(r => ({
      file_sn: r.file_sn, data_sn: r.data_sn, file_name: r.file_name, modified: r.modified,
      model: r.model, spec: r.spec, voltage: r.voltage, color: r.color,
      standard: r.standard, quantity: r.quantity, unit: r.unit,
    }));
    $('btnSave').disabled = true;
    try {
      const j = await post('/api/analysis/save', { rows: payload });
      if (j.code === 200) {
        toast(j.message, 'ok');
        const sns = (j.data && j.data.file_sns) || [];
        const dsns = (j.data && j.data.data_sns) || [];
        // 按 validRows 顺序回填编号（与 payload 一一对应）
        validRows.forEach((r, i) => {
          if (sns[i] && !r.file_sn) {
            r.file_sn = sns[i];
            if (r.tr) {
              const snCell = r.tr.querySelector('.row-sn');
              if (snCell) snCell.textContent = sns[i];
            }
          }
          if (dsns[i] && !r.data_sn) {
            r.data_sn = dsns[i];
            if (r.tr) {
              const dsnCell = r.tr.querySelector('.row-dsn');
              if (dsnCell) dsnCell.textContent = dsns[i];
            }
          }
          r.modified = false;
          r.saved = true;
          if (r.tr) {
            r.tr.classList.remove('row-dirty');
            r.tr.classList.add('row-saved');
            r.tr.querySelector('.row-status').textContent = '已保存';
          }
        });
        if (j.data.errors && j.data.errors.length) {
          toast('部分行保存失败: ' + j.data.errors[0], 'err');
        }
        updateSaveBar();
      } else {
        toast(j.message || '保存失败', 'err');
      }
    } catch (e) {
      toast('保存失败: ' + e.message, 'err');
    } finally {
      $('btnSave').disabled = false;
    }
  }

  // ================= 视图2: 数据查询 =================
  function bindQuery() {
    $('btnQuery').addEventListener('click', () => { state.queried = true; doQuery(); });
  }

  async function doQuery() {
    const u = state.user;
    const params = new URLSearchParams({
      start: $('qStart').value || todayStr(),
      end: $('qEnd').value || todayStr(),
      table: $('qTable').value,
    });
    if (u.role === 'admin' && $('qStaff').value.trim()) {
      params.set('staff_id', $('qStaff').value.trim());
    }
    const j = await api(`/api/query?${params}`);
    if (j.code !== 200) { toast(j.message || '查询失败', 'err'); return; }
    const d = j.data;
    renderStats(d.summary);
    renderChart(d.chart, d.start, d.end);
    renderQueryRows(d.rows);
  }

  function renderStats(s) {
    $('statGrid').innerHTML = `
      <div class="stat-card">
        <div class="stat-label">数据总条数</div>
        <div class="stat-value">${s.total}<small>条</small></div>
      </div>
      <div class="stat-card c-ok">
        <div class="stat-label">涉及文件数</div>
        <div class="stat-value">${s.files}<small>个</small></div>
      </div>
      <div class="stat-card c-violet">
        <div class="stat-label">最早记录</div>
        <div class="stat-value" style="font-size:15px; line-height:38px">${esc(s.first || '—')}</div>
      </div>
      <div class="stat-card c-orange">
        <div class="stat-label">最近记录</div>
        <div class="stat-value" style="font-size:15px; line-height:38px">${esc(s.last || '—')}</div>
      </div>`;
  }

  function renderChart(buckets, start, end) {
    const max = Math.max(...buckets.map(b => b.count), 1);
    $('chart').innerHTML = buckets.map(b => {
      const h = b.count > 0 ? Math.max(Math.round(b.count / max * 100), 4) : 2;
      return `<div class="bar-col" title="${esc(b.label)}：${b.count} 条">
        <div class="bar-val">${b.count > 0 ? b.count : ''}</div>
        <div class="bar ${b.count === 0 ? 'zero' : ''}" style="height:${h}%"></div>
        <div class="bar-label">${esc(b.label)}</div>
      </div>`;
    }).join('');
    $('chartLeft').textContent = `${start} 至 ${end}`;
    $('chartRight').textContent = '纵轴：数据条数（当日按小时 / 跨天按日统计）';
  }

  function renderQueryRows(rows) {
    $('qCount').textContent = `共 ${rows.length} 条`;
    $('queryTbody').innerHTML = rows.length
      ? rows.map(r => `<tr>
          <td style="font-family:Consolas,monospace;font-size:12.5px">${esc(r.file_sn)}</td>
          <td style="text-align:center">${esc(r.data_sn)}</td>
          <td>${esc(r.file_name)}</td>
          <td>${esc(r.model)}</td><td>${esc(r.spec)}</td><td>${esc(r.voltage)}</td>
          <td>${esc(r.color)}</td><td>${esc(r.standard)}</td>
          <td>${esc(r.quantity)}</td><td>${esc(r.unit)}</td>
          <td>${esc(r.create_date)}</td><td>${esc(r.edit_date)}</td>
          <td>${esc(r.staff_id)}</td>
        </tr>`).join('')
      : `<tr class="empty-row"><td colspan="13">该时间段内暂无数据</td></tr>`;
  }

  // ================= 视图3: 用户管理 =================
  async function loadUsers() {
    const j = await api('/api/users');
    if (j.code !== 200) { toast(j.message || '加载用户失败', 'err'); return; }
    const me = state.user;
    $('usersTbody').innerHTML = j.data.users.map(u => {
      const isSelf = u.staff_id === me.staff_id;
      const isAdmin = u.role === 'admin';
      const locked = isSelf || u.staff_id === 'admin';   // 自身与内置管理员限制
      const roleCell = locked
        ? `<span class="badge ${isAdmin ? 'badge-admin' : 'badge-role'}">${isAdmin ? '管理员' : '员工'}</span>`
        : `<select class="role-select" data-id="${esc(u.staff_id)}" data-k="role">
             <option value="employee" ${!isAdmin ? 'selected' : ''}>员工</option>
             <option value="admin" ${isAdmin ? 'selected' : ''}>管理员</option>
           </select>`;
      const permDisabled = isAdmin ? 'disabled title="管理员默认拥有全部权限"' : '';
      const statusDisabled = locked ? 'disabled' : '';
      return `<tr>
        <td style="font-family:Consolas,monospace;font-weight:600">${esc(u.staff_id)}</td>
        <td>${esc(u.username)}</td>
        <td>${esc(u.real_name || '—')}</td>
        <td>${roleCell}</td>
        <td><label class="switch"><input type="checkbox" data-id="${esc(u.staff_id)}" data-k="perm_analysis"
          ${u.perm_analysis ? 'checked' : ''} ${permDisabled}><span class="slider"></span></label></td>
        <td><label class="switch"><input type="checkbox" data-id="${esc(u.staff_id)}" data-k="perm_query"
          ${u.perm_query ? 'checked' : ''} ${permDisabled}><span class="slider"></span></label></td>
        <td><label class="switch"><input type="checkbox" data-id="${esc(u.staff_id)}" data-k="status"
          ${u.status ? 'checked' : ''} ${statusDisabled}><span class="slider"></span></label></td>
        <td class="muted">${esc(u.create_date)}</td>
        <td><div class="op-cell">
          <button class="btn btn-ghost btn-sm" data-op="pwd" data-id="${esc(u.staff_id)}">重置密码</button>
          <button class="btn btn-danger-ghost btn-sm" data-op="del" data-id="${esc(u.staff_id)}"
            ${locked ? 'disabled' : ''}>删除</button>
        </div></td>
      </tr>`;
    }).join('');

    // 权限/状态开关
    $('usersTbody').querySelectorAll('input[type="checkbox"]').forEach(cb => {
      cb.addEventListener('change', async () => {
        const body = {};
        body[cb.dataset.k] = cb.checked;
        const j2 = await api(`/api/users/${cb.dataset.id}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
        if (j2.code === 200) {
          toast(`已更新用户 ${cb.dataset.id}`, 'ok');
          if (cb.dataset.id === me.staff_id) {
            const nu = j2.data.user;
            state.user = nu; renderUser(); applyPerms();
          }
        } else { toast(j2.message || '更新失败', 'err'); loadUsers(); }
      });
    });
    // 角色下拉
    $('usersTbody').querySelectorAll('.role-select').forEach(sel => {
      sel.addEventListener('change', async () => {
        const j2 = await api(`/api/users/${sel.dataset.id}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ role: sel.value }),
        });
        if (j2.code === 200) toast('角色已更新', 'ok');
        else { toast(j2.message || '更新失败', 'err'); }
        loadUsers();
      });
    });
    // 操作按钮
    $('usersTbody').querySelectorAll('button[data-op]').forEach(btn => {
      btn.addEventListener('click', async () => {
        const id = btn.dataset.id;
        if (btn.dataset.op === 'pwd') {
          const pwd = prompt(`为用户 ${id} 设置新密码（至少 6 位）：`);
          if (!pwd) return;
          const j2 = await api(`/api/users/${id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ password: pwd }),
          });
          toast(j2.code === 200 ? '密码已重置' : (j2.message || '重置失败'),
            j2.code === 200 ? 'ok' : 'err');
        } else if (btn.dataset.op === 'del') {
          if (!confirm(`确认删除用户 ${id}？该操作不可恢复。`)) return;
          const j2 = await api(`/api/users/${id}`, { method: 'DELETE' });
          toast(j2.code === 200 ? '已删除' : (j2.message || '删除失败'),
            j2.code === 200 ? 'ok' : 'err');
          if (j2.code === 200) loadUsers();
        }
      });
    });
  }

  function bindUsers() {
    $('btnAddUser').addEventListener('click', () => {
      ['nuStaffId', 'nuUsername', 'nuRealName', 'nuPassword'].forEach(id => $(id).value = '');
      $('nuRole').value = 'employee';
      $('nuPermAnalysis').checked = false;
      $('nuPermQuery').checked = false;
      $('nuErr').textContent = '';
      $('modalMask').classList.remove('hidden');
    });
    $('nuRole').addEventListener('change', () => {
      $('nuPermBox').style.display = $('nuRole').value === 'admin' ? 'none' : '';
    });
    $('nuCancel').addEventListener('click', () => $('modalMask').classList.add('hidden'));
    $('nuOk').addEventListener('click', async () => {
      const j = await post('/api/users', {
        staff_id: $('nuStaffId').value.trim(),
        username: $('nuUsername').value.trim(),
        real_name: $('nuRealName').value.trim(),
        password: $('nuPassword').value,
        role: $('nuRole').value,
        perm_analysis: $('nuPermAnalysis').checked,
        perm_query: $('nuPermQuery').checked,
      });
      if (j.code === 200) {
        $('modalMask').classList.add('hidden');
        toast('新增用户成功', 'ok');
        loadUsers();
      } else {
        $('nuErr').textContent = j.message || '新增失败';
      }
    });
  }

  init().catch(() => { location.href = '/login'; });
})();
