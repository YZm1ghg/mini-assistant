/* ============================================================
   迷你助手 · 手机/平板/手表 共用逻辑

   ⚠⚠ 三条铁律
   ============================================================
   ① **不内置任何地址或密钥**
      后端地址存在 localStorage，第一次打开让用户填。
      代码里搜不到任何 IP、端口、token。

   ② **零依赖**
      不用任何框架/CDN —— 因为 APK 里要离线打开，
      而且 CDN 在国内经常连不上。

   ③ **后端 API 跟桌面版完全一样**
      所以同一台电脑既能给桌面用也能给手机用。
   ============================================================ */

'use strict';

// ------------------------------------------------------------
//  配置
// ------------------------------------------------------------
var K_HOST = 'mini_host';        // 后端地址
var K_HIST = 'mini_hist';        // 本地记录
var K_SESS = 'mini_sess';        // 当前会话 id

/* 默认端口。
 *
 * ⚠ 这个值必须跟桌面版 config.json 里的默认值一致，
 *   否则自动搜索找不到、地址也补不全。
 *
 * ⚠ 它**不是**你个人的 IP —— 只是个端口号，
 *   而且用户在电脑上能改。这里写一份是为了
 *   让「只填 IP」这种输入能自动补全。
 *   用户改了端口就在手机上手填完整地址。
 *
 * ⚠ 必须定义在使用它的函数**之前**的模块顶层
 *   （var 虽然会提升，但提升后是 undefined ——
 *     那个坑很隐蔽，所以放最上面）。
 */
var DEFAULT_PORT = 64874;

/* 自动搜索要扫的网段。
 *
 * ⚠ 只列了最通用的家用网段 —— 不针对任何特定网络。
 *   常见家用路由器默认就用这几种。
 *
 *   找不到的话手动填地址更靠谱。
 */
var SCAN_PREFIXES = [
  '192.168.1.',
  '192.168.0.',
  '192.168.2.',
  '192.168.31.'
];

function getHost() {
  try { return localStorage.getItem(K_HOST) || ''; } catch (e) { return ''; }
}
function setHost(v) {
  try { localStorage.setItem(K_HOST, v); } catch (e) {}
}

/** 把用户输入整理成规范地址。
 *
 *  ⚠ 用户可能填各种形式，都要能认（踩过）：
 *      只写 IP               → 补 http:// 和默认端口
 *      写了端口              → 补 http://
 *      带了 http:// 和斜杠   → 去掉末尾斜杠
 *      写了主机名            → 原样保留
 */
function normHost(s) {
  s = String(s || '').trim();
  if (!s) return '';
  s = s.replace(/\/+$/, '');                 // 去末尾斜杠
  if (!/^https?:\/\//i.test(s)) s = 'http://' + s;
  // 没写端口的补上默认
  var m = s.match(/^https?:\/\/([^\/:]+)(:\d+)?/i);
  if (m && !m[2]) s = s.replace(m[1], m[1] + ':' + DEFAULT_PORT);
  return s;
}

function api(path) { return getHost() + path; }

// ------------------------------------------------------------
//  请求
// ------------------------------------------------------------
function req(method, path, body, timeout) {
  return new Promise(function (ok, no) {
    var url = api(path);
    if (!url) { no(new Error('还没配置后端地址')); return; }

    var x = new XMLHttpRequest();
    x.open(method, url, true);
    x.timeout = timeout || 20000;

    if (body !== undefined && body !== null) {
      x.setRequestHeader('Content-Type', 'application/json');
    }
    x.onload = function () {
      var d;
      try { d = JSON.parse(x.responseText || '{}'); }
      catch (e) { d = { ok: false, error: '返回不是 JSON' }; }
      if (x.status >= 200 && x.status < 300) ok(d);
      else no(new Error(d.error || ('HTTP ' + x.status)));
    };
    x.onerror = function () { no(new Error('连不上 ' + url)); };
    x.ontimeout = function () { no(new Error('超时了（后端没响应）')); };
    x.send(body ? JSON.stringify(body) : null);
  });
}

function get(p) { return req('GET', p, null, 15000); }
function post(p, b, t) { return req('POST', p, b || {}, t || 300000); }

// ------------------------------------------------------------
//  弹提示
// ------------------------------------------------------------
var _tt;
function toast(msg, ms) {
  var el = document.getElementById('toast');
  if (!el) return;
  el.textContent = msg;
  el.classList.add('show');
  clearTimeout(_tt);
  _tt = setTimeout(function () { el.classList.remove('show'); },
                   ms || 2200);
}

function setStatus(s) {
  var el = document.getElementById('status');
  if (el) el.textContent = s || '';
}

// ------------------------------------------------------------
//  首次配置
// ------------------------------------------------------------
function saveSetup() {
  var el = document.getElementById('s-host');
  var err = document.getElementById('s-err');
  var raw = el.value.trim();
  if (!raw) { err.textContent = '请填后端地址'; return; }

  var h = normHost(raw);
  err.textContent = '连接中…';

  // 先探一下通不通，通了才存（避免存个错地址自己都不知道）
  var x = new XMLHttpRequest();
  x.open('GET', h + '/api/state', true);
  x.timeout = 8000;
  x.onload = function () {
    if (x.status >= 200 && x.status < 300) {
      setHost(h);
      err.textContent = '';
      document.getElementById('setup').classList.remove('show');
      document.getElementById('app').classList.remove('hidden');
      boot();
    } else {
      err.textContent = '连上了但返回 HTTP ' + x.status +
                        '，确认地址对不对';
    }
  };
  x.onerror = function () {
    err.textContent = '连不上。检查：① 电脑上服务开着吗 ' +
                      '② 手机和电脑同一个 Wi-Fi 吗 ③ 地址写对了吗';
  };
  x.ontimeout = function () { err.textContent = '超时了，地址可能不对'; };
  x.send();
}

/** 扫局域网找后端。
 *
 *  ⚠ 并发限流：手机上同时发 1000+ 个请求会直接把
 *    浏览器卡死，这里限制同时最多 12 个。
 */
function scan() {
  var err = document.getElementById('s-err');
  err.textContent = '正在搜索局域网…（约 10 秒）';

  var prefixes = SCAN_PREFIXES;
  var port = DEFAULT_PORT;
  var found = 0, done = 0, total = prefixes.length * 254;
  var running = 0, queue = [];

  function probe(ip) {
    var x = new XMLHttpRequest();
    x.open('GET', 'http://' + ip + ':' + port + '/api/ping', true);
    x.timeout = 1200;
    x.onload = function () {
      if (found === 0 && x.status >= 200 && x.status < 300) {
        found = 1;
        var el = document.getElementById('s-host');
        el.value = ip + ':' + port;
        err.textContent = '找到了！点「连接」就行';
      }
      step();
    };
    x.onerror = step;
    x.ontimeout = step;
    x.send();
  }

  function step() {
    done++;
    running--;
    if (found) return;
    if (done >= total) {
      err.textContent = found ? err.textContent
        : '没搜到。多半是电脑上的服务没开，或者不在同一个网络。' +
          '也可以手动填地址。';
      return;
    }
    next();
  }

  function next() {
    while (running < 12 && queue.length) {
      running++;
      probe(queue.shift());
    }
  }

  prefixes.forEach(function (p) {
    for (var i = 1; i <= 254; i++) queue.push(p + i);
  });
  next();
}

function editHost() {
  closeMenu();
  document.getElementById('s-host').value = getHost();
  document.getElementById('s-err').textContent = '';
  document.getElementById('setup').classList.add('show');
}

function reconnect() {
  closeMenu();
  toast('重新连接…');
  boot();
}

// ------------------------------------------------------------
//  菜单
// ------------------------------------------------------------
function openMenu() {
  document.getElementById('menu').classList.add('show');
  refreshMenu();
}
function closeMenu() {
  document.getElementById('menu').classList.remove('show');
}
function refreshMenu() {
  var h = document.getElementById('m-host');
  if (h) h.textContent = getHost() || '（没配置）';

  get('/api/state').then(function (d) {
    var b = document.getElementById('m-back');
    if (!b) return;
    var be = d.backend || {};
    b.textContent = be.ok ? '正常' : '不可用';
    b.style.color = be.ok ? 'var(--accent)' : 'var(--danger)';
  }).catch(function () {
    var b = document.getElementById('m-back');
    if (b) {
      b.textContent = '连不上';
      b.style.color = 'var(--danger)';
    }
  });
}

function clearAll() {
  try {
    localStorage.removeItem(K_HIST);
    localStorage.removeItem(K_SESS);
  } catch (e) {}
  closeMenu();
  render([]);
  toast('已清空');
}

// ------------------------------------------------------------
//  消息渲染
// ------------------------------------------------------------
var hist = [];      // [{role, text, meta}]

function loadHist() {
  try {
    hist = JSON.parse(localStorage.getItem(K_HIST) || '[]') || [];
  } catch (e) { hist = []; }
}
function saveHist() {
  try {
    // 只留最近 60 条，免得 localStorage 撑爆
    var keep = hist.slice(-60);
    localStorage.setItem(K_HIST, JSON.stringify(keep));
  } catch (e) {}
}

function esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

/** 极简 markdown：代码块 + 行内代码。
 *
 *  ⚠ 不做完整 markdown 解析 —— 手机上没必要，
 *    而且容易出 XSS。只处理这两种最常见的。
 */
function fmt(s) {
  var t = esc(s);
  // 代码块 ```...```
  t = t.replace(/```(\w*)\n?([\s\S]*?)```/g,
    function (_, lang, code) {
      return '<pre><code>' + code.replace(/\n$/, '') +
             '</code></pre>';
    });
  // 行内 `
  t = t.replace(/`([^`\n]+)`/g, '<code>$1</code>');
  return t;
}

function render(list) {
  var box = document.getElementById('msgs');
  if (!box) return;

  if (!list || !list.length) {
    box.innerHTML =
      '<div class="empty"><div class="logo">D</div>' +
      '<p>说点什么，或者点下面的麦克风</p></div>';
    return;
  }

  var h = '';
  list.forEach(function (m) {
    var who = m.role === 'user' ? '我' : '助手';
    var cls = m.role === 'user' ? 'me' : 'ai';
    h += '<div class="msg ' + cls + '">';
    h += '<div class="who">' + who + '</div>';
    h += '<div class="body">' + fmt(m.text) + '</div>';
    if (m.meta) h += '<div class="meta">' + esc(m.meta) + '</div>';
    h += '</div>';
  });
  // 正在思考
  if (thinking) {
    h += '<div class="msg ai"><div class="who">助手</div>' +
         '<div class="think"><div class="spin"></div>' +
         '<span>思考中…</span></div></div>';
  }
  box.innerHTML = h;
  scrollBottom();
}

function scrollBottom() {
  var m = document.getElementById('list');
  if (m) m.scrollTop = m.scrollHeight;
}

var thinking = false;

// ------------------------------------------------------------
//  发消息
// ------------------------------------------------------------
function send() {
  var el = document.getElementById('in');
  var text = (el.value || '').trim();
  if (!text || thinking) return;
  el.value = '';
  el.style.height = 'auto';
  ask(text);
}

function ask(text) {
  hist.push({ role: 'user', text: text });
  thinking = true;
  render(hist);
  setStatus('');

  var t0 = Date.now();
  post('/api/ask', {
    text: text,
    session: getSess(),
    speak: false          // ⚠ 手机端不自动念 —— 声音在手机上更烦
  }).then(function (d) {
    thinking = false;
    if (d.session) setSess(d.session);

    var meta = '';
    if (d.fast) {
      meta = ((Date.now() - t0) / 1000).toFixed(2) + 's' +
             ' · 本地技能';
    } else if (d.elapsed) {
      meta = Number(d.elapsed).toFixed(1) + 's';
    }
    hist.push({ role: 'ai', text: d.text || '(没返回内容)',
                meta: meta });
    saveHist();
    render(hist);
    setStatus('');
  }).catch(function (e) {
    thinking = false;
    hist.push({ role: 'ai', text: '出错了：' + e.message,
                meta: '失败' });
    render(hist);
    setStatus('');
  });
}

function getSess() {
  try { return localStorage.getItem(K_SESS) || ''; } catch (e) { return ''; }
}
function setSess(v) {
  try { localStorage.setItem(K_SESS, v); } catch (e) {}
}

function newChat() {
  closeMenu();
  try { localStorage.removeItem(K_SESS); } catch (e) {}
  hist = [];
  saveHist();
  render(hist);
  toast('新对话');
}

// ------------------------------------------------------------
//  语音输入
// ------------------------------------------------------------
var recState = 0;          // 0 空闲 1 录音 2 处理
var mediaRec = null, chunks = [], recTimer = null;

/** 开始/结束录音。
 *
 *  ⚠ 录音走浏览器自己的 MediaRecorder（MediaDevices API），
 *    录成 webm 发给后端，后端用 ffmpeg 转 wav 再识别。
 *
 *  ⚠ 需要 HTTPS 或本地来源才能用麦克风！
 *    在 APK 的 WebView 里，只要 MainActivity 授权了
 *    RECORD_AUDIO 并且 onPermissionRequest 放行，就能用。
 */
function record() {
  if (recState === 2) return;

  if (recState === 1) {
    // 停
    if (mediaRec && mediaRec.state !== 'inactive') mediaRec.stop();
    return;
  }

  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    toast('这个环境不支持录音');
    return;
  }

  navigator.mediaDevices.getUserMedia({ audio: true })
    .then(function (stream) {
      chunks = [];
      mediaRec = new MediaRecorder(stream);
      mediaRec.ondataavailable = function (e) {
        if (e.data && e.data.size) chunks.push(e.data);
      };
      mediaRec.onstop = function () {
        stream.getTracks().forEach(function (t) { t.stop(); });
        clearTimeout(recTimer);
        var blob = new Blob(chunks, { type: 'audio/webm' });
        uploadVoice(blob);
      };
      mediaRec.start();
      setRecState(1);
      setStatus('正在录音… 说完点一下停止');
      // 最多录 30 秒，自动停
      recTimer = setTimeout(function () {
        if (recState === 1) record();
      }, 30000);
    })
    .catch(function (e) {
      toast('拿不到麦克风：' + e.message);
    });
}

function setRecState(s) {
  recState = s;
  var b = document.getElementById('micBtn');
  if (!b) return;
  b.classList.remove('rec', 'busy');
  if (s === 1) b.classList.add('rec');
  if (s === 2) b.classList.add('busy');
}

function uploadVoice(blob) {
  setRecState(2);
  setStatus('正在识别…');

  var x = new XMLHttpRequest();
  x.open('POST', api('/api/voice/upload'), true);
  x.timeout = 120000;
  x.setRequestHeader('Content-Type',
                     blob.type || 'application/octet-stream');
  x.onload = function () {
    setRecState(0);
    var d;
    try { d = JSON.parse(x.responseText || '{}'); }
    catch (e) { d = {}; }
    if (d.ok && d.text) {
      setStatus('');
      document.getElementById('in').value = d.text;
      ask(d.text);                 // 识别到就直接问
    } else {
      setStatus('');
      toast(d.error || '没听清');
    }
  };
  x.onerror = function () {
    setRecState(0);
    setStatus('');
    toast('上传失败');
  };
  x.send(blob);
}

// ------------------------------------------------------------
//  输入框自适应高度
// ------------------------------------------------------------
function bindInput() {
  var el = document.getElementById('in');
  if (!el) return;
  el.addEventListener('input', function () {
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 120) + 'px';
  });
  el.addEventListener('keydown', function (e) {
    // 回车发送（Shift+Enter 换行）
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  });
}

// ------------------------------------------------------------
//  启动
// ------------------------------------------------------------
function boot() {
  loadHist();
  render(hist);
  bindInput();

  get('/api/state').then(function (d) {
    var be = d.backend || {};
    if (be.ok) {
      setStatus('已连接 · ' + getHost().replace(/^https?:\/\//, ''));
    } else {
      setStatus('后端不可用 · ' + (be.error || ''));
    }
  }).catch(function (e) {
    setStatus('连不上 · ' + e.message);
  });
}

document.addEventListener('DOMContentLoaded', function () {
  if (getHost()) {
    document.getElementById('setup').classList.remove('show');
    document.getElementById('app').classList.remove('hidden');
    boot();
  }
  // 输入框里回车也能提交
  var sh = document.getElementById('s-host');
  if (sh) {
    sh.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') saveSetup();
    });
  }
});
