/**
 * Gaming Assistant – Home Assistant Sidebar Panel
 *
 * A self-contained custom element that renders directly in the HA sidebar.
 * No build step, no dependencies – just vanilla JS + HA websocket API.
 */

const DOMAIN = "gaming_assistant";

const ENTITIES = {
  mode: `select.${DOMAIN}_assistant_mode`,
  spoiler: `select.${DOMAIN}_spoiler_level`,
  interval: `number.${DOMAIN}_interval`,
  timeout: `number.${DOMAIN}_timeout`,
  autoAnnounce: `switch.${DOMAIN}_auto_announce`,
  autoSummary: `switch.${DOMAIN}_auto_summary`,
  gamingMode: `binary_sensor.gaming_mode`,
  status: `sensor.${DOMAIN}_status`,
  tip: `sensor.${DOMAIN}_tip`,
  history: `sensor.${DOMAIN}_history`,
  latency: `sensor.${DOMAIN}_latency`,
  frames: `sensor.${DOMAIN}_frames_processed`,
  watchers: `sensor.${DOMAIN}_active_watchers`,
  errorCount: `sensor.${DOMAIN}_error_count`,
  sessionSummary: `sensor.${DOMAIN}_session_summary`,
};

class GamingAssistantPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._unsubscribe = null;
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._rendered) {
      this._render();
      this._rendered = true;
    }
    this._updateStates();
  }

  set panel(panel) {
    this._panel = panel;
  }

  connectedCallback() {
    if (this._hass && !this._rendered) {
      this._render();
      this._rendered = true;
      this._updateStates();
    }
  }

  disconnectedCallback() {
    if (this._unsubscribe) {
      this._unsubscribe();
      this._unsubscribe = null;
    }
  }

  _render() {
    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          --primary: var(--primary-color, #03a9f4);
          --bg: var(--card-background-color, #fff);
          --text: var(--primary-text-color, #212121);
          --text2: var(--secondary-text-color, #727272);
          --border: var(--divider-color, #e0e0e0);
          --success: #4caf50;
          --danger: #f44336;
          font-family: var(--paper-font-body1_-_font-family, Roboto, sans-serif);
          color: var(--text);
          background: var(--primary-background-color, #fafafa);
          min-height: 100vh;
        }
        .container {
          max-width: 900px;
          margin: 0 auto;
          padding: 16px;
        }
        h1 {
          font-size: 24px;
          font-weight: 400;
          margin: 0 0 16px 0;
          display: flex;
          align-items: center;
          gap: 8px;
        }
        h1 .icon { font-size: 28px; }

        /* Status bar */
        .status-bar {
          display: flex;
          gap: 12px;
          margin-bottom: 16px;
          flex-wrap: wrap;
        }
        .status-chip {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          padding: 6px 14px;
          border-radius: 20px;
          font-size: 13px;
          font-weight: 500;
          background: var(--bg);
          border: 1px solid var(--border);
        }
        .status-chip.active {
          background: var(--success);
          color: #fff;
          border-color: var(--success);
        }
        .status-chip .dot {
          width: 8px; height: 8px;
          border-radius: 50%;
          background: var(--text2);
        }
        .status-chip.active .dot { background: #fff; }

        /* Cards */
        .card {
          background: var(--bg);
          border-radius: 12px;
          padding: 16px;
          margin-bottom: 16px;
          border: 1px solid var(--border);
        }
        .card h2 {
          font-size: 16px;
          font-weight: 500;
          margin: 0 0 12px 0;
          display: flex;
          align-items: center;
          gap: 8px;
        }

        /* Current tip */
        .tip-box {
          background: var(--primary-background-color, #f5f5f5);
          border-left: 4px solid var(--primary);
          padding: 12px 16px;
          border-radius: 0 8px 8px 0;
          font-size: 14px;
          line-height: 1.6;
          white-space: pre-wrap;
          word-wrap: break-word;
        }
        .tip-box.empty {
          color: var(--text2);
          font-style: italic;
          border-left-color: var(--border);
        }
        .tip-game {
          margin-top: 8px;
          font-size: 12px;
          color: var(--text2);
        }

        /* Controls grid */
        .controls-grid {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 12px;
        }
        @media (max-width: 600px) {
          .controls-grid { grid-template-columns: 1fr; }
        }
        .control-item label {
          display: block;
          font-size: 12px;
          color: var(--text2);
          margin-bottom: 4px;
          text-transform: uppercase;
          letter-spacing: 0.5px;
        }
        .control-item select,
        .control-item input[type="number"] {
          width: 100%;
          padding: 8px 12px;
          border: 1px solid var(--border);
          border-radius: 8px;
          background: var(--primary-background-color, #f5f5f5);
          color: var(--text);
          font-size: 14px;
          box-sizing: border-box;
          outline: none;
        }
        .control-item select:focus,
        .control-item input:focus {
          border-color: var(--primary);
        }

        /* Switches */
        .switch-row {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 8px 0;
        }
        .switch-row + .switch-row {
          border-top: 1px solid var(--border);
        }
        .switch-label { font-size: 14px; }
        .toggle {
          position: relative;
          width: 48px; height: 26px;
          cursor: pointer;
        }
        .toggle input {
          opacity: 0; width: 0; height: 0;
        }
        .toggle .slider {
          position: absolute;
          top: 0; left: 0; right: 0; bottom: 0;
          background: var(--border);
          border-radius: 13px;
          transition: 0.2s;
        }
        .toggle .slider::before {
          content: "";
          position: absolute;
          width: 20px; height: 20px;
          left: 3px; bottom: 3px;
          background: #fff;
          border-radius: 50%;
          transition: 0.2s;
        }
        .toggle input:checked + .slider {
          background: var(--primary);
        }
        .toggle input:checked + .slider::before {
          transform: translateX(22px);
        }

        /* Action buttons */
        .actions {
          display: flex;
          gap: 8px;
          flex-wrap: wrap;
        }
        .btn {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          padding: 8px 16px;
          border: 1px solid var(--border);
          border-radius: 8px;
          background: var(--bg);
          color: var(--text);
          font-size: 13px;
          cursor: pointer;
          transition: 0.15s;
        }
        .btn:hover {
          background: var(--primary);
          color: #fff;
          border-color: var(--primary);
        }
        .btn.danger:hover {
          background: var(--danger);
          border-color: var(--danger);
        }
        .btn.success {
          background: var(--success);
          color: #fff;
          border-color: var(--success);
        }
        .btn.success:hover {
          opacity: 0.85;
        }

        /* History */
        .history-list {
          max-height: 400px;
          overflow-y: auto;
          padding-right: 4px;
        }
        .history-item {
          padding: 10px 0;
          font-size: 13px;
          line-height: 1.5;
          border-bottom: 1px solid var(--border);
        }
        .history-item:last-child { border-bottom: none; }
        .history-num {
          display: inline-block;
          width: 24px;
          font-weight: 600;
          color: var(--primary);
        }

        /* Diagnostics */
        .diag-grid {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
          gap: 12px;
        }
        .diag-item {
          text-align: center;
          padding: 12px 8px;
          background: var(--primary-background-color, #f5f5f5);
          border-radius: 8px;
        }
        .diag-value {
          font-size: 24px;
          font-weight: 600;
          color: var(--primary);
        }
        .diag-label {
          font-size: 11px;
          color: var(--text2);
          text-transform: uppercase;
          margin-top: 4px;
        }

        /* Session summary */
        .summary-box {
          background: var(--primary-background-color, #f5f5f5);
          padding: 12px 16px;
          border-radius: 8px;
          font-size: 14px;
          line-height: 1.6;
          white-space: pre-wrap;
          word-wrap: break-word;
        }
      </style>

      <div class="container">
        <h1><span class="icon">&#127918;</span> Gaming Assistant</h1>

        <!-- Status Bar -->
        <div class="status-bar">
          <span class="status-chip" id="chip-gaming"><span class="dot"></span> <span id="chip-gaming-text">Inactive</span></span>
          <span class="status-chip" id="chip-status"><span class="dot"></span> <span id="chip-status-text">--</span></span>
          <span class="status-chip" id="chip-tips">Tips: <strong id="chip-tips-count">0</strong></span>
        </div>

        <!-- Current Tip -->
        <div class="card">
          <h2>Current Tip</h2>
          <div class="tip-box empty" id="current-tip">Waiting for tips...</div>
          <div class="tip-game" id="current-tip-game"></div>
        </div>

        <!-- Controls -->
        <div class="card">
          <h2>Controls</h2>
          <div class="controls-grid">
            <div class="control-item">
              <label>Mode</label>
              <select id="ctrl-mode"></select>
            </div>
            <div class="control-item">
              <label>Spoiler Level</label>
              <select id="ctrl-spoiler"></select>
            </div>
            <div class="control-item">
              <label>Interval (s)</label>
              <input type="number" id="ctrl-interval" min="5" max="120" step="1">
            </div>
            <div class="control-item">
              <label>Timeout (s)</label>
              <input type="number" id="ctrl-timeout" min="10" max="300" step="5">
            </div>
          </div>
          <div style="margin-top: 12px;">
            <div class="switch-row">
              <span class="switch-label">Auto Announce (TTS)</span>
              <label class="toggle">
                <input type="checkbox" id="ctrl-auto-announce">
                <span class="slider"></span>
              </label>
            </div>
            <div class="switch-row">
              <span class="switch-label">Auto Summary</span>
              <label class="toggle">
                <input type="checkbox" id="ctrl-auto-summary">
                <span class="slider"></span>
              </label>
            </div>
          </div>
        </div>

        <!-- Actions -->
        <div class="card">
          <h2>Actions</h2>
          <div class="actions">
            <button class="btn success" id="btn-start">&#9654; Start</button>
            <button class="btn" id="btn-stop">&#9632; Stop</button>
            <button class="btn" id="btn-analyze">&#128247; Analyze Now</button>
            <button class="btn" id="btn-announce">&#128226; Announce</button>
            <button class="btn" id="btn-summarize">&#128196; Summarize</button>
            <button class="btn danger" id="btn-clear">&#128465; Clear History</button>
          </div>
        </div>

        <!-- History -->
        <div class="card">
          <h2>Tip History</h2>
          <div class="history-list" id="history-list">
            <em style="color: var(--text2)">No tips yet.</em>
          </div>
        </div>

        <!-- Session Summary -->
        <div class="card" id="summary-card" style="display:none;">
          <h2>Session Summary</h2>
          <div class="summary-box" id="session-summary"></div>
        </div>

        <!-- Diagnostics -->
        <div class="card">
          <h2>Diagnostics</h2>
          <div class="diag-grid">
            <div class="diag-item">
              <div class="diag-value" id="diag-latency">--</div>
              <div class="diag-label">Latency (s)</div>
            </div>
            <div class="diag-item">
              <div class="diag-value" id="diag-frames">0</div>
              <div class="diag-label">Frames</div>
            </div>
            <div class="diag-item">
              <div class="diag-value" id="diag-watchers">0</div>
              <div class="diag-label">Watchers</div>
            </div>
            <div class="diag-item">
              <div class="diag-value" id="diag-errors">0</div>
              <div class="diag-label">Errors</div>
            </div>
          </div>
        </div>
      </div>
    `;

    this._bindEvents();
  }

  _bindEvents() {
    const $ = (id) => this.shadowRoot.getElementById(id);

    // Select/Number controls
    $("ctrl-mode").addEventListener("change", (e) =>
      this._callService("select", "select_option", ENTITIES.mode, { option: e.target.value })
    );
    $("ctrl-spoiler").addEventListener("change", (e) =>
      this._callService("select", "select_option", ENTITIES.spoiler, { option: e.target.value })
    );
    $("ctrl-interval").addEventListener("change", (e) =>
      this._callService("number", "set_value", ENTITIES.interval, { value: Number(e.target.value) })
    );
    $("ctrl-timeout").addEventListener("change", (e) =>
      this._callService("number", "set_value", ENTITIES.timeout, { value: Number(e.target.value) })
    );

    // Switches
    $("ctrl-auto-announce").addEventListener("change", (e) =>
      this._callService("switch", e.target.checked ? "turn_on" : "turn_off", ENTITIES.autoAnnounce)
    );
    $("ctrl-auto-summary").addEventListener("change", (e) =>
      this._callService("switch", e.target.checked ? "turn_on" : "turn_off", ENTITIES.autoSummary)
    );

    // Action buttons
    $("btn-start").addEventListener("click", () =>
      this._callDomainService("start")
    );
    $("btn-stop").addEventListener("click", () =>
      this._callDomainService("stop")
    );
    $("btn-analyze").addEventListener("click", () =>
      this._callDomainService("analyze")
    );
    $("btn-announce").addEventListener("click", () =>
      this._callDomainService("announce")
    );
    $("btn-summarize").addEventListener("click", () =>
      this._callDomainService("summarize_session")
    );
    $("btn-clear").addEventListener("click", () => {
      if (confirm("Clear all tip history?")) {
        this._callDomainService("clear_history");
      }
    });
  }

  async _callService(domain, service, entityId, data = {}) {
    if (!this._hass) return;
    try {
      await this._hass.callService(domain, service, {
        entity_id: entityId,
        ...data,
      });
    } catch (err) {
      console.error(`Gaming Assistant: ${domain}.${service} failed:`, err);
    }
  }

  async _callDomainService(service, data = {}) {
    if (!this._hass) return;
    try {
      await this._hass.callService(DOMAIN, service, data);
    } catch (err) {
      console.error(`Gaming Assistant: ${DOMAIN}.${service} failed:`, err);
    }
  }

  _getState(entityId) {
    if (!this._hass || !this._hass.states[entityId]) return null;
    return this._hass.states[entityId];
  }

  _updateStates() {
    if (!this._hass) return;
    const $ = (id) => this.shadowRoot.getElementById(id);

    // Gaming mode chip
    const gaming = this._getState(ENTITIES.gamingMode);
    const isActive = gaming && gaming.state === "on";
    const chipGaming = $("chip-gaming");
    if (chipGaming) {
      chipGaming.classList.toggle("active", isActive);
      $("chip-gaming-text").textContent = isActive ? "Active" : "Inactive";
    }

    // Status chip
    const status = this._getState(ENTITIES.status);
    if (status) {
      const chipStatus = $("chip-status");
      chipStatus.classList.toggle("active", status.state === "analyzing");
      $("chip-status-text").textContent = status.state;
    }

    // Tips count
    const history = this._getState(ENTITIES.history);
    if (history) {
      $("chip-tips-count").textContent = history.state || "0";
    }

    // Current tip
    const tip = this._getState(ENTITIES.tip);
    const tipBox = $("current-tip");
    if (tip) {
      const fullTip = (tip.attributes && tip.attributes.full_tip) || tip.state;
      if (fullTip && fullTip !== "Waiting for tips...") {
        tipBox.textContent = fullTip;
        tipBox.classList.remove("empty");
      } else {
        tipBox.textContent = "Waiting for tips...";
        tipBox.classList.add("empty");
      }
      const game = tip.attributes && tip.attributes.game;
      $("current-tip-game").textContent = game ? `Game: ${game}` : "";
    }

    // Controls: populate select options and set values
    this._updateSelect($("ctrl-mode"), ENTITIES.mode);
    this._updateSelect($("ctrl-spoiler"), ENTITIES.spoiler);

    const interval = this._getState(ENTITIES.interval);
    const intEl = $("ctrl-interval");
    if (interval && document.activeElement !== intEl) {
      intEl.value = interval.state;
    }

    const timeout = this._getState(ENTITIES.timeout);
    const toEl = $("ctrl-timeout");
    if (timeout && document.activeElement !== toEl) {
      toEl.value = timeout.state;
    }

    // Switches
    const autoAnn = this._getState(ENTITIES.autoAnnounce);
    if (autoAnn) $("ctrl-auto-announce").checked = autoAnn.state === "on";

    const autoSum = this._getState(ENTITIES.autoSummary);
    if (autoSum) $("ctrl-auto-summary").checked = autoSum.state === "on";

    // History list
    if (history && history.attributes && history.attributes.recent_tips) {
      const tips = history.attributes.recent_tips;
      const listEl = $("history-list");
      if (tips.length > 0) {
        listEl.innerHTML = tips
          .slice()
          .reverse()
          .map(
            (entry, i) =>
              `<div class="history-item"><span class="history-num">${i + 1}.</span>${this._escapeHtml(entry.tip)}</div>`
          )
          .join("");
      } else {
        listEl.innerHTML = '<em style="color: var(--text2)">No tips yet.</em>';
      }
    }

    // Session summary
    const summary = this._getState(ENTITIES.sessionSummary);
    const summaryCard = $("summary-card");
    if (summary) {
      const fullSummary =
        (summary.attributes && summary.attributes.full_summary) || summary.state;
      if (fullSummary && fullSummary !== "No summary yet") {
        $("session-summary").textContent = fullSummary;
        summaryCard.style.display = "";
      } else {
        summaryCard.style.display = "none";
      }
    }

    // Diagnostics
    const latency = this._getState(ENTITIES.latency);
    if (latency) {
      const val = parseFloat(latency.state);
      $("diag-latency").textContent = isNaN(val) ? "--" : val.toFixed(1);
    }

    const frames = this._getState(ENTITIES.frames);
    if (frames) $("diag-frames").textContent = frames.state || "0";

    const watchers = this._getState(ENTITIES.watchers);
    if (watchers) $("diag-watchers").textContent = watchers.state || "0";

    const errors = this._getState(ENTITIES.errorCount);
    if (errors) $("diag-errors").textContent = errors.state || "0";
  }

  _updateSelect(selectEl, entityId) {
    const state = this._getState(entityId);
    if (!state || !state.attributes) return;

    const options = state.attributes.options || [];
    const current = state.state;

    // Only rebuild if options changed
    const optKey = options.join(",");
    if (selectEl.dataset.optKey !== optKey) {
      selectEl.innerHTML = options
        .map((o) => `<option value="${o}">${o}</option>`)
        .join("");
      selectEl.dataset.optKey = optKey;
    }

    if (selectEl.value !== current) {
      selectEl.value = current;
    }
  }

  _escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
  }
}

customElements.define("gaming-assistant-panel", GamingAssistantPanel);
