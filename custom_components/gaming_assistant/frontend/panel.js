/**
 * Gaming Assistant – Home Assistant Sidebar Panel
 *
 * Self-contained custom element for the HA sidebar.
 * Supports DE/EN based on HA language setting.
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
  sourceType: `select.${DOMAIN}_source_type`,
};

const I18N = {
  de: {
    title: "Gaming Assistent",
    active: "Aktiv",
    inactive: "Inaktiv",
    tips: "Tipps",
    controls: "Steuerung",
    mode: "Modus",
    game: "Spiel",
    gameAuto: "\u2014 Automatisch erkennen \u2014",
    gamePlaceholder: "Oder Spielname eingeben\u2026",
    sourceType: "Quelle",
    sourceAuto: "Automatisch",
    sourceConsole: "Konsole / Handheld",
    sourceTabletop: "Brettspiel / Karten",
    modeCoach: "Coach",
    modeCoplay: "Mitspieler",
    modeOpponent: "Gegner",
    modeAnalyst: "Analyst",
    spoilerNone: "Keine",
    spoilerLow: "Niedrig",
    spoilerMedium: "Mittel",
    spoilerHigh: "Hoch",
    spoilerLevel: "Spoiler-Stufe",
    intervalS: "Intervall (s)",
    timeoutS: "Timeout (s)",
    autoAnnounce: "Auto-Ansage (TTS)",
    autoSummary: "Auto-Zusammenfassung",
    actions: "Aktionen",
    start: "Start",
    stop: "Stopp",
    analyzeNow: "Jetzt analysieren",
    announce: "Ansagen",
    summarize: "Zusammenfassen",
    clearHistory: "Verlauf leeren",
    confirmClear: "Gesamten Tipp-Verlauf leeren?",
    askTitle: "Frage an die KI",
    askPlaceholder: "Stelle eine Frage zum Spiel\u2026",
    askSend: "Fragen",
    askSending: "Wird gesendet\u2026",
    currentTip: "Aktueller Tipp",
    waitingForTips: "Warte auf Tipps\u2026",
    game: "Spiel",
    tipHistory: "Tipp-Verlauf",
    noTipsYet: "Noch keine Tipps.",
    sessionSummary: "Sitzungs\u00FCbersicht",
    diagSetup: "Diagnose & Einstellungen",
    latency: "Latenz (s)",
    frames: "Frames",
    watchers: "Watchers",
    errors: "Fehler",
    camera: "Kamera",
    noCamera: "\u2014 Keine Kamera \u2014",
    ttsEngine: "Sprachausgabe (TTS)",
    noTts: "\u2014 Keine TTS \u2014",
    speaker: "Lautsprecher",
    defaultSpeaker: "\u2014 Standard \u2014",
    aiModel: "KI-Modell",
    save: "Speichern",
    saved: "Gespeichert!",
  },
  en: {
    title: "Gaming Assistant",
    active: "Active",
    inactive: "Inactive",
    tips: "Tips",
    controls: "Controls",
    mode: "Mode",
    game: "Game",
    gameAuto: "\u2014 Auto-detect \u2014",
    gamePlaceholder: "Or type a game name\u2026",
    sourceType: "Source",
    sourceAuto: "Auto-detect",
    sourceConsole: "Console / Handheld",
    sourceTabletop: "Board game / Cards",
    modeCoach: "Coach",
    modeCoplay: "Co-Player",
    modeOpponent: "Opponent",
    modeAnalyst: "Analyst",
    spoilerNone: "None",
    spoilerLow: "Low",
    spoilerMedium: "Medium",
    spoilerHigh: "High",
    spoilerLevel: "Spoiler Level",
    intervalS: "Interval (s)",
    timeoutS: "Timeout (s)",
    autoAnnounce: "Auto Announce (TTS)",
    autoSummary: "Auto Summary",
    actions: "Actions",
    start: "Start",
    stop: "Stop",
    analyzeNow: "Analyze Now",
    announce: "Announce",
    summarize: "Summarize",
    clearHistory: "Clear History",
    confirmClear: "Clear all tip history?",
    askTitle: "Ask the AI",
    askPlaceholder: "Ask a question about the game\u2026",
    askSend: "Ask",
    askSending: "Sending\u2026",
    currentTip: "Current Tip",
    waitingForTips: "Waiting for tips\u2026",
    game: "Game",
    tipHistory: "Tip History",
    noTipsYet: "No tips yet.",
    sessionSummary: "Session Summary",
    diagSetup: "Diagnostics & Setup",
    latency: "Latency (s)",
    frames: "Frames",
    watchers: "Watchers",
    errors: "Errors",
    camera: "Camera",
    noCamera: "\u2014 No camera \u2014",
    ttsEngine: "Text-to-Speech (TTS)",
    noTts: "\u2014 No TTS \u2014",
    speaker: "Speaker",
    defaultSpeaker: "\u2014 Default \u2014",
    aiModel: "AI Model",
    save: "Save",
    saved: "Saved!",
  },
};

class GamingAssistantPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._rendered = false;
    this._lang = "en";
    this._setupPopulated = false;
  }

  set hass(hass) {
    this._hass = hass;
    const lang = (hass.language || "en").substring(0, 2);
    const langChanged = lang !== this._lang;
    this._lang = lang;

    if (!this._rendered || langChanged) {
      this._setupPopulated = false;
      this._render();
      this._rendered = true;
    }
    this._updateStates();
  }

  set panel(panel) {
    this._panel = panel;
  }

  _t(key) {
    return (I18N[this._lang] || I18N.en)[key] || I18N.en[key] || key;
  }

  _render() {
    const t = (k) => this._t(k);
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
        .container { max-width: 900px; margin: 0 auto; padding: 16px; }
        h1 {
          font-size: 24px; font-weight: 400; margin: 0 0 16px 0;
          display: flex; align-items: center; gap: 8px;
        }
        h1 .icon { font-size: 28px; }

        .status-bar { display: flex; gap: 12px; margin-bottom: 16px; flex-wrap: wrap; }
        .status-chip {
          display: inline-flex; align-items: center; gap: 6px;
          padding: 6px 14px; border-radius: 20px; font-size: 13px; font-weight: 500;
          background: var(--bg); border: 1px solid var(--border);
        }
        .status-chip.active { background: var(--success); color: #fff; border-color: var(--success); }
        .status-chip .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--text2); }
        .status-chip.active .dot { background: #fff; }

        .card {
          background: var(--bg); border-radius: 12px; padding: 16px;
          margin-bottom: 16px; border: 1px solid var(--border);
        }
        .card h2 {
          font-size: 16px; font-weight: 500; margin: 0 0 12px 0;
          display: flex; align-items: center; gap: 8px;
        }

        .tip-box {
          background: var(--primary-background-color, #f5f5f5);
          border-left: 4px solid var(--primary); padding: 12px 16px;
          border-radius: 0 8px 8px 0; font-size: 14px; line-height: 1.6;
          white-space: pre-wrap; word-wrap: break-word;
        }
        .tip-box.empty { color: var(--text2); font-style: italic; border-left-color: var(--border); }
        .tip-game { margin-top: 8px; font-size: 12px; color: var(--text2); }

        .ask-row { display: flex; gap: 8px; }
        .ask-row input[type="text"] {
          flex: 1; padding: 10px 14px; border: 1px solid var(--border);
          border-radius: 8px; background: var(--primary-background-color, #f5f5f5);
          color: var(--text); font-size: 14px; outline: none; box-sizing: border-box;
        }
        .ask-row input[type="text"]:focus { border-color: var(--primary); }
        .ask-row button {
          padding: 10px 20px; border: none; border-radius: 8px;
          background: var(--primary); color: #fff; font-size: 14px;
          font-weight: 500; cursor: pointer; white-space: nowrap; transition: 0.15s;
        }
        .ask-row button:hover { opacity: 0.85; }
        .ask-row button:disabled { opacity: 0.5; cursor: not-allowed; }

        .controls-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
        @media (max-width: 600px) { .controls-grid { grid-template-columns: 1fr; } }
        .control-item label {
          display: block; font-size: 12px; color: var(--text2);
          margin-bottom: 4px; text-transform: uppercase; letter-spacing: 0.5px;
        }
        .control-item select, .control-item input[type="number"], .control-item input[type="text"] {
          width: 100%; padding: 8px 12px; border: 1px solid var(--border);
          border-radius: 8px; background: var(--primary-background-color, #f5f5f5);
          color: var(--text); font-size: 14px; box-sizing: border-box; outline: none;
        }
        .control-item select:focus, .control-item input:focus { border-color: var(--primary); }

        .switch-row { display: flex; align-items: center; justify-content: space-between; padding: 8px 0; }
        .switch-row + .switch-row { border-top: 1px solid var(--border); }
        .switch-label { font-size: 14px; }
        .toggle { position: relative; width: 48px; height: 26px; cursor: pointer; }
        .toggle input { opacity: 0; width: 0; height: 0; }
        .toggle .slider {
          position: absolute; top: 0; left: 0; right: 0; bottom: 0;
          background: var(--border); border-radius: 13px; transition: 0.2s;
        }
        .toggle .slider::before {
          content: ""; position: absolute; width: 20px; height: 20px;
          left: 3px; bottom: 3px; background: #fff; border-radius: 50%; transition: 0.2s;
        }
        .toggle input:checked + .slider { background: var(--primary); }
        .toggle input:checked + .slider::before { transform: translateX(22px); }

        .actions { display: flex; gap: 8px; flex-wrap: wrap; }
        .btn {
          display: inline-flex; align-items: center; gap: 6px;
          padding: 8px 16px; border: 1px solid var(--border); border-radius: 8px;
          background: var(--bg); color: var(--text); font-size: 13px;
          cursor: pointer; transition: 0.15s;
        }
        .btn:hover { background: var(--primary); color: #fff; border-color: var(--primary); }
        .btn.danger:hover { background: var(--danger); border-color: var(--danger); }
        .btn.success { background: var(--success); color: #fff; border-color: var(--success); }
        .btn.success:hover { opacity: 0.85; }
        .btn-save {
          padding: 8px 24px; border: none; border-radius: 8px;
          background: var(--primary); color: #fff; font-size: 13px; font-weight: 500;
          cursor: pointer; transition: 0.15s; margin-top: 12px;
        }
        .btn-save:hover { opacity: 0.85; }
        .btn-save:disabled { opacity: 0.5; cursor: not-allowed; }

        .history-list { max-height: 400px; overflow-y: auto; padding-right: 4px; }
        .history-item {
          padding: 10px 0; font-size: 13px; line-height: 1.5;
          border-bottom: 1px solid var(--border);
        }
        .history-item:last-child { border-bottom: none; }
        .history-num { display: inline-block; width: 24px; font-weight: 600; color: var(--primary); }

        .diag-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 12px; }
        .diag-item {
          text-align: center; padding: 12px 8px;
          background: var(--primary-background-color, #f5f5f5); border-radius: 8px;
        }
        .diag-value { font-size: 24px; font-weight: 600; color: var(--primary); }
        .diag-label { font-size: 11px; color: var(--text2); text-transform: uppercase; margin-top: 4px; }

        .setup-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 16px; }
        @media (max-width: 600px) { .setup-grid { grid-template-columns: 1fr; } }
        .setup-grid .full-width { grid-column: 1 / -1; }

        .summary-box {
          background: var(--primary-background-color, #f5f5f5); padding: 12px 16px;
          border-radius: 8px; font-size: 14px; line-height: 1.6;
          white-space: pre-wrap; word-wrap: break-word;
        }
        .section-divider {
          border: none; border-top: 1px solid var(--border); margin: 16px 0 12px;
        }
      </style>

      <div class="container">
        <h1><span class="icon">&#127918;</span> ${t("title")}</h1>

        <div class="status-bar">
          <span class="status-chip" id="chip-gaming"><span class="dot"></span> <span id="chip-gaming-text">${t("inactive")}</span></span>
          <span class="status-chip" id="chip-status"><span class="dot"></span> <span id="chip-status-text">--</span></span>
          <span class="status-chip" id="chip-tips">${t("tips")}: <strong id="chip-tips-count">0</strong></span>
        </div>

        <!-- 1. Controls (top) -->
        <div class="card">
          <h2>${t("controls")}</h2>
          <div class="controls-grid">
            <div class="control-item">
              <label>${t("mode")}</label>
              <select id="ctrl-mode">
                <option value="coach">${t("modeCoach")}</option>
                <option value="coplay">${t("modeCoplay")}</option>
                <option value="opponent">${t("modeOpponent")}</option>
                <option value="analyst">${t("modeAnalyst")}</option>
              </select>
            </div>
            <div class="control-item">
              <label>${t("game")}</label>
              <input type="text" id="ctrl-game" list="game-list" placeholder="${t("gamePlaceholder")}" autocomplete="off">
              <datalist id="game-list"></datalist>
            </div>
            <div class="control-item">
              <label>${t("sourceType")}</label>
              <select id="ctrl-source-type">
                <option value="auto">${t("sourceAuto")}</option>
                <option value="console">${t("sourceConsole")}</option>
                <option value="tabletop">${t("sourceTabletop")}</option>
              </select>
            </div>
            <div class="control-item">
              <label>${t("spoilerLevel")}</label>
              <select id="ctrl-spoiler">
                <option value="none">${t("spoilerNone")}</option>
                <option value="low">${t("spoilerLow")}</option>
                <option value="medium" selected>${t("spoilerMedium")}</option>
                <option value="high">${t("spoilerHigh")}</option>
              </select>
            </div>
            <div class="control-item">
              <label>${t("intervalS")}</label>
              <input type="number" id="ctrl-interval" min="5" max="120" step="1">
            </div>
            <div class="control-item">
              <label>${t("timeoutS")}</label>
              <input type="number" id="ctrl-timeout" min="10" max="300" step="5">
            </div>
          </div>
          <div style="margin-top: 12px;">
            <div class="switch-row">
              <span class="switch-label">${t("autoAnnounce")}</span>
              <label class="toggle"><input type="checkbox" id="ctrl-auto-announce"><span class="slider"></span></label>
            </div>
            <div class="switch-row">
              <span class="switch-label">${t("autoSummary")}</span>
              <label class="toggle"><input type="checkbox" id="ctrl-auto-summary"><span class="slider"></span></label>
            </div>
          </div>
        </div>

        <!-- 2. Actions -->
        <div class="card">
          <h2>${t("actions")}</h2>
          <div class="actions">
            <button class="btn success" id="btn-start">&#9654; ${t("start")}</button>
            <button class="btn" id="btn-stop">&#9632; ${t("stop")}</button>
            <button class="btn" id="btn-analyze">&#128247; ${t("analyzeNow")}</button>
            <button class="btn" id="btn-announce">&#128226; ${t("announce")}</button>
            <button class="btn" id="btn-summarize">&#128196; ${t("summarize")}</button>
            <button class="btn danger" id="btn-clear">&#128465; ${t("clearHistory")}</button>
          </div>
        </div>

        <!-- 3. Current Tip + Ask -->
        <div class="card">
          <h2>${t("currentTip")}</h2>
          <div class="tip-box empty" id="current-tip">${t("waitingForTips")}</div>
          <div class="tip-game" id="current-tip-game"></div>
          <hr class="section-divider">
          <h2>${t("askTitle")}</h2>
          <div class="ask-row">
            <input type="text" id="ask-input" placeholder="${t("askPlaceholder")}">
            <button id="btn-ask">${t("askSend")}</button>
          </div>
        </div>

        <!-- 4. Tip History -->
        <div class="card">
          <h2>${t("tipHistory")}</h2>
          <div class="history-list" id="history-list">
            <em style="color: var(--text2)">${t("noTipsYet")}</em>
          </div>
        </div>

        <!-- Session Summary -->
        <div class="card" id="summary-card" style="display:none;">
          <h2>${t("sessionSummary")}</h2>
          <div class="summary-box" id="session-summary"></div>
        </div>

        <!-- 5. Diagnostics & Setup -->
        <div class="card">
          <h2>${t("diagSetup")}</h2>
          <div class="diag-grid">
            <div class="diag-item">
              <div class="diag-value" id="diag-latency">--</div>
              <div class="diag-label">${t("latency")}</div>
            </div>
            <div class="diag-item">
              <div class="diag-value" id="diag-frames">0</div>
              <div class="diag-label">${t("frames")}</div>
            </div>
            <div class="diag-item">
              <div class="diag-value" id="diag-watchers">0</div>
              <div class="diag-label">${t("watchers")}</div>
            </div>
            <div class="diag-item">
              <div class="diag-value" id="diag-errors">0</div>
              <div class="diag-label">${t("errors")}</div>
            </div>
          </div>
          <hr class="section-divider">
          <div class="setup-grid">
            <div class="control-item">
              <label>${t("camera")}</label>
              <select id="setup-camera"></select>
            </div>
            <div class="control-item">
              <label>${t("speaker")}</label>
              <select id="setup-speaker"></select>
            </div>
            <div class="control-item">
              <label>${t("ttsEngine")}</label>
              <select id="setup-tts"></select>
            </div>
            <div class="control-item">
              <label>${t("aiModel")}</label>
              <select id="setup-model"></select>
            </div>
          </div>
          <button class="btn-save" id="btn-save-setup">${t("save")}</button>
        </div>
      </div>
    `;

    this._bindEvents();
  }

  _bindEvents() {
    const $ = (id) => this.shadowRoot.getElementById(id);

    // Controls
    $("ctrl-mode").addEventListener("change", (e) =>
      this._callService("select", "select_option", ENTITIES.mode, { option: e.target.value })
    );
    // Game hint: send on Enter, blur, or datalist selection
    const gameInput = $("ctrl-game");
    let gameDebounce = null;
    const sendGameHint = () => {
      clearTimeout(gameDebounce);
      const hint = gameInput.value.trim();
      this._callDomainService("set_game_hint", { game_hint: hint });
    };
    gameInput.addEventListener("change", sendGameHint);  // datalist pick or blur
    gameInput.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); sendGameHint(); } });
    $("ctrl-source-type").addEventListener("change", (e) =>
      this._callService("select", "select_option", ENTITIES.sourceType, { option: e.target.value })
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
    $("ctrl-auto-announce").addEventListener("change", (e) =>
      this._callService("switch", e.target.checked ? "turn_on" : "turn_off", ENTITIES.autoAnnounce)
    );
    $("ctrl-auto-summary").addEventListener("change", (e) =>
      this._callService("switch", e.target.checked ? "turn_on" : "turn_off", ENTITIES.autoSummary)
    );

    // Ask
    const askInput = $("ask-input");
    const askBtn = $("btn-ask");
    const submitQuestion = async () => {
      const question = askInput.value.trim();
      if (!question) return;
      askBtn.disabled = true;
      askBtn.textContent = this._t("askSending");
      await this._callDomainService("ask", { question });
      askBtn.disabled = false;
      askBtn.textContent = this._t("askSend");
      askInput.value = "";
      askInput.focus();
    };
    askBtn.addEventListener("click", submitQuestion);
    askInput.addEventListener("keydown", (e) => { if (e.key === "Enter") submitQuestion(); });

    // Actions
    $("btn-start").addEventListener("click", () => this._callDomainService("start"));
    $("btn-stop").addEventListener("click", () => this._callDomainService("stop"));
    $("btn-analyze").addEventListener("click", () => this._callDomainService("analyze"));
    $("btn-announce").addEventListener("click", () => this._callDomainService("announce"));
    $("btn-summarize").addEventListener("click", () => this._callDomainService("summarize_session"));
    $("btn-clear").addEventListener("click", () => {
      if (confirm(this._t("confirmClear"))) this._callDomainService("clear_history");
    });

    // Setup save
    $("btn-save-setup").addEventListener("click", async () => {
      const btn = $("btn-save-setup");
      btn.disabled = true;
      const data = {};
      const cam = $("setup-camera").value;
      data.camera_entity = cam || "";
      const tts = $("setup-tts").value;
      data.tts_entity = tts || "";
      const spk = $("setup-speaker").value;
      data.tts_target = spk || "";
      const model = $("setup-model").value;
      if (model) data.model = model;

      await this._callDomainService("configure", data);
      btn.textContent = this._t("saved");
      setTimeout(() => {
        btn.textContent = this._t("save");
        btn.disabled = false;
      }, 2000);
    });
  }

  async _callService(domain, service, entityId, data = {}) {
    if (!this._hass) return;
    try {
      await this._hass.callService(domain, service, { entity_id: entityId, ...data });
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
      $("chip-gaming-text").textContent = isActive ? this._t("active") : this._t("inactive");
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
    if (history) $("chip-tips-count").textContent = history.state || "0";

    // Current tip
    const tip = this._getState(ENTITIES.tip);
    const tipBox = $("current-tip");
    if (tip) {
      const fullTip = (tip.attributes && tip.attributes.full_tip) || tip.state;
      if (fullTip && fullTip !== "Waiting for tips...") {
        tipBox.textContent = fullTip;
        tipBox.classList.remove("empty");
      } else {
        tipBox.textContent = this._t("waitingForTips");
        tipBox.classList.add("empty");
      }
      const game = tip.attributes && tip.attributes.game;
      $("current-tip-game").textContent = game ? `${this._t("game")}: ${game}` : "";
    }

    // Mode & Spoiler selects
    this._updateSelect($("ctrl-mode"), ENTITIES.mode);
    this._updateSelect($("ctrl-source-type"), ENTITIES.sourceType);
    this._updateSelect($("ctrl-spoiler"), ENTITIES.spoiler);

    // Number inputs
    const interval = this._getState(ENTITIES.interval);
    const intEl = $("ctrl-interval");
    if (interval && this.shadowRoot.activeElement !== intEl) intEl.value = interval.state;
    const timeout = this._getState(ENTITIES.timeout);
    const toEl = $("ctrl-timeout");
    if (timeout && this.shadowRoot.activeElement !== toEl) toEl.value = timeout.state;

    // Switches
    const autoAnn = this._getState(ENTITIES.autoAnnounce);
    if (autoAnn) $("ctrl-auto-announce").checked = autoAnn.state === "on";
    const autoSum = this._getState(ENTITIES.autoSummary);
    if (autoSum) $("ctrl-auto-summary").checked = autoSum.state === "on";

    // History
    if (history && history.attributes && history.attributes.recent_tips) {
      const tips = history.attributes.recent_tips;
      const listEl = $("history-list");
      if (tips.length > 0) {
        listEl.innerHTML = tips.slice().reverse()
          .map((entry, i) =>
            `<div class="history-item"><span class="history-num">${i + 1}.</span>${this._escapeHtml(entry.tip)}</div>`
          ).join("");
      } else {
        listEl.innerHTML = `<em style="color: var(--text2)">${this._t("noTipsYet")}</em>`;
      }
    }

    // Session summary
    const summary = this._getState(ENTITIES.sessionSummary);
    const summaryCard = $("summary-card");
    if (summary) {
      const fullSummary = (summary.attributes && summary.attributes.full_summary) || summary.state;
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

    // Game dropdown + current game hint from status sensor
    const statusState = this._getState(ENTITIES.status);
    if (statusState && statusState.attributes) {
      this._updateGameDropdown($("ctrl-game"), statusState.attributes);
      // Refresh model dropdown when server-side models arrive
      this._updateModelDropdown($("setup-model"), statusState.attributes);
    }

    // Setup dropdowns (populate once from hass.states)
    if (!this._setupPopulated) {
      this._populateSetupDropdowns();
      this._setupPopulated = true;
    }
  }

  _populateSetupDropdowns() {
    if (!this._hass) return;
    const $ = (id) => this.shadowRoot.getElementById(id);
    const states = this._hass.states;

    // Camera dropdown
    const camSelect = $("setup-camera");
    const cameras = Object.keys(states).filter((e) => e.startsWith("camera.")).sort();
    camSelect.innerHTML = `<option value="">${this._t("noCamera")}</option>`
      + cameras.map((e) => {
        const name = states[e].attributes.friendly_name || e;
        return `<option value="${e}">${name}</option>`;
      }).join("");

    // TTS dropdown
    const ttsSelect = $("setup-tts");
    const ttsEntities = Object.keys(states).filter((e) => e.startsWith("tts.")).sort();
    ttsSelect.innerHTML = `<option value="">${this._t("noTts")}</option>`
      + ttsEntities.map((e) => {
        const name = states[e].attributes.friendly_name || e;
        return `<option value="${e}">${name}</option>`;
      }).join("");

    // Speaker (media_player) dropdown
    const spkSelect = $("setup-speaker");
    const players = Object.keys(states).filter((e) => e.startsWith("media_player.")).sort();
    spkSelect.innerHTML = `<option value="">${this._t("defaultSpeaker")}</option>`
      + players.map((e) => {
        const name = states[e].attributes.friendly_name || e;
        return `<option value="${e}">${name}</option>`;
      }).join("");

    // AI Model dropdown – use models from coordinator (fetched server-side)
    const modelSelect = $("setup-model");
    const statusForModels = this._getState(ENTITIES.status);
    const serverModels = (statusForModels && statusForModels.attributes && statusForModels.attributes.available_models) || [];
    const fallbackModels = ["qwen2.5vl", "llava", "llava:13b", "bakllava", "llama3.2-vision"];
    const modelList = serverModels.length > 0 ? serverModels : fallbackModels;
    modelSelect.innerHTML = modelList
      .map((m) => `<option value="${m}">${m}</option>`).join("");

    // Try to set current values from config entry
    this._loadCurrentConfig(camSelect, ttsSelect, spkSelect, modelSelect);
  }

  async _loadCurrentConfig(camSelect, ttsSelect, spkSelect, modelSelect) {
    if (!this._hass) return;
    try {
      const entries = await this._hass.callWS({
        type: "config_entries/get",
        domain: DOMAIN,
      });
      if (entries && entries.length > 0) {
        const entry = entries[0];
        try {
          const detail = await this._hass.callWS({
            type: "config_entries/get_single",
            entry_id: entry.entry_id,
          });
          const opts = detail.options || {};
          const data = detail.data || {};
          const merged = { ...data, ...opts };
          if (merged.camera_entity) camSelect.value = merged.camera_entity;
          if (merged.tts_entity) ttsSelect.value = merged.tts_entity;
          if (merged.tts_target) spkSelect.value = merged.tts_target;
          if (merged.model) {
            // Ensure the configured model is in the dropdown
            const exists = Array.from(modelSelect.options).some((o) => o.value === merged.model);
            if (!exists) {
              const opt = document.createElement("option");
              opt.value = merged.model;
              opt.textContent = merged.model;
              modelSelect.insertBefore(opt, modelSelect.firstChild);
            }
            modelSelect.value = merged.model;
          }
        } catch (_e) {
          modelSelect.value = "qwen2.5vl";
        }
      }
    } catch (err) {
      console.warn("Gaming Assistant: Could not load config entries:", err);
    }
  }

  _updateGameDropdown(inputEl, attrs) {
    const packs = attrs.available_game_packs || [];
    const currentHint = attrs.default_game_hint || "";
    const packKey = packs.map((p) => p.id).join(",");

    // Rebuild datalist options if packs changed
    const datalist = this.shadowRoot.getElementById("game-list");
    if (datalist && datalist.dataset.packKey !== packKey) {
      datalist.innerHTML = packs.map((p) => `<option value="${p.name}">`).join("");
      datalist.dataset.packKey = packKey;
    }

    // Sync value with current hint (don't overwrite while user is typing)
    if (this.shadowRoot.activeElement !== inputEl && inputEl.value !== currentHint) {
      inputEl.value = currentHint;
    }
  }

  _updateSelect(selectEl, entityId) {
    const state = this._getState(entityId);
    if (!state) return;
    const current = state.state;
    // If entity has options and the select is empty, populate it
    // (pre-populated selects with localized labels are kept as-is)
    if (state.attributes) {
      const options = state.attributes.options || [];
      if (options.length > 0 && selectEl.options.length === 0) {
        selectEl.innerHTML = options.map((o) => `<option value="${o}">${o}</option>`).join("");
      }
    }
    // Sync selected value from entity state
    if (current && selectEl.value !== current) selectEl.value = current;
  }

  _updateModelDropdown(selectEl, attrs) {
    if (!selectEl) return;
    const models = attrs.available_models || [];
    if (models.length === 0) return;
    const modelKey = models.join(",");
    if (selectEl.dataset.modelKey === modelKey) return;
    const current = selectEl.value;
    selectEl.innerHTML = models.map((m) => `<option value="${m}">${m}</option>`).join("");
    selectEl.dataset.modelKey = modelKey;
    // Restore previous selection or add it if not in list
    if (current) {
      if (models.includes(current)) {
        selectEl.value = current;
      } else {
        const opt = document.createElement("option");
        opt.value = current;
        opt.textContent = current;
        selectEl.insertBefore(opt, selectEl.firstChild);
        selectEl.value = current;
      }
    }
  }

  _escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
  }
}

customElements.define("gaming-assistant-panel", GamingAssistantPanel);
