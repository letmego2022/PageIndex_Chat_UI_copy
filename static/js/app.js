/**
 * PageIndex Chat UI - Frontend Application
 */

// Socket.IO connection
let socket;
let currentDocId = null;
let currentModelType = 'text';
let useMemory = true;
let isStreaming = false;

// Node info cache
let nodeMapCache = {};
let allPagesCache = {};

window.onerror = function(msg, url, line, col, error) {
    console.error('Global JS Error:', msg, 'at', line, ':', col);
    alert('JavaScript Error: ' + msg + ' at line ' + line);
    return false;
};

// Initialize application
document.addEventListener('DOMContentLoaded', () => {
    console.log('DOM Content Loaded, starting init...');
    console.log('Marked library status:', typeof marked !== 'undefined' ? 'Loaded' : 'Missing');
    
    // Load documents first as it's most critical
    try {
        loadDocuments();
        console.log('Documents loading started');
    } catch (e) {
        console.error('Document loading failed:', e);
    }

    try {
        initSocket();
        console.log('Socket initialized');
    } catch (e) {
        console.error('Socket init failed:', e);
    }
    
    try {
        loadConfig();
        setupDragDrop();
        setupEventListeners();
        console.log('PageIndex App Initialized');
    } catch (e) {
        console.error('General initialization failed:', e);
    }
});

// Setup event listeners
function setupEventListeners() {
    // Model toggle buttons
    const textModelBtn = document.getElementById('textModelBtn');
    const visionModelBtn = document.getElementById('visionModelBtn');

    if (textModelBtn) {
        textModelBtn.addEventListener('click', () => switchModel('text'));
    }

    if (visionModelBtn) {
        visionModelBtn.addEventListener('click', () => switchModel('vision'));
    }

    // Settings button
    const settingsBtn = document.getElementById('settingsBtn');
    if (settingsBtn) {
        settingsBtn.addEventListener('click', openSettingsModal);
    }

    // Memory toggle
    const memoryToggle = document.getElementById('memoryToggle');
    if (memoryToggle) {
        memoryToggle.addEventListener('change', (e) => toggleMemory(e.target.checked));
    }

    // Upload area
    const uploadArea = document.getElementById('uploadArea');
    const fileInput = document.getElementById('fileInput');
    if (uploadArea && fileInput) {
        uploadArea.addEventListener('click', () => fileInput.click());
        fileInput.addEventListener('change', (e) => {
            if (e.target.files && e.target.files[0]) {
                uploadDocument(e.target.files[0]);
            }
        });
    }

    // Chat input
    const chatInput = document.getElementById('chatInput');
    const sendBtn = document.getElementById('sendBtn');
    if (chatInput) {
        chatInput.addEventListener('keydown', handleKeyDown);
    }
    if (sendBtn) {
        sendBtn.addEventListener('click', sendMessage);
    }

    // Save settings button
    const saveSettingsBtn = document.getElementById('saveSettingsBtn');
    if (saveSettingsBtn) {
        saveSettingsBtn.addEventListener('click', saveSettings);
    }
}

// Initialize Socket.IO
function initSocket() {
    if (typeof io === 'undefined') {
        console.error('Socket.IO (io) is not defined! Check CDN link.');
        return;
    }
    socket = io();

    socket.on('connect', () => console.log('Connected to server'));
    
    socket.on('status', (data) => updateStatus(data.status));
    
    socket.on('thinking_chunk', (data) => appendToThinking(data.content));
    
    socket.on('thinking', (data) => {
        const box = document.getElementById('thinkingBox');
        if (box) box.querySelector('.thinking-content').textContent = data.content;
    });

    socket.on('nodes', (data) => showNodes(data.nodes));

    socket.on('chunk', (data) => appendToResponse(data.content));

    socket.on('response', (data) => {
        const typing = document.getElementById('typingIndicator');
        if (typing) typing.remove();
        addUserMessage(data.content, 'assistant'); // Fallback for full sync response
    });

    socket.on('done', () => finishResponse());

    socket.on('error', (data) => showError(data.message));

    socket.on('history', (data) => displayHistory(data.history));

    socket.on('history_cleared', (data) => {
        if (currentDocId === data.doc_id) clearChatDisplay();
    });

    socket.on('indexing_progress', (data) => handleIndexingProgress(data));
}

// ============= Document Management =============

async function loadDocuments() {
    try {
        console.log('Fetching documents...');
        const response = await fetch('/api/documents');
        if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
        const data = await response.json();
        console.log('Received documents:', data.documents);
        renderDocuments(data.documents);
    } catch (error) {
        console.error('Error loading documents:', error);
        // Show error in the list container
        const container = document.getElementById('documentList');
        if (container) container.innerHTML = `<div style="color: #fca5a5; padding: 10px;">加载失败: ${error.message}</div>`;
    }
}

function renderDocuments(documents) {
    console.log('Rendering documents:', documents);
    const container = document.getElementById('documentList');
    if (!container) {
        console.error('documentList container not found in DOM');
        return;
    }

    if (!documents || !Array.isArray(documents) || documents.length === 0) {
        console.log('No documents to render');
        container.innerHTML = '<div style="text-align: center; padding: 20px; opacity: 0.5;">暂无文档</div>';
        return;
    }

    container.innerHTML = documents.map(doc => `
        <div class="doc-item ${doc.doc_id === currentDocId ? 'active' : ''}" data-doc-id="${doc.doc_id}">
            <div class="doc-name">${doc.filename}</div>
            <div class="doc-status">
                <span class="status-badge status-${doc.status}"></span>
                ${getStatusText(doc.status)}
            </div>
            <div class="doc-actions">
                <button class="doc-action-btn delete" onclick="event.stopPropagation(); deleteDocument('${doc.doc_id}', '${doc.filename}')">
                    <i class="bi bi-trash"></i>
                </button>
            </div>
        </div>
    `).join('');

    container.querySelectorAll('.doc-item').forEach(item => {
        item.addEventListener('click', () => selectDocument(item.dataset.docId));
    });
}

function getStatusText(status) {
    const map = { 'pending': '等待', 'indexing': '索引中', 'indexed': '完成', 'ready': '就绪', 'error': '错误' };
    return map[status] || status;
}

async function selectDocument(docId) {
    currentDocId = docId;
    document.querySelectorAll('.doc-item').forEach(item => {
        item.classList.toggle('active', item.dataset.docId === docId);
    });
    clearChatDisplay();
    socket.emit('get_history', { doc_id: docId });
    hideEmptyState();
}

async function uploadDocument(file) {
    const filename = file.name.toLowerCase();
    if (!file || !(filename.endsWith('.pdf') || filename.endsWith('.md'))) {
        alert('请选择 PDF 或 Markdown 文件');
        return;
    }

    const formData = new FormData();
    formData.append('file', file);

    try {
        const response = await fetch('/api/documents/upload', { method: 'POST', body: formData });
        const data = await response.json();
        if (data.success) {
            currentDocId = data.document.doc_id;
            loadDocuments();
            pollDocumentStatus(data.document.doc_id);
        } else {
            alert('上传失败: ' + data.error);
        }
    } catch (error) {
        alert('上传过程中发生错误');
    }
}

async function pollDocumentStatus(docId) {
    const interval = setInterval(async () => {
        const res = await fetch(`/api/documents/${docId}/status`);
        const data = await res.json();
        loadDocuments();
        if (data.status === 'ready' || data.status === 'error') {
            clearInterval(interval);
            if (data.status === 'ready') {
                const pm = document.getElementById('indexingProgressMessage');
                if (pm) pm.remove();
                addSystemMessage('文档索引完成！');
            }
        }
    }, 2000);
}

async function deleteDocument(docId, filename) {
    if (!confirm(`确定删除 ${filename}?`)) return;
    await fetch(`/api/documents/${docId}`, { method: 'DELETE' });
    if (currentDocId === docId) currentDocId = null;
    loadDocuments();
    clearChatDisplay();
}

// ============= Chat Interaction =============

function sendMessage() {
    const input = document.getElementById('chatInput');
    const msg = input.value.trim();
    if (!msg || isStreaming || !currentDocId) return;

    addUserMessage(msg);
    input.value = '';
    showTypingIndicator();
    isStreaming = true;
    updateSendButton();
    
    socket.emit(currentModelType === 'text' ? 'chat' : 'chat_sync', {
        doc_id: currentDocId,
        query: msg,
        model_type: currentModelType,
        use_memory: useMemory
    });
}

function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
}

function appendToThinking(content) {
    let box = document.getElementById('thinkingBox');
    if (!box) {
        // Find existing nodes box or typing indicator to determine insertion point
        const typing = document.getElementById('typingIndicator');
        const messagesContainer = document.getElementById('chatMessages');
        
        box = document.createElement('div');
        box.className = 'thinking-box';
        box.id = 'thinkingBox';
        box.innerHTML = '<strong>推理过程</strong><span class="thinking-content"></span>';
        
        if (typing) {
            typing.before(box);
        } else {
            messagesContainer.appendChild(box);
        }
    }
    box.querySelector('.thinking-content').textContent += content;
    scrollToBottom();
}

function showNodes(nodes) {
    const thinkingBox = document.getElementById('thinkingBox');
    const nodesHtml = `
        <div class="nodes-box">
            <strong>检索节点:</strong> ${nodes.map(n => `<span class="node-tag" onclick="showNodePreview('${n}')">${n}</span>`).join(' ')}
        </div>
    `;
    if (thinkingBox) thinkingBox.insertAdjacentHTML('afterend', nodesHtml);
    scrollToBottom();
}

function appendToResponse(content) {
    let resp = document.getElementById('responseContent');
    if (!resp) {
        const typing = document.getElementById('typingIndicator');
        const messagesContainer = document.getElementById('chatMessages');
        
        const div = document.createElement('div');
        div.className = 'message message-assistant';
        div.innerHTML = '<div class="message-content markdown-body" id="responseContent"></div>';
        
        if (typing) {
            typing.before(div);
        } else {
            messagesContainer.appendChild(div);
        }
        
        resp = document.getElementById('responseContent');
    }
    
    const currentRaw = (resp.getAttribute('data-raw') || "") + content;
    resp.setAttribute('data-raw', currentRaw);
    
    resp.innerHTML = safeMarkedParse(currentRaw);
    scrollToBottom();
}

function finishResponse() {
    isStreaming = false;
    updateSendButton();
    
    // Remove ids to avoid conflicts with future messages
    const resp = document.getElementById('responseContent');
    if (resp) {
        resp.removeAttribute('id');
        resp.removeAttribute('data-raw');
    }
    
    const think = document.getElementById('thinkingBox');
    if (think) {
        think.removeAttribute('id');
    }
    
    const typing = document.getElementById('typingIndicator');
    if (typing) {
        typing.remove();
    }
}

// ============= Preview Logic =============

async function showNodePreview(nodeId) {
    if (!nodeMapCache[currentDocId]) {
        const res = await fetch(`/api/documents/${currentDocId}/node-info`);
        const data = await res.json();
        nodeMapCache[currentDocId] = data.node_map;
        allPagesCache[currentDocId] = data.all_pages;
    }

    const info = nodeMapCache[currentDocId][nodeId];
    if (!info) return;

    const activeDoc = document.querySelector(`.doc-item[data-doc-id="${currentDocId}"]`);
    const isMarkdown = activeDoc?.querySelector('.doc-name').textContent.toLowerCase().endsWith('.md');

    let modal = document.getElementById('pagePreviewModal');
    if (!modal) {
        modal = document.createElement('div');
        modal.id = 'pagePreviewModal';
        modal.className = 'page-preview-modal';
        modal.innerHTML = `
            <div id="sidebarResizeHandle" class="resize-handle"></div>
            <div class="page-preview-header">
                <h5 class="page-preview-title"></h5>
                <button class="btn-close" onclick="closePagePreviewModal()"></button>
            </div>
            <div class="page-preview-body"></div>
            <div class="page-preview-footer" style="padding: 10px; border-top: 1px solid #eee; display: flex; justify-content: center; gap: 10px;">
                <button class="btn btn-sm btn-outline-secondary" onclick="navigatePreviewPage(-1)">上一页</button>
                <span id="pageIndicator"></span>
                <button class="btn btn-sm btn-outline-secondary" onclick="navigatePreviewPage(1)">下一页</button>
            </div>
        `;
        document.body.appendChild(modal);
        initSidebarResizing();
    }

    modal.querySelector('.page-preview-title').textContent = `节点: ${nodeId} - ${info.title}`;
    const body = modal.querySelector('.page-preview-body');
    const footer = modal.querySelector('.page-preview-footer');

    if (isMarkdown) {
        footer.style.display = 'none';
        const mdContent = info.text || '';
        body.innerHTML = `<div class="markdown-body" style="padding: 20px;">${safeMarkedParse(mdContent)}</div>`;
    } else {
        footer.style.display = 'flex';
        const pages = allPagesCache[currentDocId];
        body.innerHTML = pages.map(p => `
            <div class="page-img-container" data-page="${p.page}" style="margin-bottom: 10px; text-align: center;">
                <img src="${p.url}" style="max-width: 100%; box-shadow: 0 2px 10px rgba(0,0,0,0.1);">
                <div style="font-size: 12px; color: #666; margin-top: 5px;">第 ${p.page} 页</div>
            </div>
        `).join('');
        
        modal.dataset.pages = JSON.stringify(pages);
        modal.dataset.currentIndex = (info.start_index || 1) - 1;
        updatePreviewNavigation();
        
        setTimeout(() => {
            const target = body.querySelectorAll('.page-img-container')[modal.dataset.currentIndex];
            if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }, 100);
    }

    modal.classList.add('active');
    document.querySelector('.main-content').classList.add('preview-open');
    document.querySelector('.main-content').style.marginRight = getComputedStyle(modal).width;
}

function closePagePreviewModal() {
    const modal = document.getElementById('pagePreviewModal');
    if (modal) modal.classList.remove('active');
    const main = document.querySelector('.main-content');
    if (main) { main.classList.remove('preview-open'); main.style.marginRight = ''; }
}

function navigatePreviewPage(dir) {
    const modal = document.getElementById('pagePreviewModal');
    const pages = JSON.parse(modal.dataset.pages);
    let idx = parseInt(modal.dataset.currentIndex) + dir;
    if (idx >= 0 && idx < pages.length) {
        modal.dataset.currentIndex = idx;
        const target = modal.querySelector(`.page-img-container[data-page="${pages[idx].page}"]`);
        if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
        updatePreviewNavigation();
    }
}

function updatePreviewNavigation() {
    const modal = document.getElementById('pagePreviewModal');
    const pages = JSON.parse(modal.dataset.pages);
    const idx = parseInt(modal.dataset.currentIndex);
    document.getElementById('pageIndicator').textContent = `${idx + 1} / ${pages.length}`;
}

// ============= Settings & UI Helpers =============

async function loadConfig() {
    const res = await fetch('/api/config/models');
    const data = await res.json();
    const t = data.models.text || {};
    const v = data.models.vision || {};
    document.getElementById('textModelName').value = t.name || '';
    document.getElementById('textApiKey').value = t.api_key || '';
    document.getElementById('textBaseUrl').value = t.base_url || '';
    document.getElementById('visionModelName').value = v.name || '';
    document.getElementById('visionApiKey').value = v.api_key || '';
    document.getElementById('visionBaseUrl').value = v.base_url || '';
}

async function saveSettings() {
    const configs = {
        text: { name: document.getElementById('textModelName').value, api_key: document.getElementById('textApiKey').value, base_url: document.getElementById('textBaseUrl').value, type: 'text' },
        vision: { name: document.getElementById('visionModelName').value, api_key: document.getElementById('visionApiKey').value, base_url: document.getElementById('visionBaseUrl').value, type: 'vision' }
    };
    await fetch('/api/config/models/text', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(configs.text) });
    await fetch('/api/config/models/vision', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(configs.vision) });
    bootstrap.Modal.getInstance(document.getElementById('settingsModal')).hide();
    showNotification('配置已保存');
}

function switchModel(type) {
    currentModelType = type;
    updateModelToggle();
}

function updateModelToggle() {
    const t = document.getElementById('textModelBtn');
    const v = document.getElementById('visionModelBtn');
    if (t) t.classList.toggle('active', currentModelType === 'text');
    if (v) v.classList.toggle('active', currentModelType === 'vision');
}

function toggleMemory(enabled) {
    useMemory = enabled;
    console.log('Conversation memory:', useMemory ? 'Enabled' : 'Disabled');
}

function handleIndexingProgress(data) {
    const { doc_id, current, total, phase, detail } = data;
    const item = document.querySelector(`.doc-item[data-doc-id="${doc_id}"]`);
    if (item) {
        const percent = total > 0 ? Math.round((current / total) * 100) : 0;
        item.querySelector('.doc-status').innerHTML = `<span class="status-badge status-indexing"></span> ${phase}: ${percent}%`;
    }
    if (currentDocId === doc_id) updateProgressCard(data);
}

function updateProgressCard(data) {
    let card = document.getElementById('indexingProgressMessage');
    if (!card) {
        hideEmptyState();
        card = document.createElement('div');
        card.id = 'indexingProgressMessage';
        card.className = 'message message-assistant';
        document.getElementById('chatMessages').appendChild(card);
    }
    const percent = data.total > 0 ? Math.round((data.current / data.total) * 100) : 0;
    card.innerHTML = `
        <div class="message-content" style="background: #f0f9ff; border: 1px solid #bae6fd; color: #0369a1; width: 100%;">
            <div style="display: flex; justify-content: space-between; margin-bottom: 8px;">
                <strong><i class="bi bi-gear-fill"></i> ${data.phase}</strong>
                <span>${data.current}/${data.total}</span>
            </div>
            <div class="progress" style="height: 6px; background: #e0f2fe; border-radius: 3px; overflow: hidden;">
                <div class="progress-bar" style="width: ${percent}%; background: #0ea5e9; height: 100%;"></div>
            </div>
            <div style="font-size: 12px; margin-top: 5px; opacity: 0.8;">${data.detail || ''}</div>
        </div>
    `;
    scrollToBottom();
}

// Display chat history
function displayHistory(history) {
    console.log('Displaying history:', history);
    if (!history) return;
    const container = document.getElementById('chatMessages');
    container.innerHTML = '';
    history.forEach(msg => {
        if (msg.thinking) {
            const t = document.createElement('div');
            t.className = 'thinking-box';
            t.innerHTML = `<strong>推理过程</strong><span class="thinking-content">${escapeHtml(msg.thinking)}</span>`;
            container.appendChild(t);
        }
        if (msg.nodes && msg.nodes.length > 0) {
            const n = document.createElement('div');
            n.className = 'nodes-box';
            n.innerHTML = `<strong>检索节点:</strong> ${msg.nodes.map(node => `<span class="node-tag" onclick="showNodePreview('${node}')">${node}</span>`).join(' ')}`;
            container.appendChild(n);
        }
        addUserMessage(msg.content, msg.role);
    });
    scrollToBottom();
}

function safeMarkedParse(content) {
    if (typeof marked === 'undefined') return content;
    try {
        if (typeof marked.parse === 'function') {
            return marked.parse(content);
        } else if (typeof marked === 'function') {
            return marked(content);
        }
    } catch (e) {
        console.error('Marked parse error:', e);
    }
    return content;
}

function addUserMessage(content, role = 'user') {
    hideEmptyState();
    const div = document.createElement('div');
    div.className = `message message-${role}`;
    const bodyClass = role === 'assistant' ? 'markdown-body' : '';
    
    let bodyContent = role === 'assistant' ? safeMarkedParse(content) : escapeHtml(content);
    
    div.innerHTML = `<div class="message-content ${bodyClass}">${bodyContent}</div>`;
    document.getElementById('chatMessages').appendChild(div);
    scrollToBottom();
}

function addSystemMessage(msg) {
    const div = document.createElement('div');
    div.className = 'message message-assistant';
    div.innerHTML = `<div class="message-content" style="background: #fef3c7; color: #92400e;">${msg}</div>`;
    document.getElementById('chatMessages').appendChild(div);
    scrollToBottom();
}

function showTypingIndicator() {
    const div = document.createElement('div');
    div.className = 'typing-indicator';
    div.id = 'typingIndicator';
    div.innerHTML = '<span class="typing-dot"></span><span class="typing-dot"></span><span class="typing-dot"></span><span class="status-text" style="margin-left:10px"></span>';
    document.getElementById('chatMessages').appendChild(div);
    scrollToBottom();
}

function updateStatus(status) {
    const el = document.querySelector('#typingIndicator .status-text');
    if (el) {
        const map = { 'preparing': '准备数据...', 'searching': '检索树中...', 'answering': '生成回答...' };
        el.textContent = map[status] || '';
    }
}

function updateSendButton() { document.getElementById('sendBtn').disabled = isStreaming; }

function clearChatDisplay() {
    document.getElementById('chatMessages').innerHTML = '<div class="empty-state" id="emptyState"><i class="bi bi-chat-dots"></i><h5>开始对话</h5><p>输入问题开始问答</p></div>';
}

function hideEmptyState() { const el = document.getElementById('emptyState'); if (el) el.remove(); }

function openSettingsModal() { new bootstrap.Modal(document.getElementById('settingsModal')).show(); }

function scrollToBottom() { const el = document.getElementById('chatContainer'); el.scrollTop = el.scrollHeight; }

function escapeHtml(text) { const div = document.createElement('div'); div.textContent = text; return div.innerHTML; }

function showNotification(msg) {
    const n = document.createElement('div');
    n.style.cssText = 'position:fixed;top:20px;right:20px;background:#22c55e;color:white;padding:12px 24px;border-radius:10px;z-index:9999;box-shadow:0 4px 15px rgba(0,0,0,0.2);';
    n.textContent = msg;
    document.body.appendChild(n);
    setTimeout(() => n.remove(), 2000);
}

function setupDragDrop() {
    const area = document.getElementById('uploadArea');
    if (!area) return;
    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(e => area.addEventListener(e, (ev) => { ev.preventDefault(); ev.stopPropagation(); }));
    area.addEventListener('drop', (ev) => uploadDocument(ev.dataTransfer.files[0]));
}

function initSidebarResizing() {
    const modal = document.getElementById('pagePreviewModal');
    const handle = document.getElementById('sidebarResizeHandle');
    let isResizing = false;
    handle.addEventListener('mousedown', (e) => { isResizing = true; document.body.style.cursor = 'ew-resize'; e.preventDefault(); });
    document.addEventListener('mousemove', (e) => {
        if (!isResizing) return;
        const w = window.innerWidth - e.clientX;
        if (w > 300 && w < window.innerWidth * 0.9) {
            modal.style.width = `${w}px`;
            const main = document.querySelector('.main-content');
            if (main?.classList.contains('preview-open')) main.style.marginRight = `${w}px`;
        }
    });
    document.addEventListener('mouseup', () => { isResizing = false; document.body.style.cursor = ''; });
}
