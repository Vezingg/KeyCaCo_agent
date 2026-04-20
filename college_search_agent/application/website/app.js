/**
 * app.js — College Search Agent Chat Application
 *
 * Architecture:
 *  • Firebase Firestore  → persistent chat history (sidebar)
 *  • Backend /api/*      → FastWorkflow session + message routing
 *  • In-memory state     → current chat messages + active session id
 *
 * Special commands:
 *  //new  → start a fresh session (same as clicking "New Chat")
 */

import { db } from '/static/firebase-config.js';
import {
    collection,
    doc,
    addDoc,
    updateDoc,
    getDocs,
    query,
    orderBy,
    serverTimestamp,
    deleteDoc,
} from 'https://www.gstatic.com/firebasejs/10.12.0/firebase-firestore.js';

// ============================================================
// STATE
// ============================================================
const state = {
    /** UUID returned by /api/new-session — tracks FastWorkflow server session */
    currentSessionId: null,
    /** Firestore document id of the active chat */
    currentChatId: null,
    /** Messages in the active chat: [{role, content, ts}] */
    currentMessages: [],
    /** All chats loaded from Firestore (for the sidebar) */
    allChats: [],
    /** Prevent concurrent submissions */
    isLoading: false,
    /** Desktop sidebar collapsed state */
    sidebarCollapsed: false,
};

// ============================================================
// DOM REFERENCES
// ============================================================
const el = {
    sidebar: document.getElementById('sidebar'),
    chatHistory: document.getElementById('chatHistory'),
    historyEmpty: document.getElementById('historyEmpty'),
    newChatBtn: document.getElementById('newChatBtn'),
    sidebarCollapseBtn: document.getElementById('sidebarCollapseBtn'),
    mobileMenuBtn: document.getElementById('mobileMenuBtn'),
    mobileNewChatBtn: document.getElementById('mobileNewChatBtn'),
    overlay: document.getElementById('overlay'),
    welcome: document.getElementById('welcome'),
    messagesWrap: document.getElementById('messagesWrap'),
    messages: document.getElementById('messages'),
    messageInput: document.getElementById('messageInput'),
    sendBtn: document.getElementById('sendBtn'),
    headerTitle: document.getElementById('headerTitle'),
};

// ============================================================
// MARKED.JS CONFIGURATION
// ============================================================
marked.setOptions({ breaks: true, gfm: true });

// ============================================================
// INIT
// ============================================================
async function init() {
    _attachEventListeners();

    // On mobile, sidebar starts closed
    if (window.innerWidth <= 768) {
        el.sidebar.classList.remove('open');
    }

    // Load history from Firestore if configured
    if (db) {
        await _loadChatHistory();
    }
}

// ============================================================
// EVENT LISTENERS
// ============================================================
function _attachEventListeners() {
    // New chat
    el.newChatBtn.addEventListener('click', handleNewChat);
    el.mobileNewChatBtn.addEventListener('click', handleNewChat);

    // Sidebar toggles — mobileMenuBtn works on both mobile and desktop
    el.sidebarCollapseBtn.addEventListener('click', _toggleSidebarDesktop);
    el.mobileMenuBtn.addEventListener('click', () => {
        if (window.innerWidth <= 768) {
            _openSidebarMobile();
        } else {
            _toggleSidebarDesktop();
        }
    });
    el.overlay.addEventListener('click', _closeSidebarMobile);

    // Message input
    el.messageInput.addEventListener('input', _onInputChange);
    el.messageInput.addEventListener('keydown', _onKeyDown);
    el.sendBtn.addEventListener('click', handleSend);

    // Suggestion chips on the welcome screen
    document.querySelectorAll('.suggestion').forEach((btn) => {
        btn.addEventListener('click', () => {
            const msg = btn.getAttribute('data-msg');
            if (msg) {
                el.messageInput.value = msg;
                _onInputChange();
                handleSend();
            }
        });
    });
}

// ─── Sidebar helpers ───────────────────────────────────────

function _toggleSidebarDesktop() {
    state.sidebarCollapsed = !state.sidebarCollapsed;
    el.sidebar.classList.toggle('collapsed', state.sidebarCollapsed);
}

function _openSidebarMobile() {
    el.sidebar.classList.add('open');
    el.overlay.classList.add('visible');
}

function _closeSidebarMobile() {
    el.sidebar.classList.remove('open');
    el.overlay.classList.remove('visible');
}

// ─── Input helpers ─────────────────────────────────────────

function _onInputChange() {
    const val = el.messageInput.value;
    el.sendBtn.disabled = val.trim().length === 0 || state.isLoading;

    // Auto-grow textarea (up to 200px)
    el.messageInput.style.height = 'auto';
    el.messageInput.style.height =
        Math.min(el.messageInput.scrollHeight, 200) + 'px';
}

function _onKeyDown(e) {
    // Submit on Enter (not Shift+Enter)
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        if (!el.sendBtn.disabled) {
            handleSend();
        }
    }
}

// ============================================================
// MAIN ACTION HANDLERS
// ============================================================

/** Start a brand-new conversation (clears state + shows welcome screen). */
async function handleNewChat() {
    state.currentSessionId = null;
    state.currentChatId = null;
    state.currentMessages = [];

    // Clear the messages DOM so old messages don't bleed into the new chat
    el.messages.innerHTML = '';

    _showWelcome();
    el.headerTitle.textContent = 'College Search Agent';
    document.querySelectorAll('.chat-item').forEach((i) =>
        i.classList.remove('active')
    );

    el.messageInput.value = '';
    el.messageInput.style.height = 'auto';
    el.sendBtn.disabled = true;

    // Close sidebar on mobile
    if (window.innerWidth <= 768) {
        _closeSidebarMobile();
    }

    el.messageInput.focus();
}

/** Called when the send button is clicked or Enter is pressed. */
async function handleSend() {
    const text = el.messageInput.value.trim();
    if (!text || state.isLoading) return;

    // ── Special command: //new ──────────────────────────────
    if (text === '//new') {
        el.messageInput.value = '';
        el.messageInput.style.height = 'auto';
        el.sendBtn.disabled = true;
        await handleNewChat();
        return;
    }

    // ── Normal message ──────────────────────────────────────
    el.messageInput.value = '';
    el.messageInput.style.height = 'auto';
    el.sendBtn.disabled = true;

    await _sendUserMessage(text);
}

// ============================================================
// MESSAGE FLOW
// ============================================================

async function _sendUserMessage(text) {
    state.isLoading = true;

    // Switch to chat view on first message
    if (!state.currentSessionId) {
        _showChat();

        // Create a FastWorkflow session on the backend
        try {
            await _createBackendSession();
        } catch (err) {
            _appendSystemMessage(`⚠️ Could not connect to the agent: ${err.message}`);
            state.isLoading = false;
            el.sendBtn.disabled = false;
            return;
        }
    }

    // Render user bubble immediately
    _appendMessage('user', text);
    _showTyping();

    // Persist user message to Firestore
    const userEntry = { role: 'user', content: text, ts: Date.now() };
    state.currentMessages.push(userEntry);

    if (db) {
        if (!state.currentChatId) {
            await _createFirestoreChat(userEntry);
        } else {
            await _appendToFirestore(userEntry);
        }
    }

    // ── Call backend ─────────────────────────────────────────
    let agentText = '';
    try {
        const resp = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                session_id: state.currentSessionId,
                message: text,
            }),
        });

        if (!resp.ok) {
            const payload = await resp.json().catch(() => ({}));
            throw new Error(payload.detail || `HTTP ${resp.status}`);
        }

        const data = await resp.json();
        agentText = data.response || '';
    } catch (err) {
        _removeTyping();
        _appendSystemMessage(`⚠️ ${err.message}`);
        state.isLoading = false;
        el.sendBtn.disabled = el.messageInput.value.trim().length === 0;
        return;
    }

    _removeTyping();

    // Render and persist agent reply
    if (agentText) {
        _appendMessage('assistant', agentText);
        const agentEntry = { role: 'assistant', content: agentText, ts: Date.now() };
        state.currentMessages.push(agentEntry);

        if (db && state.currentChatId) {
            await _appendToFirestore(agentEntry);
        }
    }

    state.isLoading = false;
    el.sendBtn.disabled = el.messageInput.value.trim().length === 0;
    el.messageInput.focus();
}

// ============================================================
// BACKEND SESSION
// ============================================================

async function _createBackendSession() {
    const resp = await fetch('/api/new-session', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: 'web_user' }),
    });

    if (!resp.ok) {
        const payload = await resp.json().catch(() => ({}));
        throw new Error(payload.detail || `HTTP ${resp.status}`);
    }

    const data = await resp.json();
    state.currentSessionId = data.session_id;
}

// ============================================================
// FIRESTORE  (chat history)
// ============================================================

/** Load all chats ordered newest-first and render in sidebar. */
async function _loadChatHistory() {
    if (!db) return;
    try {
        const q = query(collection(db, 'chats'), orderBy('updatedAt', 'desc'));
        const snapshot = await getDocs(q);
        state.allChats = snapshot.docs.map((d) => ({ id: d.id, ...d.data() }));
        _renderSidebar();
    } catch (err) {
        console.warn('[College Agent] Failed to load chat history:', err);
    }
}

/** Create a new Firestore document for the current chat. */
async function _createFirestoreChat(firstMessage) {
    if (!db) return;
    try {
        const rawTitle = firstMessage.content;
        const title = rawTitle.length > 50 ? rawTitle.slice(0, 50) + '…' : rawTitle;

        const docRef = await addDoc(collection(db, 'chats'), {
            title,
            createdAt: serverTimestamp(),
            updatedAt: serverTimestamp(),
            messages: [firstMessage],
        });

        state.currentChatId = docRef.id;
        el.headerTitle.textContent = title;

        // Add to local cache and re-render sidebar
        const newChat = { id: docRef.id, title, messages: [firstMessage] };
        state.allChats.unshift(newChat);
        _renderSidebar();
        _highlightChat(docRef.id);
    } catch (err) {
        console.warn('[College Agent] Firestore create failed:', err);
    }
}

/** Append a message entry to the existing Firestore document. */
async function _appendToFirestore(entry) {
    if (!db || !state.currentChatId) return;
    try {
        const chatRef = doc(db, 'chats', state.currentChatId);
        await updateDoc(chatRef, {
            messages: [...state.currentMessages],
            updatedAt: serverTimestamp(),
        });

        // Update local cache
        const idx = state.allChats.findIndex((c) => c.id === state.currentChatId);
        if (idx >= 0) {
            state.allChats[idx].messages = [...state.currentMessages];
        }
    } catch (err) {
        console.warn('[College Agent] Firestore update failed:', err);
    }
}

/** Delete a chat from Firestore and the sidebar. */
async function _deleteChat(chatId, event) {
    event.stopPropagation(); // don't open the chat
    if (!db) return;
    try {
        await deleteDoc(doc(db, 'chats', chatId));
        state.allChats = state.allChats.filter((c) => c.id !== chatId);
        _renderSidebar();

        // If deleting the active chat, reset to welcome
        if (state.currentChatId === chatId) {
            await handleNewChat();
        }
    } catch (err) {
        console.warn('[College Agent] Firestore delete failed:', err);
    }
}

// ============================================================
// SIDEBAR RENDERING
// ============================================================

function _renderSidebar() {
    const chats = state.allChats;

    if (!chats || chats.length === 0) {
        el.historyEmpty.style.display = 'block';
        // Remove any existing group elements
        el.chatHistory.querySelectorAll('.chat-group').forEach((g) => g.remove());
        return;
    }

    el.historyEmpty.style.display = 'none';

    // Remove old groups before re-rendering
    el.chatHistory.querySelectorAll('.chat-group').forEach((g) => g.remove());

    // Date-based grouping
    const now = new Date();
    const today = new Date(now); today.setHours(0, 0, 0, 0);
    const yday = new Date(today); yday.setDate(yday.getDate() - 1);
    const w7 = new Date(today); w7.setDate(w7.getDate() - 7);
    const d30 = new Date(today); d30.setDate(d30.getDate() - 30);

    const groups = {
        'Today': [],
        'Yesterday': [],
        'Previous 7 Days': [],
        'Previous 30 Days': [],
        'Older': [],
    };

    chats.forEach((chat) => {
        // createdAt may be a Firestore Timestamp (has .seconds) or a plain Date
        const ts = chat.createdAt?.seconds
            ? new Date(chat.createdAt.seconds * 1000)
            : new Date();
        if (ts >= today) groups['Today'].push(chat);
        else if (ts >= yday) groups['Yesterday'].push(chat);
        else if (ts >= w7) groups['Previous 7 Days'].push(chat);
        else if (ts >= d30) groups['Previous 30 Days'].push(chat);
        else groups['Older'].push(chat);
    });

    for (const [label, groupChats] of Object.entries(groups)) {
        if (groupChats.length === 0) continue;

        const groupEl = document.createElement('div');
        groupEl.className = 'chat-group';

        const labelEl = document.createElement('div');
        labelEl.className = 'group-label';
        labelEl.textContent = label;
        groupEl.appendChild(labelEl);

        groupChats.forEach((chat) => {
            const item = document.createElement('div');
            item.className = 'chat-item';
            item.dataset.chatId = chat.id;
            item.setAttribute('role', 'listitem');
            item.style.cssText =
                'display:flex; align-items:center; justify-content:space-between; gap:6px;';

            const titleSpan = document.createElement('span');
            titleSpan.textContent = chat.title || 'Conversation';
            titleSpan.title = chat.title || 'Conversation';
            titleSpan.style.cssText = 'flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;';
            item.appendChild(titleSpan);

            // Delete button (only shown in Firebase mode)
            if (db) {
                const delBtn = document.createElement('button');
                delBtn.className = 'icon-btn';
                delBtn.title = 'Delete chat';
                delBtn.setAttribute('aria-label', 'Delete this chat');
                delBtn.style.cssText =
                    'width:24px; height:24px; flex-shrink:0; opacity:0; transition:opacity 0.15s;';
                delBtn.innerHTML = `
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none"
            stroke="currentColor" stroke-width="2" stroke-linecap="round">
            <polyline points="3 6 5 6 21 6"/>
            <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/>
            <path d="M10 11v6M14 11v6"/>
            <path d="M9 6V4h6v2"/>
          </svg>`;
                delBtn.addEventListener('click', (e) => _deleteChat(chat.id, e));
                item.addEventListener('mouseenter', () => { delBtn.style.opacity = '1'; });
                item.addEventListener('mouseleave', () => { delBtn.style.opacity = '0'; });
                item.appendChild(delBtn);
            }

            // Open chat on click (anywhere except delete button)
            item.addEventListener('click', (e) => {
                if (e.target.closest('.icon-btn')) return;
                _openExistingChat(chat);
            });

            groupEl.appendChild(item);
        });

        el.chatHistory.appendChild(groupEl);
    }

    // Re-apply active highlight
    if (state.currentChatId) {
        _highlightChat(state.currentChatId);
    }
}

function _highlightChat(chatId) {
    document.querySelectorAll('.chat-item').forEach((item) => {
        item.classList.toggle('active', item.dataset.chatId === chatId);
    });
}

/** Load an existing chat from the sidebar into the main view. */
async function _openExistingChat(chat) {
    state.currentChatId = chat.id;
    state.currentMessages = Array.isArray(chat.messages) ? [...chat.messages] : [];
    state.currentSessionId = null; // fresh agent session (previous context is gone)

    const title = chat.title || 'Conversation';
    el.headerTitle.textContent = title;
    _highlightChat(chat.id);

    _showChat();
    el.messages.innerHTML = '';

    // Replay all stored messages
    state.currentMessages.forEach((msg) => {
        _appendMessage(msg.role, msg.content);
    });

    if (window.innerWidth <= 768) {
        _closeSidebarMobile();
    }

    el.messageInput.focus();
}

// ============================================================
// UI HELPERS
// ============================================================

function _showWelcome() {
    el.welcome.style.display = 'flex';
    el.messagesWrap.style.display = 'none';
}

function _showChat() {
    el.welcome.style.display = 'none';
    el.messagesWrap.style.display = 'flex';
}

function _appendMessage(role, content) {
    const msgEl = document.createElement('div');
    msgEl.className = `message ${role}`;

    // Avatar (assistant only)
    if (role === 'assistant') {
        const avatar = document.createElement('div');
        avatar.className = 'avatar';
        avatar.textContent = '🎓';
        avatar.setAttribute('aria-hidden', 'true');
        msgEl.appendChild(avatar);
    }

    const contentEl = document.createElement('div');
    contentEl.className = 'message-content';

    if (role === 'assistant') {
        // Render markdown and sanitise HTML
        const rawHtml = marked.parse(String(content));
        contentEl.innerHTML = DOMPurify.sanitize(rawHtml, {
            // Allow safe HTML entities produced by marked
            FORBID_TAGS: ['script', 'iframe', 'object', 'embed'],
            FORBID_ATTR: ['onerror', 'onload', 'onclick'],
        });
    } else {
        // User text: plain text only (no HTML)
        contentEl.textContent = String(content);
    }

    msgEl.appendChild(contentEl);
    el.messages.appendChild(msgEl);
    _scrollToBottom();
}

function _appendSystemMessage(text) {
    const msgEl = document.createElement('div');
    msgEl.className = 'message system';
    const contentEl = document.createElement('div');
    contentEl.className = 'message-content';
    contentEl.textContent = String(text);
    msgEl.appendChild(contentEl);
    el.messages.appendChild(msgEl);
    _scrollToBottom();
}

function _showTyping() {
    const typingEl = document.createElement('div');
    typingEl.className = 'message assistant';
    typingEl.id = 'typingIndicator';

    const avatar = document.createElement('div');
    avatar.className = 'avatar';
    avatar.textContent = '🎓';
    avatar.setAttribute('aria-hidden', 'true');

    const contentEl = document.createElement('div');
    contentEl.className = 'message-content';
    contentEl.innerHTML = `
    <div class="typing-dots" aria-label="Agent is typing">
      <span></span><span></span><span></span>
    </div>`;

    typingEl.appendChild(avatar);
    typingEl.appendChild(contentEl);
    el.messages.appendChild(typingEl);
    _scrollToBottom();
}

function _removeTyping() {
    document.getElementById('typingIndicator')?.remove();
}

function _scrollToBottom() {
    // Use requestAnimationFrame so the DOM has updated before measuring
    requestAnimationFrame(() => {
        el.messagesWrap.scrollTop = el.messagesWrap.scrollHeight;
    });
}

// ============================================================
// BOOT
// ============================================================
init();
