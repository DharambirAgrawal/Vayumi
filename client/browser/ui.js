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

function showLoginScreen() {}
function showMainInterface() {}
function showLoginError(message) {}
function updateStatus(state) {}
function addTranscript(text, speaker) {}
function addResponse(text, isFinal) {}
function updateMode(mode) {}
function showNotification(source, preview) {}
function showError(message) {}
function showDisconnected() {}
function hideDisconnected() {}
function clearTranscript() {}
