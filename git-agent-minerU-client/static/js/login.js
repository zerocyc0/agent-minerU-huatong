// 登录页逻辑
(function () {
  const $ = (id) => document.getElementById(id);

  // 已登录则直接进入主界面
  fetch('/api/auth/me').then(r => { if (r.ok) location.href = '/app'; }).catch(() => {});

  // Tab 切换
  document.querySelectorAll('.login-tab').forEach(tab => {
    tab.addEventListener('click', () => {
      document.querySelectorAll('.login-tab').forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      const isLogin = tab.dataset.tab === 'login';
      $('loginForm').classList.toggle('hidden', !isLogin);
      $('registerForm').classList.toggle('hidden', isLogin);
      $('loginErr').textContent = '';
      $('regErr').textContent = '';
    });
  });

  async function post(url, body) {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    return res.json();
  }

  // 登录
  $('loginForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    $('loginErr').textContent = '';
    const j = await post('/api/auth/login', {
      username: $('loginUsername').value.trim(),
      password: $('loginPassword').value,
    });
    if (j.code === 200) { location.href = '/app'; }
    else { $('loginErr').textContent = j.message || '登录失败'; }
  });

  // 注册
  $('registerForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    $('regErr').textContent = '';
    const pwd = $('regPassword').value;
    if (pwd !== $('regPassword2').value) {
      $('regErr').textContent = '两次输入的密码不一致';
      return;
    }
    const j = await post('/api/auth/register', {
      staff_id: $('regStaffId').value.trim(),
      real_name: $('regRealName').value.trim(),
      username: $('regUsername').value.trim(),
      password: pwd,
    });
    if (j.code === 200) { location.href = '/app'; }
    else { $('regErr').textContent = j.message || '注册失败'; }
  });
})();
