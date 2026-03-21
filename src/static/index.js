// ── State ────────────────────────────────────────────────────────────────────
let currentProjectId = null;
let currentThreadId = null;
let currentThreadTitle = '';
let eventSource = null;
let agentBusy = false;
let pollInterval = null;

// ── Utilities ────────────────────────────────────────────────────────────────
function showToast(msg, duration = 2800) {
    const t = document.getElementById('toast');
    t.textContent = msg;
    t.classList.add('show');
    setTimeout(() => t.classList.remove('show'), duration);
}

function setStatus(label, active = false) {
    document.getElementById('status-text').textContent = label;
    document.getElementById('status-dot').classList.toggle('active', active);
}

function scrollBottom() {
    const area = document.getElementById('chat-area');
    area.scrollTop = area.scrollHeight;
}

function autoResize(el) {
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 160) + 'px';
}

function setInputEnabled(enabled) {
    const inp = document.getElementById('msg-input');
    const btn = document.getElementById('btn-send');
    inp.disabled = !enabled;
    btn.disabled = !enabled;
}

function setHaltVisible(visible) {
    document.getElementById('btn-halt').classList.toggle('visible', visible);
}

async function apiFetch(url, opts = {}) {
    const res = await fetch(url, opts);
    if (!res.ok) {
        const err = await res.json().catch(() => ({ error: res.statusText }));
        throw new Error(err.error || res.statusText);
    }
    return res.json();
}

// ── Project/Thread list ───────────────────────────────────────────────────────
async function loadProjects() {
    const projects = await apiFetch('/api/projects');
    const list = document.getElementById('project-list');
    list.innerHTML = '';
    if (!projects.length) {
        list.innerHTML = '<div style="padding:20px 12px;font-size:12.5px;color:var(--text-muted);text-align:center;">No projects yet.<br>Click + to create one.</div>';
        return;
    }
    projects.forEach(p => {
        const entry = document.createElement('div');
        entry.className = 'project-entry';

        const header = document.createElement('div');
        header.className = 'project-item' + (p.id === currentProjectId ? ' expanded' : '');
        header.dataset.id = p.id;
        header.innerHTML = `<div class="project-chevron">▶</div><div class="project-name">${escHtml(p.name)}</div><button class="project-files-btn" title="Browse files">📁</button>`;
        header.addEventListener('click', () => toggleProject(p.id, p.name));
        header.querySelector('.project-files-btn').addEventListener('click', e => {
            e.stopPropagation();
            openFileBrowser(p.id, p.name);
        });

        const threadList = document.createElement('div');
        threadList.className = 'thread-list';
        threadList.id = `threads-${p.id}`;

        entry.appendChild(header);
        entry.appendChild(threadList);
        list.appendChild(entry);

        if (p.id === currentProjectId) {
            loadThreadsInto(p.id, threadList);
        }
    });
}

async function toggleProject(pid) {
    const header = document.querySelector(`.project-item[data-id="${pid}"]`);
    const threadList = document.getElementById(`threads-${pid}`);
    const isExpanded = header.classList.contains('expanded');

    // Collapse all
    document.querySelectorAll('.project-item').forEach(el => el.classList.remove('expanded'));
    document.querySelectorAll('.thread-list').forEach(el => { el.innerHTML = ''; });

    if (!isExpanded) {
        header.classList.add('expanded');
        currentProjectId = pid;
        const firstThread = await loadThreadsInto(pid, threadList);
        if (firstThread) openThread(firstThread.id, pid, firstThread.title);
    } else {
        currentProjectId = null;
    }
}

async function loadThreadsInto(pid, container) {
    container.innerHTML = '<div class="thread-item" style="opacity:0.5">Loading…</div>';
    try {
        const threads = await apiFetch(`/api/projects/${pid}/threads`);
        container.innerHTML = '';
        let firstThread = null;
        threads.forEach(t => {
            if (!firstThread) firstThread = t;
            const el = document.createElement('div');
            el.className = 'thread-item' + (t.id === currentThreadId ? ' active' : '');
            el.dataset.tid = t.id;
            el.textContent = t.title;
            el.addEventListener('click', (e) => { e.stopPropagation(); openThread(t.id, pid, t.title); });
            container.appendChild(el);
        });
        const newBtn = document.createElement('div');
        newBtn.className = 'new-thread-btn';
        newBtn.textContent = '+ New Thread';
        newBtn.addEventListener('click', (e) => { e.stopPropagation(); openNewThreadModal(pid); });
        container.appendChild(newBtn);
        return firstThread;
    } catch (e) {
        container.innerHTML = `<div class="thread-item" style="color:var(--danger)">Failed to load</div>`;
        return null;
    }
}

// ── Run Project button ────────────────────────────────────────────────────────
async function checkRunScript(pid) {
    const btn = document.getElementById('btn-run-project');
    try {
        const data = await apiFetch(`/api/projects/${pid}/has-run-script`);
        if (data.has_run_script) {
            btn.style.display = 'inline-flex';
            btn.onclick = () => runProjectScript(pid);
        } else {
            btn.style.display = 'none';
        }
    } catch (e) {
        btn.style.display = 'none';
    }
}

async function runProjectScript(pid) {
    const btn = document.getElementById('btn-run-project');
    btn.disabled = true;
    btn.textContent = '⏳ Starting…';
    try {
        const data = await apiFetch(`/api/projects/${pid}/run`, { method: 'POST' });
        if (data.status === 'running') {
            showToast(`✅ Project running (PID: ${data.pid})`);
            loadProcesses();
        } else {
            showToast('Script finished: ' + (data.log || '').substring(0, 100));
        }
    } catch (e) {
        showToast('Run failed: ' + e.message);
    } finally {
        btn.disabled = false;
        btn.textContent = '▶ Run Project';
    }
}

// ── Open a thread ─────────────────────────────────────────────────────────────
async function openThread(tid, pid, title) {
    if (tid === currentThreadId) { closeSidebar(); return; }
    disconnectSSE();
    currentThreadId = tid;
    currentProjectId = pid;
    currentThreadTitle = title;

    document.getElementById('project-title').textContent = title;
    document.getElementById('no-project-state')?.remove();

    document.querySelectorAll('.thread-item').forEach(el => {
        el.classList.toggle('active', parseInt(el.dataset.tid) === tid);
    });

    clearChat();
    setInputEnabled(false);
    setStatus('Loading…', false);

    checkRunScript(pid);

    try {
        const msgs = await apiFetch(`/api/threads/${tid}/messages`);
        msgs.forEach(m => appendMessage(m.role, m.type, m.content, false));
        if (!msgs.length) showEmptyState();
        scrollBottom();

        const status = await apiFetch(`/api/threads/${tid}/agent-status`);
        if (status.running) {
            agentBusy = true;
            setInputEnabled(false);
            setHaltVisible(true);
            setStatus('Thinking…', true);
            appendTypingIndicator();
        } else {
            setInputEnabled(true);
            setStatus('Idle', false);
        }
    } catch (e) {
        showToast('Failed to load messages: ' + e.message);
    }

    connectSSE(tid);
    closeSidebar();
}

// ── Chat rendering ────────────────────────────────────────────────────────────
function clearChat() {
    const area = document.getElementById('chat-area');
    area.innerHTML = '';
    document.getElementById('tool-approval-card').style.display = 'none';
}

function showEmptyState() {
    const area = document.getElementById('chat-area');
    const div = document.createElement('div');
    div.className = 'empty-state';
    div.id = 'empty-state-msg';
    div.innerHTML = `
<div class="empty-state-icon">💬</div>
<h3>Start the conversation</h3>
<p>Describe what you want to build or ask the agent anything about your project.</p>`;
    area.appendChild(div);
}

function removeEmptyState() {
    document.getElementById('empty-state-msg')?.remove();
}

function escHtml(str) {
    return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function toggleToolCode(header) {
    const body = header.nextElementSibling;
    const toggle = header.querySelector('.collapse-toggle');
    body.classList.toggle('collapsed');
    if (toggle) {
        toggle.textContent = body.classList.contains('collapsed') ? '▼' : '▲';
    }
}

function appendMessage(role, type, content, animate = true) {
    removeEmptyState();
    const area = document.getElementById('chat-area');
    const row = document.createElement('div');
    row.className = `msg-row ${role === 'user' ? 'user-row' : 'agent-row'} msg-${type}`;
    if (!animate) row.style.animation = 'none';

    const avatar = document.createElement('div');
    avatar.className = 'msg-avatar';
    avatar.textContent = role === 'user' ? '👤' : '🤖';

    const bubble = document.createElement('div');
    bubble.className = 'msg-bubble';

    if (type === 'tool') {
        const { toolName, toolArg, toolCode } = parseToolCall(content);
        const header = getToolHeader(toolName, toolArg);
        const isLarge = toolCode && toolCode.split('\n').length > 5;
        bubble.innerHTML = `
  <div class="tool-header" onclick="toggleToolCode(this)">
    <span class="tool-icon">${getToolIcon(toolName)}</span>
    <span style="flex:1">${header}</span>
    ${toolCode ? `<span class="collapse-toggle" style="font-size:10px; opacity:0.6; margin-left:8px;">${isLarge ? '▼' : '▲'}</span>` : ''}
  </div>
  <div class="tool-code-block ${isLarge ? 'collapsed' : ''}">${toolCode ? highlightCode(toolCode, toolName, toolArg) : escHtml(content)}</div>`;

        bubble.querySelectorAll('pre code').forEach(el => hljs.highlightElement(el));

    } else if (type === 'tool_result') {
        const isError = content.startsWith('Error [') || content === 'Tool call denied by user.';
        bubble.innerHTML = `
  <div class="result-header" onclick="this.nextElementSibling.classList.toggle('collapsed')">
    <span style="color:${isError ? 'var(--danger)' : 'var(--accent2)'}">${isError ? '❌ Error' : '📤 Result'}</span>
    <span style="margin-left:auto;font-size:11px;opacity:0.6;">▼ click to expand</span>
  </div>
  <div class="result-body collapsed">${escHtml(content)}</div>`;
    } else if (type === 'thought') {
        bubble.innerHTML = renderContent(content);
    } else {
        bubble.innerHTML = renderContent(content);
        bubble.querySelectorAll('pre code').forEach(el => hljs.highlightElement(el));
    }

    row.appendChild(avatar);
    row.appendChild(bubble);
    area.appendChild(row);

    setTimeout(scrollBottom, 30);
    return row;
}

function parseToolCall(str) {
    const match = str.match(/^(\w+)\(([\s\S]*)\)$/);
    if (!match) return { toolName: 'tool', toolArg: '', toolCode: '' };
    const name = match[1];
    const argsStr = match[2];

    const args = [];
    let current = "";
    let inQuote = null;
    let escaped = false;

    for (let i = 0; i < argsStr.length; i++) {
        const c = argsStr[i];
        if (escaped) { current += c; escaped = false; continue; }
        if (c === "\\") { current += c; escaped = true; continue; }

        if (!inQuote) {
            if (argsStr.substring(i, i + 3) === '"""') { inQuote = '"""'; current += '"""'; i += 2; continue; }
            if (argsStr.substring(i, i + 3) === "'''") { inQuote = "'''"; current += "'''"; i += 2; continue; }
        } else if (inQuote === '"""') {
            if (argsStr.substring(i, i + 3) === '"""') { inQuote = null; current += '"""'; i += 2; continue; }
        } else if (inQuote === "'''") {
            if (argsStr.substring(i, i + 3) === "'''") { inQuote = null; current += "'''"; i += 2; continue; }
        }

        if (!inQuote) {
            if (c === '"' || c === "'") { inQuote = c; current += c; continue; }
        } else if (inQuote === '"' || inQuote === "'") {
            if (c === inQuote) { inQuote = null; current += c; continue; }
        }

        if (c === ',' && !inQuote) { args.push(current.trim()); current = ""; }
        else { current += c; }
    }
    if (current.trim()) args.push(current.trim());

    const clean = (s) => {
        if (!s) return "";
        let res = s;
        if (res.startsWith('"""') && res.endsWith('"""')) res = res.substring(3, res.length - 3);
        else if (res.startsWith("'''") && res.endsWith("'''")) res = res.substring(3, res.length - 3);
        else if (res.startsWith('"') && res.endsWith('"')) res = res.substring(1, res.length - 1);
        else if (res.startsWith("'") && res.endsWith("'")) res = res.substring(1, res.length - 1);
        return res.replace(/\\n/g, '\n').replace(/\\r/g, '\r').replace(/\\"/g, '"').replace(/\\'/g, "'").replace(/\\\\/g, '\\');
    };

    try {
        if (name === 'edit_file' && args.length >= 2) {
            return { toolName: name, toolArg: clean(args[0]), toolCode: clean(args[1]) };
        }
        if (name === 'python_tool' && args.length >= 1) {
            return { toolName: name, toolArg: '', toolCode: clean(args[0]) };
        }
        if ((name === 'read_file' || name === 'run_project' || name === 'list_dir') && args.length >= 1) {
            return { toolName: name, toolArg: clean(args[0]), toolCode: '' };
        }
        if (name === 'stop_process' && args.length >= 1) {
            return { toolName: name, toolArg: clean(args[0]), toolCode: '' };
        }
    } catch (e) { console.warn("Parse error", e); }

    return { toolName: name, toolArg: '', toolCode: argsStr };
}

function getToolHeader(name, arg) {
    const map = {
        'edit_file': 'Edit File:', 'read_file': 'Read File:', 'list_dir': 'List Directory:',
        'run_project': 'Running:', 'pip_install': 'Pip Install:', 'python_tool': 'Python Script',
        'code_search': 'Searching Code', 'stop_process': 'Stop Process:'
    };
    let h = map[name] || 'Tool Call:';
    if (arg) h += ` <span class="tool-file-hint">${escHtml(arg)}</span>`;
    return h;
}

function getToolIcon(name) {
    const map = {
        'edit_file': '📝', 'read_file': '📖', 'list_dir': '📁', 'run_project': '🚀',
        'pip_install': '📦', 'python_tool': '🐍', 'code_search': '🔍', 'stop_process': '🛑'
    };
    return map[name] || '🔧';
}

function getToolLabel(name, arg) {
    const map = {
        'edit_file': 'Edit File', 'read_file': 'Read File', 'list_dir': 'List Directory',
        'run_project': 'Run Project', 'pip_install': 'Pip Install', 'python_tool': 'Run Python Script',
        'code_search': 'Search Code', 'stop_process': 'Stop Process'
    };
    let h = map[name] || 'Tool Call';
    if (arg) h += `: ${arg}`;
    return h;
}

function highlightCode(code, toolName, toolArg) {
    let lang = 'python';
    const arg = (toolArg || '').toLowerCase();
    if (arg.endsWith('.html') || arg.endsWith('.htm')) lang = 'html';
    else if (arg.endsWith('.js')) lang = 'javascript';
    else if (arg.endsWith('.css')) lang = 'css';
    else if (arg.endsWith('.md')) lang = 'markdown';
    else if (toolName === 'edit_file' || toolName === 'python_tool') {
        if (code.includes('<!DOCTYPE html>') || code.includes('<html')) lang = 'html';
        else if (code.includes('import ') || code.includes('def ')) lang = 'python';
    }
    const escaped = escHtml(code);
    return `<pre><code class="language-${lang}">${escaped}</code></pre>`;
}

function renderContent(text) {
    text = text.replace(/```(\w*)\n?([\s\S]*?)```/g, (_, lang, code) => {
        const l = lang || 'python';
        return `<pre><code class="language-${l}">${escHtml(code.trim())}</code></pre>`;
    });
    text = text.replace(/`([^`]+)`/g, '<code>$1</code>');
    text = text.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    text = text.replace(/\*(.*?)\*/g, '<em>$1</em>');
    text = text.replace(/\n/g, '<br>');
    return text;
}

function appendTypingIndicator() {
    if (document.querySelector('.typing-indicator')) return;
    const area = document.getElementById('chat-area');
    const row = document.createElement('div');
    row.className = 'msg-row agent-row typing-indicator-row';
    row.innerHTML = `
<div class="msg-avatar">🤖</div>
<div class="msg-bubble" style="padding:0">
  <div class="typing-indicator">
    <span></span><span></span><span></span>
  </div>
</div>`;
    area.appendChild(row);
    scrollBottom();
}

function removeTypingIndicator() {
    document.querySelectorAll('.typing-indicator-row').forEach(row => row.remove());
}

// ── SSE ───────────────────────────────────────────────────────────────────────
function connectSSE(threadId) {
    disconnectSSE();
    eventSource = new EventSource(`/api/threads/${threadId}/stream`);

    eventSource.onmessage = function (e) {
        const data = JSON.parse(e.data);
        if (data.type === 'connected' || data.type === 'ping') return;

        if (data.type === 'done') {
            removeTypingIndicator();
            agentBusy = false;
            setInputEnabled(true);
            setHaltVisible(false);
            setStatus('Idle', false);
            stopToolPolling();
            document.getElementById('tool-approval-card').style.display = 'none';
            disconnectSSE();
            return;
        }

        removeTypingIndicator();
        if (data.type === 'tool') {
            showApprovalCard(data.content);
        } else {
            hideApprovalCard();
        }
        appendMessage('assistant', data.type, data.content);

        if (data.type !== 'complete' && data.type !== 'done') {
            appendTypingIndicator();
        }
    };

    eventSource.onerror = function () {
        removeTypingIndicator();
        if (agentBusy) {
            agentBusy = false;
            setInputEnabled(true);
            setHaltVisible(false);
            setStatus('Idle', false);
        }
        stopToolPolling();
    };
}

function disconnectSSE() {
    if (eventSource) { eventSource.close(); eventSource = null; }
}

// ── Tool Approval ─────────────────────────────────────────────────────────────
function showApprovalCard(toolContent) {
    const card = document.getElementById('tool-approval-card');
    const { toolName, toolArg } = parseToolCall(toolContent);
    document.getElementById('approval-code').textContent = getToolLabel(toolName, toolArg);
    card.style.display = 'block';
}

function hideApprovalCard() {
    document.getElementById('tool-approval-card').style.display = 'none';
}

async function respondToTool(decision) {
    if (!currentThreadId) return;
    hideApprovalCard();
    try {
        await apiFetch(`/api/threads/${currentThreadId}/approve-tool`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ decision })
        });
        if (decision === 'stop') {
            removeTypingIndicator();
            setStatus('Stopping…', true);
        } else {
            appendTypingIndicator();
        }
    } catch (e) {
        showToast('Error: ' + e.message);
    }
}

function startToolPolling() { stopToolPolling(); }
function stopToolPolling() {
    if (pollInterval) { clearInterval(pollInterval); pollInterval = null; }
}

document.getElementById('btn-approve').addEventListener('click', () => respondToTool('approve'));
document.getElementById('btn-deny').addEventListener('click', () => respondToTool('deny'));
document.getElementById('btn-stop').addEventListener('click', () => respondToTool('stop'));

// ── Halt agent ────────────────────────────────────────────────────────────────
async function haltAgent() {
    if (!currentThreadId) return;
    setHaltVisible(false);
    setStatus('Halting…', true);
    try {
        await apiFetch(`/api/threads/${currentThreadId}/halt`, { method: 'POST' });
    } catch (e) {
        showToast('Halt error: ' + e.message);
    }
}

document.getElementById('btn-halt').addEventListener('click', haltAgent);

// ── Sending messages ──────────────────────────────────────────────────────────
async function sendMessage() {
    const input = document.getElementById('msg-input');
    const text = input.value.trim();
    if (!text || !currentThreadId || agentBusy) return;

    input.value = '';
    autoResize(input);
    agentBusy = true;
    setInputEnabled(false);
    setHaltVisible(true);
    setStatus('Thinking…', true);

    appendMessage('user', 'text', text);
    appendTypingIndicator();
    disconnectSSE();

    try {
        await apiFetch(`/api/threads/${currentThreadId}/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: text })
        });
        connectSSE(currentThreadId);
    } catch (e) {
        removeTypingIndicator();
        agentBusy = false;
        setInputEnabled(true);
        setHaltVisible(false);
        setStatus('Idle', false);
        disconnectSSE();
        showToast('Error: ' + e.message);
    }
}

document.getElementById('btn-send').addEventListener('click', sendMessage);
document.getElementById('msg-input').addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
});
document.getElementById('msg-input').addEventListener('input', function () { autoResize(this); });

// ── New Project Modal ─────────────────────────────────────────────────────────
function openModal() {
    document.getElementById('modal-overlay').classList.add('open');
    document.getElementById('new-project-name').value = '';
    setTimeout(() => document.getElementById('new-project-name').focus(), 50);
}
function closeModal() {
    document.getElementById('modal-overlay').classList.remove('open');
}

document.getElementById('btn-new-project').addEventListener('click', openModal);
document.getElementById('btn-modal-cancel').addEventListener('click', closeModal);
document.getElementById('modal-overlay').addEventListener('click', e => {
    if (e.target === document.getElementById('modal-overlay')) closeModal();
});
document.getElementById('new-project-name').addEventListener('keydown', e => {
    if (e.key === 'Enter') createProject();
});

async function createProject() {
    const inp = document.getElementById('new-project-name');
    const name = inp.value.trim();
    if (!name) { inp.focus(); return; }

    const btn = document.getElementById('btn-modal-create');
    btn.disabled = true; btn.textContent = 'Creating…';

    try {
        const p = await apiFetch('/api/projects', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name })
        });
        closeModal();
        await loadProjects();
        showToast(`✅ "${p.name}" created ${p.venv_created ? '(venv ready)' : '(venv setup failed)'}`);
        openThread(p.default_thread_id, p.id, 'Main Thread');
    } catch (e) {
        showToast('Error: ' + e.message);
    } finally {
        btn.disabled = false; btn.textContent = 'Create Project';
    }
}

document.getElementById('btn-modal-create').addEventListener('click', createProject);

// ── New Thread Modal ──────────────────────────────────────────────────────────
let _newThreadPid = null;

function openNewThreadModal(pid) {
    _newThreadPid = pid;
    document.getElementById('thread-modal-overlay').classList.add('open');
    document.getElementById('new-thread-title').value = '';
    setTimeout(() => document.getElementById('new-thread-title').focus(), 50);
}
function closeThreadModal() {
    document.getElementById('thread-modal-overlay').classList.remove('open');
    _newThreadPid = null;
}

document.getElementById('btn-thread-modal-cancel').addEventListener('click', closeThreadModal);
document.getElementById('thread-modal-overlay').addEventListener('click', e => {
    if (e.target === document.getElementById('thread-modal-overlay')) closeThreadModal();
});
document.getElementById('new-thread-title').addEventListener('keydown', e => {
    if (e.key === 'Enter') createThread();
});

async function createThread() {
    const inp = document.getElementById('new-thread-title');
    const title = inp.value.trim();
    if (!title || !_newThreadPid) { inp.focus(); return; }

    const btn = document.getElementById('btn-thread-modal-create');
    btn.disabled = true; btn.textContent = 'Creating…';

    try {
        const t = await apiFetch(`/api/projects/${_newThreadPid}/threads`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title })
        });
        const pid = _newThreadPid;
        closeThreadModal();
        const container = document.getElementById(`threads-${pid}`);
        if (container) await loadThreadsInto(pid, container);
        openThread(t.id, pid, t.title);
    } catch (e) {
        showToast('Error: ' + e.message);
    } finally {
        btn.disabled = false; btn.textContent = 'Create Thread';
    }
}

document.getElementById('btn-thread-modal-create').addEventListener('click', createThread);

// ── File Browser ──────────────────────────────────────────────────────────────
let fbPid = null, fbProjectName = '', fbPath = '';

function openFileBrowser(pid, name) {
    fbPid = pid; fbProjectName = name; fbPath = '';
    document.getElementById('fb-title').textContent = name;
    document.getElementById('fb-overlay').classList.add('open');
    loadFBDir('');
}

function closeFB() {
    document.getElementById('fb-overlay').classList.remove('open');
}

async function loadFBDir(rel) {
    fbPath = rel;
    document.getElementById('fb-breadcrumb').textContent = '/' + rel;
    const list = document.getElementById('fb-list');
    list.innerHTML = '<div style="padding:8px; opacity:0.5; font-size:12px;">Loading…</div>';
    try {
        const data = await apiFetch(`/api/projects/${fbPid}/files?path=${encodeURIComponent(rel)}`);
        list.innerHTML = '';

        if (rel) {
            const up = document.createElement('div');
            up.className = 'fb-entry fb-dir';
            up.innerHTML = `<span class="fb-icon">📁</span><span class="fb-name">..</span>`;
            up.addEventListener('click', () => {
                const parent = rel.includes('/') ? rel.substring(0, rel.lastIndexOf('/')) : '';
                loadFBDir(parent);
            });
            list.appendChild(up);
        }

        if (!data.entries.length && !rel) {
            list.innerHTML = '<div style="padding:8px; opacity:0.5; font-size:12px;">Empty directory.</div>';
            return;
        }

        data.entries.forEach(e => {
            const fullRel = rel ? `${rel}/${e.name}` : e.name;
            const row = document.createElement('div');
            row.className = 'fb-entry' + (e.is_dir ? ' fb-dir' : '');
            row.innerHTML = `
                <span class="fb-icon">${e.is_dir ? '📁' : '📄'}</span>
                <span class="fb-name">${escHtml(e.name)}</span>
                ${!e.is_dir ? `<button class="fb-del-btn" data-rel="${escHtml(fullRel)}" title="Delete">🗑</button>` : ''}
            `;
            if (e.is_dir) {
                row.addEventListener('click', () => loadFBDir(fullRel));
            } else {
                row.querySelector('.fb-name').style.cursor = 'pointer';
                row.querySelector('.fb-name').addEventListener('click', () => {
                    window.location.href = `/api/projects/${fbPid}/files/download?path=${encodeURIComponent(fullRel)}`;
                });
                row.querySelector('.fb-del-btn').addEventListener('click', async (ev) => {
                    ev.stopPropagation();
                    if (!confirm(`Delete "${e.name}"?`)) return;
                    await apiFetch(`/api/projects/${fbPid}/files/delete?path=${encodeURIComponent(fullRel)}`, { method: 'DELETE' });
                    loadFBDir(fbPath);
                });
            }
            list.appendChild(row);
        });
    } catch (err) {
        list.innerHTML = `<div style="padding:8px; color:var(--danger); font-size:12px;">Error: ${escHtml(err.message)}</div>`;
    }
}

document.getElementById('fb-close-btn').addEventListener('click', closeFB);
document.getElementById('fb-overlay').addEventListener('click', e => {
    if (e.target === document.getElementById('fb-overlay')) closeFB();
});

const fbUploadInput = document.getElementById('fb-upload-input');
document.getElementById('fb-upload-btn').addEventListener('click', () => fbUploadInput.click());
fbUploadInput.addEventListener('change', async () => {
    const file = fbUploadInput.files[0];
    if (!file) return;
    const form = new FormData();
    form.append('file', file);
    form.append('path', fbPath);
    fbUploadInput.value = '';
    try {
        const resp = await fetch(`/api/projects/${fbPid}/files/upload`, { method: 'POST', body: form });
        if (!resp.ok) throw new Error((await resp.json()).error || resp.statusText);
        loadFBDir(fbPath);
    } catch (e) {
        showToast('Upload failed: ' + e.message);
    }
});

// ── Sidebar (mobile) ──────────────────────────────────────────────────────────
function closeSidebar() {
    document.getElementById('sidebar').classList.remove('open');
    document.getElementById('sidebar-overlay').classList.remove('open');
}
document.getElementById('hamburger').addEventListener('click', () => {
    document.getElementById('sidebar').classList.toggle('open');
    document.getElementById('sidebar-overlay').classList.toggle('open');
});
document.getElementById('sidebar-overlay').addEventListener('click', closeSidebar);

// ── Processes ─────────────────────────────────────────────────────────────
async function loadProcesses() {
    try {
        const procs = await fetch('/api/processes').then(r => r.json());
        const list = document.getElementById('proc-list');
        const count = document.getElementById('proc-count');

        list.innerHTML = '';
        count.innerText = procs.length;
        count.style.display = procs.length > 0 ? 'inline-block' : 'none';

        if (procs.length === 0) {
            list.innerHTML = '<div style="padding:20px; font-size:11px; color:var(--text-muted); text-align:center;">No processes running.</div>';
            return;
        }

        procs.forEach(p => {
            const el = document.createElement('div');
            el.className = 'proc-item';
            const projectLabel = p.project ? `${escHtml(p.project)} — ` : '';
            el.innerHTML = `
        <div class="proc-info">
            <div class="proc-title">${projectLabel}${escHtml(p.script)}</div>
            <div class="proc-meta">PID: ${p.pid} · Started ${escHtml(p.started_at)}</div>
        </div>
        <button class="btn-kill" onclick="killProcess(${p.pid})">Kill</button>
    `;
            list.appendChild(el);
        });
    } catch (e) { }
}

async function killProcess(pid) {
    await fetch(`/api/processes/${pid}`, { method: 'DELETE' });
    loadProcesses();
}

function toggleProcs() {
    document.getElementById('processes-panel').classList.toggle('open');
}
document.getElementById('btn-toggle-procs').addEventListener('click', toggleProcs);

// ── Init ──────────────────────────────────────────────────────────────────────
async function init() {
    // Check if API key is configured; redirect to admin setup if not
    try {
        const status = await apiFetch('/api/settings/status');
        if (!status.configured) {
            window.location.href = '/admin?setup=1';
            return;
        }
    } catch (e) { }

    loadProjects();
    setInterval(loadProcesses, 5000);
    loadProcesses();
}

init();
