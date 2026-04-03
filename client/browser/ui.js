// =============================================================================
// client/browser/ui.js — UI Status, Transcript, and DOM Manipulation
// =============================================================================
//
// PURPOSE:
//   All DOM manipulation and UI updates for the Vayumi browser client.
//   Called by app.js message handlers. Keeps all UI logic separate from
//   connection/audio logic.
//
// FUNCTIONS:
//
//   showLoginScreen():
//     Shows login-screen div, hides main-interface div.
//
//   showMainInterface():
//     Hides login-screen div, shows main-interface div.
//     Called after successful WebSocket auth.
//
//   showLoginError(message):
//     Displays error message on login form.
//
//   updateStatus(state):
//     Updates the status indicator with current state.
//     States: "sleeping", "listening", "processing", "speaking", "queued"
//     Visual mapping:
//       sleeping   → dim/grey indicator, "Sleeping" text
//       listening  → blue pulse, "Listening..."
//       processing → yellow, "Thinking..."
//       speaking   → white stream, "Speaking..."
//       queued     → orange, "Queued..."
//
//   addTranscript(text, speaker):
//     Adds a user transcript entry to the conversation display.
//     Format: "[speaker]: text"
//     Auto-scrolls to bottom.
//
//   addResponse(text, isFinal):
//     Adds or appends Vayumi's response text.
//     If isFinal is false → append to current response bubble.
//     If isFinal is true → finalize current response bubble.
//
//   updateMode(mode):
//     Updates mode button/indicator to show current mode.
//     Modes: "normal", "meeting", "focus"
//
//   showNotification(source, preview):
//     Shows a non-intrusive notification for flag events.
//     Example: "New email from Prof. Sharma: 'Project Deadline Update'"
//     Auto-dismisses after 5 seconds.
//
//   showError(message):
//     Shows an error toast/banner. Auto-dismisses after 5 seconds.
//
//   showDisconnected():
//     Shows "Disconnected — reconnecting..." banner.
//
//   hideDisconnected():
//     Hides the disconnected banner (called on reconnect).
//
//   clearTranscript():
//     Clears all conversation entries.
// =============================================================================

// function showLoginScreen() {}
// function showMainInterface() {}
// function showLoginError(message) {}
// function updateStatus(state) {}
// function addTranscript(text, speaker) {}
// function addResponse(text, isFinal) {}
// function updateMode(mode) {}
// function showNotification(source, preview) {}
// function showError(message) {}
// function showDisconnected() {}
// function hideDisconnected() {}
// function clearTranscript() {}

// =============================================================================
// client/browser/ui.js — UI Status, Transcript, and DOM Manipulation
// =============================================================================

// ---------------------------------------------------------------------------
// Internal helper – safely query a DOM element (returns null with a warning
// if not found so callers don't throw).
// ---------------------------------------------------------------------------
function _el(selector) {
  const el = document.querySelector(selector);
  if (!el) console.warn(`[ui] Element not found: ${selector}`);
  return el;
}

// ---------------------------------------------------------------------------
// We keep a tiny bit of module-level state so that addResponse() can
// distinguish between "append to the current bubble" and "start a new bubble".
// ---------------------------------------------------------------------------
let _currentResponseBubble = null;

// =============================================================================
// Login / Main Interface Toggle
// =============================================================================

function showLoginScreen() {
  const login = _el('#login-screen');
  const main  = _el('#main-interface');
  if (login) login.style.display = '';
  if (main) {
    main.classList.remove('visible');
    main.style.display = '';
  }
  showLoginPanel();
}

function showMainInterface() {
  const login = _el('#login-screen');
  const main  = _el('#main-interface');
  if (login) login.style.display = 'none';
  if (main) {
    main.style.display = '';
    main.classList.add('visible');
  }
}

function showLoginPanel() {
  const lp = _el('#login-panel');
  const rp = _el('#register-panel');
  if (lp) lp.hidden = false;
  if (rp) rp.hidden = true;
}

function showRegisterPanel() {
  const lp = _el('#login-panel');
  const rp = _el('#register-panel');
  if (lp) lp.hidden = true;
  if (rp) rp.hidden = false;
}

function clearAuthError() {
  const errEl = _el('#login-error');
  if (!errEl) return;
  errEl.textContent = '';
  errEl.classList.remove('visible');
}

function showAuthSuccessHint(text) {
  const hint = _el('#auth-success-hint');
  if (!hint) return;
  hint.textContent = text;
  hint.hidden = false;
}

function hideAuthSuccessHint() {
  const hint = _el('#auth-success-hint');
  if (!hint) return;
  hint.textContent = '';
  hint.hidden = true;
}

function showLoginError(message) {
  let errEl = _el('#login-error');
  // If a dedicated element doesn't exist, create one inside the login screen.
  if (!errEl) {
    const login = _el('#login-screen');
    if (!login) return;
    errEl = document.createElement('div');
    errEl.id = 'login-error';
    errEl.setAttribute('role', 'alert');
    errEl.className = 'login-error';
    login.appendChild(errEl);
  }
  hideAuthSuccessHint();
  errEl.textContent = message;
  errEl.classList.add('visible');
}

// =============================================================================
// Status Indicator
// =============================================================================

const _STATUS_META = {
  sleeping:   { label: 'Sleeping',    dotClass: 'sleeping' },
  listening:  { label: 'Listening…',  dotClass: 'listening' },
  processing: { label: 'Thinking…',   dotClass: 'processing' },
  speaking:   { label: 'Speaking…',   dotClass: 'speaking' },
  queued:     { label: 'Queued…',     dotClass: 'processing' },
};

const _STATUS_DOT_VARIANTS = ['sleeping', 'listening', 'processing', 'speaking', 'disconnected'];

function updateStatus(state) {
  const dot = _el('#status-dot');
  const label = _el('#status-label');
  const meta = _STATUS_META[state] || _STATUS_META.sleeping;

  if (dot) {
    _STATUS_DOT_VARIANTS.forEach((c) => dot.classList.remove(c));
    dot.classList.add(meta.dotClass);
  }
  if (label) {
    label.textContent = meta.label;
  }
}

// =============================================================================
// Transcript / Conversation
// =============================================================================

/**
 * Returns (or lazily creates) the scrollable conversation container.
 */
function _getTranscriptContainer() {
  const container = _el('#transcript-area');
  return container;
}

function _scrollToBottom(container) {
  if (container) container.scrollTop = container.scrollHeight;
}

function addTranscript(text, speaker) {
  const container = _getTranscriptContainer();
  if (!container) return;

  const empty = _el('#transcript-empty');
  if (empty) empty.style.display = 'none';

  const entry = document.createElement('div');
  const isUser = !speaker || String(speaker).toLowerCase() === 'user';
  entry.classList.add('transcript-entry', isUser ? 'user' : 'assistant');

  const speakerSpan = document.createElement('span');
  speakerSpan.classList.add('transcript-speaker');
  speakerSpan.textContent = `[${speaker || 'user'}]: `;

  const bubble = document.createElement('div');
  bubble.classList.add('transcript-bubble');
  bubble.textContent = text;

  entry.appendChild(speakerSpan);
  entry.appendChild(bubble);
  container.appendChild(entry);

  // A new user transcript also finalises any in-progress response bubble.
  _currentResponseBubble = null;

  _scrollToBottom(container);
}

function addResponse(text, isFinal) {
  const container = _getTranscriptContainer();
  if (!container) return;

  // If we don't already have an in-progress bubble, create one.
  if (!_currentResponseBubble) {
    const empty = _el('#transcript-empty');
    if (empty) empty.style.display = 'none';

    _currentResponseBubble = document.createElement('div');
    _currentResponseBubble.classList.add('transcript-entry', 'assistant');

    const speakerSpan = document.createElement('span');
    speakerSpan.classList.add('transcript-speaker');
    speakerSpan.textContent = '[vayumi]: ';

    const bubble = document.createElement('div');
    bubble.classList.add('transcript-bubble', 'streaming');
    bubble.textContent = '';

    _currentResponseBubble.appendChild(speakerSpan);
    _currentResponseBubble.appendChild(bubble);
    container.appendChild(_currentResponseBubble);
  }

  // Append text to the bubble's text span.
  const bubble = _currentResponseBubble.querySelector('.transcript-bubble');
  if (bubble) bubble.textContent += text;

  _scrollToBottom(container);

  // Finalise the bubble so the next addResponse creates a fresh one.
  if (isFinal) {
    _currentResponseBubble.classList.add('transcript-final');
    const bubble = _currentResponseBubble.querySelector('.transcript-bubble');
    if (bubble) bubble.classList.remove('streaming');
    _currentResponseBubble = null;
  }
}

function clearTranscript() {
  const container = _getTranscriptContainer();
  if (!container) return;
  container.querySelectorAll('.transcript-entry').forEach((el) => el.remove());
  const empty = _el('#transcript-empty');
  if (empty) empty.style.display = '';
  _currentResponseBubble = null;
}

// =============================================================================
// Mode Indicator
// =============================================================================

function updateMode(mode) {
  const m = mode || 'normal';
  document.querySelectorAll('.mode-btn[data-mode]').forEach((btn) => {
    btn.classList.toggle('active', btn.dataset.mode === m);
  });
}

// =============================================================================
// Notifications
// =============================================================================

/**
 * Returns (or lazily creates) a fixed-position notifications wrapper.
 */
function _getNotificationContainer() {
  let wrap = _el('#notification-container');
  if (!wrap) {
    wrap = document.createElement('div');
    wrap.id = 'notification-container';
    // Minimal inline positioning; real apps should use a stylesheet.
    Object.assign(wrap.style, {
      position: 'fixed',
      top: '1rem',
      right: '1rem',
      zIndex: '9999',
      display: 'flex',
      flexDirection: 'column',
      gap: '0.5rem',
      maxWidth: '24rem',
    });
    document.body.appendChild(wrap);
  }
  return wrap;
}

function showNotification(source, preview) {
  const container = _getNotificationContainer();

  const note = document.createElement('div');
  note.classList.add('notification');
  note.setAttribute('role', 'status');
  note.textContent = `New ${source}: "${preview}"`;

  // Basic inline styling as a fallback.
  Object.assign(note.style, {
    padding: '0.75rem 1rem',
    background: '#333',
    color: '#fff',
    borderRadius: '0.5rem',
    boxShadow: '0 2px 8px rgba(0,0,0,0.3)',
    opacity: '1',
    transition: 'opacity 0.4s ease',
  });

  container.appendChild(note);

  // Auto-dismiss after 5 seconds.
  setTimeout(() => {
    note.style.opacity = '0';
    setTimeout(() => note.remove(), 400);
  }, 5000);
}

// =============================================================================
// Error Toast
// =============================================================================

function showError(message) {
  const container = _getNotificationContainer();

  const toast = document.createElement('div');
  toast.classList.add('error-toast');
  toast.setAttribute('role', 'alert');
  toast.textContent = message;

  Object.assign(toast.style, {
    padding: '0.75rem 1rem',
    background: '#b00020',
    color: '#fff',
    borderRadius: '0.5rem',
    boxShadow: '0 2px 8px rgba(0,0,0,0.3)',
    opacity: '1',
    transition: 'opacity 0.4s ease',
  });

  container.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = '0';
    setTimeout(() => toast.remove(), 400);
  }, 5000);
}

// =============================================================================
// Disconnected Banner
// =============================================================================

function showDisconnected() {
  const overlay = _el('#disconnected-overlay');
  if (overlay) overlay.classList.add('visible');

  const dot = _el('#status-dot');
  if (dot) {
    _STATUS_DOT_VARIANTS.forEach((c) => dot.classList.remove(c));
    dot.classList.add('disconnected');
  }
  const label = _el('#status-label');
  if (label) label.textContent = 'Disconnected';
}

function hideDisconnected() {
  const overlay = _el('#disconnected-overlay');
  if (overlay) overlay.classList.remove('visible');
}

// Namespace expected by app.js (plain scripts — no bundler)
window.ui = {
  showLoginScreen,
  showMainInterface,
  showLoginPanel,
  showRegisterPanel,
  clearAuthError,
  showAuthSuccessHint,
  hideAuthSuccessHint,
  showLoginError,
  updateStatus,
  addTranscript,
  addResponse,
  clearTranscript,
  updateMode,
  showNotification,
  showError,
  showDisconnected,
  hideDisconnected,
};