/**
 * Gaming Assistant – Home Assistant Sidebar Panel
 *
 * Custom element for the HA sidebar, built from HA's own frontend elements
 * (hass-tabs-subpage, ha-card, ha-button, ha-select, ha-input, ha-dialog ...).
 * Tabs live under /gaming-assistant/<tab>. Supports DE/EN based on HA language.
 */

const DOMAIN = "gaming_assistant";

const ENTITIES = {
  // Candidates: the entity id follows the entity name, not the unique id, so
  // older and newer installs differ (select.gaming_assistant_mode vs ..._assistant_mode).
  mode: [`select.${DOMAIN}_mode`, `select.${DOMAIN}_assistant_mode`],
  spoiler: `select.${DOMAIN}_spoiler_level`,
  interval: `number.${DOMAIN}_interval`,
  timeout: `number.${DOMAIN}_timeout`,
  autoAnnounce: `switch.${DOMAIN}_auto_announce`,
  autoSummary: `switch.${DOMAIN}_auto_summary`,
  gamingMode: [`binary_sensor.${DOMAIN}_gaming_mode`, `binary_sensor.gaming_mode`],
  status: `sensor.${DOMAIN}_status`,
  tip: `sensor.${DOMAIN}_tip`,
  history: `sensor.${DOMAIN}_history`,
  latency: `sensor.${DOMAIN}_latency`,
  frames: `sensor.${DOMAIN}_frames_processed`,
  watchers: `sensor.${DOMAIN}_active_watchers`,
  errorCount: `sensor.${DOMAIN}_error_count`,
  sessionSummary: `sensor.${DOMAIN}_session_summary`,
  sourceType: `select.${DOMAIN}_source_type`,
  clients: `sensor.${DOMAIN}_clients`,
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
    tipHistory: "Tipp-Verlauf",
    noTipsYet: "Noch keine Tipps.",
    sessionSummary: "Sitzungs\u00FCbersicht",
    diagSetup: "Diagnose & Einstellungen",
    latency: "Latenz (s)",
    frames: "Frames",
    watchers: "Watchers",
    errors: "Fehler",
    camera: "Kamera",
    noCamera: "\u2014 Nur Capture-Clients \u2014",
    ttsEngine: "Sprachausgabe (TTS)",
    noTts: "\u2014 Keine TTS \u2014",
    speaker: "Lautsprecher",
    defaultSpeaker: "\u2014 Standard \u2014",
    aiModel: "KI-Modell",
    save: "Speichern",
    saved: "Gespeichert!",
    clients: "Ger\u00E4te",
    noClients: "Noch keine Ger\u00E4te. Starte einen Capture-Agent oder eine Kamera.",
    globalSetting: "\u2014 Wie global \u2014",
    activeClient: "aktiv",
    lastSeen: "zuletzt",
    clientGameHint: "Spiel, falls keins erkannt",
    tabOverview: "Übersicht",
    tabHistory: "Verlauf",
    tabClients: "Geräte",
    tabSettings: "Einstellungen",
    status: "Status",
    model: "KI-Modell",
    client: "Aktives Gerät",
    session: "Sitzung",
    automation: "Automatik",
    diagnostics: "Diagnose",
    setup: "Einrichtung",
    cancel: "Abbrechen",
    confirmClearTitle: "Verlauf leeren?",
    historyCleared: "Verlauf geleert.",
    askSent: "Frage gesendet.",
    noResponse: "Die Integration antwortet nicht.",
    callFailed: "Aktion fehlgeschlagen",
    noSummary: "Noch keine Zusammenfassung.",
    gamePick: "Spiel aus Liste",
    pickKnown: "Bekannte Spiele",
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
    tipHistory: "Tip History",
    noTipsYet: "No tips yet.",
    sessionSummary: "Session Summary",
    diagSetup: "Diagnostics & Setup",
    latency: "Latency (s)",
    frames: "Frames",
    watchers: "Watchers",
    errors: "Errors",
    camera: "Camera",
    noCamera: "\u2014 Capture clients only \u2014",
    ttsEngine: "Text-to-Speech (TTS)",
    noTts: "\u2014 No TTS \u2014",
    speaker: "Speaker",
    defaultSpeaker: "\u2014 Default \u2014",
    aiModel: "AI Model",
    save: "Save",
    saved: "Saved!",
    clients: "Clients",
    noClients: "No clients yet. Start a capture agent or a camera watcher.",
    globalSetting: "\u2014 Global \u2014",
    activeClient: "active",
    lastSeen: "last seen",
    clientGameHint: "Game if none is detected",
    tabOverview: "Overview",
    tabHistory: "History",
    tabClients: "Clients",
    tabSettings: "Settings",
    status: "Status",
    model: "AI model",
    client: "Active client",
    session: "Session",
    automation: "Automation",
    diagnostics: "Diagnostics",
    setup: "Setup",
    cancel: "Cancel",
    confirmClearTitle: "Clear history?",
    historyCleared: "History cleared.",
    askSent: "Question sent.",
    noResponse: "The integration is not responding.",
    callFailed: "Action failed",
    noSummary: "No summary yet.",
    gamePick: "Game from list",
    pickKnown: "Known games",
  },
};

/* ---------- Home Assistant building blocks ----------
 * The panel is assembled from HA's own frontend elements (hass-tabs-subpage,
 * ha-card, ha-button, ha-select, ha-input, ha-dialog ...). They are lazy-loaded
 * by HA, so we pull them in the same way HACS does (via the config panel).
 * Every element has a plain HTML fallback (checked with customElements.get). */

const PATH = "/gaming-assistant";
const NONE = "__none__"; // ha-select sentinel for the "empty" choice

const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ESC[c]);
const def = (tag) => !!customElements.get(tag);
const attr = (n, v) => (v == null || v === "" ? "" : ` ${n}="${esc(v)}"`);

async function loadBuildingBlocks() {
  if (customElements.get("hass-tabs-subpage-data-table")) return;
  try {
    const resolver = document.createElement("partial-panel-resolver");
    const routes = resolver._getRoutes
      ? resolver._getRoutes([{ component_name: "config", url_path: "a" }])
      : resolver.getRoutes([{ component_name: "config", url_path: "a" }]);
    await routes.routes.a.load();
    const config = document.createElement("ha-panel-config");
    await config.routerOptions.routes.integrations.load();
  } catch (_err) {
    /* the fallbacks below keep the panel usable */
  }
  await Promise.race([
    customElements.whenDefined("hass-tabs-subpage-data-table"),
    new Promise((r) => setTimeout(r, 8000)),
  ]);
}

// mdi icon paths for the tabs
const TABS = [
  ["overview", "tabOverview", "M13,3V9H21V3M13,21H21V11H13M3,21H11V15H3M3,13H11V3H3V13Z"],
  ["history", "tabHistory", "M13.5,8H12V13L16.28,15.54L17,14.33L13.5,12.25V8M13,3A9,9 0 0,0 4,12H1L4.96,16.03L9,12H6A7,7 0 0,1 13,5A7,7 0 0,1 20,12A7,7 0 0,1 13,19C11.07,19 9.32,18.21 8.06,16.94L6.64,18.36C8.27,20 10.5,21 13,21A9,9 0 0,0 22,12A9,9 0 0,0 13,3"],
  ["clients", "tabClients", "M4,6H20V4H4A2,2 0 0,0 2,6V17H0V20H14V17H4V6M23,8H17A1,1 0 0,0 16,9V19A1,1 0 0,0 17,20H23A1,1 0 0,0 24,19V9A1,1 0 0,0 23,8M22,17H18V10H22V17Z"],
  ["settings", "tabSettings", "M12,15.5A3.5,3.5 0 0,1 8.5,12A3.5,3.5 0 0,1 12,8.5A3.5,3.5 0 0,1 15.5,12A3.5,3.5 0 0,1 12,15.5M19.43,12.97C19.47,12.65 19.5,12.33 19.5,12C19.5,11.67 19.47,11.34 19.43,11L21.54,9.37C21.73,9.22 21.78,8.95 21.66,8.73L19.66,5.27C19.54,5.05 19.27,4.96 19.05,5.05L16.56,6.05C16.04,5.66 15.5,5.32 14.87,5.07L14.5,2.42C14.46,2.18 14.25,2 14,2H10C9.75,2 9.54,2.18 9.5,2.42L9.13,5.07C8.5,5.32 7.96,5.66 7.44,6.05L4.95,5.05C4.72,4.96 4.46,5.05 4.34,5.27L2.34,8.73C2.21,8.95 2.27,9.22 2.46,9.37L4.57,11C4.53,11.34 4.5,11.67 4.5,12C4.5,12.33 4.53,12.65 4.57,12.97L2.46,14.63C2.27,14.78 2.21,15.05 2.34,15.27L4.34,18.73C4.46,18.95 4.72,19.03 4.95,18.95L7.44,17.94C7.96,18.34 8.5,18.68 9.13,18.93L9.5,21.58C9.54,21.82 9.75,22 10,22H14C14.25,22 14.46,21.82 14.5,21.58L14.87,18.93C15.5,18.67 16.04,18.34 16.56,17.94L19.05,18.95C19.27,19.03 19.54,18.95 19.66,18.73L21.66,15.27C21.78,15.05 21.73,14.78 21.54,14.63L19.43,12.97Z"],
];
const TAB_KEYS = TABS.map((t) => t[0]);

/* o: act (data-act), id, cls, outlined, danger, disabled, slot, extra */
function button(text, o = {}) {
  const common = `${attr("id", o.id)}${attr("slot", o.slot)}${attr("data-act", o.act)}${o.disabled ? " disabled" : ""}${o.extra || ""}`;
  if (def("ha-button")) {
    return `<ha-button${common}${attr("class", o.cls)} appearance="${o.outlined ? "outlined" : "filled"}" variant="${o.danger ? "danger" : "brand"}">${esc(text)}</ha-button>`;
  }
  return `<button${common} class="fb-btn ${o.outlined ? "outlined" : ""} ${o.danger ? "danger" : ""} ${o.cls || ""}">${esc(text)}</button>`;
}

/* o: id, cls, label, value, type, min, max, step, placeholder */
function textField(o) {
  const a = attr("id", o.id) + attr("class", o.cls) + attr("type", o.type) + attr("min", o.min)
    + attr("max", o.max) + attr("step", o.step) + attr("placeholder", o.placeholder);
  if (def("ha-input")) return `<ha-input${a}${attr("label", o.label)}${attr("value", o.value)}></ha-input>`;
  return `<label class="fb-field">${esc(o.label)}<input${a} value="${esc(o.value)}"></label>`;
}

/* Options are set afterwards via setOptions(): ha-select takes them as a property. */
function selectField(o) {
  const a = attr("id", o.id) + attr("class", o.cls);
  if (def("ha-select")) return `<ha-select${a}${attr("label", o.label)}></ha-select>`;
  return `<label class="fb-field">${esc(o.label)}<select${a}></select></label>`;
}

function setOptions(el, opts, value) {
  if (!el) return;
  if (el.localName === "select") {
    el.innerHTML = opts.map((o) => `<option value="${esc(o.value)}">${esc(o.label)}</option>`).join("");
  } else {
    el.options = opts;
  }
  if (value !== undefined) el.value = value;
}

function setSelectValue(el, value) {
  if (!el) return;
  if (el.localName === "select") {
    if (!Array.from(el.options).some((o) => o.value === value)) el.add(new Option(value, value));
  } else if (!(el.options || []).some((o) => o.value === value)) {
    el.options = [...(el.options || []), { value, label: value }];
  }
  el.value = value;
}

/* label + switch row */
function switchRow(id, label) {
  if (def("ha-settings-row") && def("ha-switch")) {
    return `<ha-settings-row><span slot="heading">${esc(label)}</span><ha-switch id="${id}"></ha-switch></ha-settings-row>`;
  }
  if (def("ha-switch") && def("ha-formfield")) {
    return `<ha-formfield label="${esc(label)}"><ha-switch id="${id}"></ha-switch></ha-formfield>`;
  }
  return `<label class="fb-check"><input type="checkbox" id="${id}"> ${esc(label)}</label>`;
}

/* type: error | warning | info | success; content is already-escaped HTML */
function alertBox(type, content) {
  if (def("ha-alert")) return `<ha-alert alert-type="${type}">${content}</ha-alert>`;
  return `<div class="fb-alert ${type}" role="alert">${content}</div>`;
}

const CHIP_COLOR = { ok: "success-color", bad: "error-color", warn: "warning-color", now: "primary-color" };
function chip(text, kind = "") {
  const color = CHIP_COLOR[kind];
  const style = color
    ? `--md-assist-chip-label-text-color:var(--${color});--md-assist-chip-outline-color:var(--${color});` : "";
  if (def("ha-assist-chip")) {
    return `<ha-assist-chip label="${esc(text)}"${kind === "now" ? " filled" : ""}${style ? ` style="${style}"` : ""}></ha-assist-chip>`;
  }
  return `<span class="fb-chip"${color ? ` style="color:var(--${color})"` : ""}>${esc(text)}</span>`;
}

/* card with optional header; content is HTML */
function card(header, content, o = {}) {
  const a = attr("id", o.id) + ` class="card ${o.cls || ""}"` + (o.hidden ? " hidden" : "");
  if (def("ha-card")) {
    return `<ha-card${a}${attr("header", header)}><div class="card-content">${content}</div></ha-card>`;
  }
  return `<div${a.replace('class="card', 'class="fb-card card')}>${header ? `<h2>${esc(header)}</h2>` : ""}${content}</div>`;
}

const PANEL_CSS = `
  :host { display: block; }
  * { box-sizing: border-box; }
  [hidden] { display: none !important; }
  .page { padding: 16px; max-width: 1100px; margin: 0 auto; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 16px; align-items: start; }
  .grid > * { min-width: 0; }
  .card { display: block; margin-bottom: 16px; }
  .grid > .card { margin-bottom: 0; }
  .card-content { padding: 16px; }
  .card-content > ha-select, .card-content > ha-input, .card-content > .fb-field, ha-alert { display: block; margin: 8px 0; }
  .card-content > ha-select:first-child, .card-content > ha-input:first-child { margin-top: 0; }
  .two { display: grid; grid-template-columns: 1fr 1fr; gap: 0 12px; }
  .two > * { min-width: 0; display: block; margin: 8px 0; }
  @media (max-width: 600px) { .page { padding: 8px; } .two { grid-template-columns: 1fr; } }
  .chips { display: flex; flex-wrap: wrap; gap: 8px; }
  .row { display: flex; gap: 8px; align-items: center; }
  .row > ha-input, .row > .fb-field { flex: 1; min-width: 0; }
  .actions { display: flex; flex-wrap: wrap; gap: 8px; }
  .save { margin-top: 12px; }
  .tip { white-space: pre-wrap; word-wrap: break-word; line-height: 1.6; }
  .tip.empty, .empty { color: var(--secondary-text-color); font-style: italic; }
  .sub { font-size: var(--ha-font-size-s, 12px); color: var(--secondary-text-color); margin-top: 8px; }
  .hist { max-height: 60vh; overflow-y: auto; }
  .hist-item { padding: 10px 0; line-height: 1.5; border-bottom: 1px solid var(--divider-color); }
  .hist-item:last-child { border-bottom: none; }
  .hist-num { display: inline-block; min-width: 28px; font-weight: 500; color: var(--primary-color); }
  .summary { white-space: pre-wrap; word-wrap: break-word; line-height: 1.6; }
  .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(110px, 1fr)); gap: 12px; text-align: center; }
  .stats b { display: block; font-size: 24px; font-weight: 400; color: var(--primary-color); }
  .stats span { font-size: var(--ha-font-size-s, 12px); color: var(--secondary-text-color); }
  .c-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 4px; }
  .c-dot { width: 10px; height: 10px; border-radius: 50%; background: var(--disabled-text-color); flex: none; }
  .c-dot.online { background: var(--success-color); }
  .c-dot.offline { background: var(--error-color); }
  .c-title { font-size: var(--ha-font-size-l, 16px); font-weight: 500; }
  .c-meta { font-size: var(--ha-font-size-s, 12px); color: var(--secondary-text-color); margin-bottom: 4px; }
  .c-tip { font-style: italic; color: var(--secondary-text-color); margin: 4px 0 8px; word-wrap: break-word; }
  /* fallbacks when an HA element is missing */
  .fb-head { padding: 12px 16px; background: var(--app-header-background-color); color: var(--app-header-text-color); }
  .fb-head h1 { margin: 0; font-size: 20px; font-weight: 500; }
  .fb-tabs { display: flex; flex-wrap: wrap; gap: 4px; padding: 0 16px; border-bottom: 1px solid var(--divider-color); }
  .fb-tabs .fb-btn { background: none; border: 0; border-radius: 0; color: var(--secondary-text-color); }
  .fb-tabs .fb-btn.active { color: var(--primary-color); border-bottom: 3px solid var(--primary-color); }
  .fb-btn { font: inherit; padding: 8px 16px; border: 1px solid var(--primary-color); border-radius: 18px; cursor: pointer; background: var(--primary-color); color: var(--text-primary-color); }
  .fb-btn.outlined { background: none; color: var(--primary-color); }
  .fb-btn.danger { border-color: var(--error-color); background: var(--error-color); color: #fff; }
  .fb-btn.danger.outlined { background: none; color: var(--error-color); }
  .fb-btn:disabled { opacity: .45; cursor: not-allowed; }
  .fb-field, .fb-check { display: block; margin: 8px 0; color: var(--secondary-text-color); }
  .fb-check { display: flex; gap: 8px; align-items: center; }
  .fb-field input, .fb-field select { display: block; width: 100%; padding: 8px; font: inherit; color: var(--primary-text-color); background: var(--card-background-color); border: 1px solid var(--divider-color); border-radius: 6px; }
  .fb-alert { margin: 8px 0; padding: 8px 12px; border: 1px solid var(--divider-color); border-radius: 6px; }
  .fb-alert.error { border-color: var(--error-color); color: var(--error-color); }
  .fb-chip { padding: 2px 10px; border: 1px solid var(--divider-color); border-radius: 12px; }
  .fb-card { background: var(--card-background-color); border: 1px solid var(--divider-color); border-radius: var(--ha-card-border-radius, 12px); padding: 16px; }
  .fb-card h2 { margin: 0 0 10px; font-size: 18px; font-weight: 500; }
  dialog.fb-dialog { max-width: 480px; width: 90%; background: var(--card-background-color); color: var(--primary-text-color); border: 1px solid var(--divider-color); border-radius: 12px; }
  dialog.fb-dialog .actions { margin-top: 16px; justify-content: flex-end; }
`;

class GamingAssistantPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._lang = "en";
    this._tab = "overview";
    this._started = false;
    this._built = false;
    this._setupPopulated = false;
    this._clientRows = {};
    this._lastHint = "";
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    const lang = (hass.language || "en").substring(0, 2);
    const langChanged = lang !== this._lang;
    this._lang = lang;
    if (this._frame) this._frame.hass = hass;
    if (first && !this._started) {
      this._started = true;
      this._start();
      return;
    }
    if (!this._built) return;
    if (langChanged) this._build();
    this._updateStates();
  }

  set narrow(narrow) {
    this._narrow = !!narrow;
    if (this._frame) this._frame.narrow = this._narrow;
  }

  set panel(panel) {
    this._panel = panel;
  }

  set route(route) {
    this._route = route;
    const tab = this._tabFromRoute();
    if (tab && tab !== this._tab) {
      this._tab = tab;
      if (this._built) this._showTab();
    }
  }

  _t(key) {
    return (I18N[this._lang] || I18N.en)[key] || I18N.en[key] || key;
  }

  $(id) {
    return this.shadowRoot.getElementById(id);
  }

  // -- Routing: /gaming-assistant/<tab> ------------------------------------------

  _prefix() {
    return (this._route && this._route.prefix) || PATH;
  }

  _tabFromRoute() {
    const m = ((this._route && this._route.path) || "").match(/^\/([a-z]+)/);
    return m && TAB_KEYS.includes(m[1]) ? m[1] : null;
  }

  _gotoTab(tab) {
    this._tab = tab;
    this._showTab();
    try {
      const target = `${this._prefix()}/${tab}`;
      if (window.location.pathname !== target) {
        window.history.pushState(null, "", target);
        window.dispatchEvent(new CustomEvent("location-changed", { detail: { replace: false } }));
      }
    } catch (_e) { /* tab stays switched even without an address bar */ }
  }

  _showTab() {
    for (const key of TAB_KEYS) {
      const pane = this.$(`pane-${key}`);
      if (pane) pane.hidden = key !== this._tab;
    }
    if (this._frame) {
      this._frame.route = { prefix: this._prefix(), path: `/${this._tab}` };
      this._frame.tabs = TABS.map(([key, label, icon]) => ({
        path: `${this._prefix()}/${key}`, name: this._t(label), iconPath: icon,
      }));
    } else {
      const nav = this.$("fb-tabs");
      if (nav) {
        nav.innerHTML = TABS.map(([key, label]) =>
          `<button class="fb-btn ${key === this._tab ? "active" : ""}" data-act="tab" data-tab="${key}">${esc(this._t(label))}</button>`).join("");
      }
    }
  }

  // -- Start and layout ----------------------------------------------------------

  async _start() {
    this.shadowRoot.innerHTML = `<style>${PANEL_CSS}</style><div class="page"><ha-spinner></ha-spinner></div>`;
    await loadBuildingBlocks();
    const tab = this._tabFromRoute();
    if (tab) this._tab = tab;
    this._build();
    this._updateStates();
  }

  _build() {
    const t = (k) => this._t(k);
    const hasFrame = def("hass-tabs-subpage");

    const overview = `
      <div class="grid">
        ${card(t("status"), `<div class="chips" id="chips"></div>`)}
        ${card(t("currentTip"), `
          <div class="tip empty" id="current-tip">${esc(t("waitingForTips"))}</div>
          <div class="sub" id="current-tip-game"></div>`)}
        ${card(t("askTitle"), `
          <div class="row">
            ${textField({ id: "ask-input", label: t("askTitle"), placeholder: t("askPlaceholder") })}
            ${button(t("askSend"), { id: "btn-ask" })}
          </div>`)}
        ${card(t("actions"), `
          <div class="actions">
            ${button(t("start"), { act: "start" })}
            ${button(t("stop"), { act: "stop", outlined: true })}
            ${button(t("analyzeNow"), { act: "analyze", outlined: true })}
            ${button(t("announce"), { act: "announce", outlined: true })}
            ${button(t("summarize"), { act: "summarize_session", outlined: true })}
            ${button(t("clearHistory"), { act: "clear", outlined: true, danger: true })}
          </div>`)}
        ${card(t("session"), `
          ${selectField({ id: "ctrl-mode", label: t("mode") })}
          ${selectField({ id: "ctrl-game-pick", label: t("gamePick") })}
          ${textField({ id: "ctrl-game", label: t("game"), placeholder: t("gamePlaceholder") })}
          ${selectField({ id: "ctrl-source-type", label: t("sourceType") })}
          ${selectField({ id: "ctrl-spoiler", label: t("spoilerLevel") })}`)}
      </div>`;

    const history = `
      <div class="grid">
        ${card(t("tipHistory"), `
          <div class="hist" id="history-list"><span class="empty">${esc(t("noTipsYet"))}</span></div>
          <div class="actions save">${button(t("clearHistory"), { act: "clear", outlined: true, danger: true })}</div>`)}
        ${card(t("sessionSummary"), `
          <div class="summary empty" id="session-summary">${esc(t("noSummary"))}</div>
          <div class="actions save">${button(t("summarize"), { act: "summarize_session", outlined: true })}</div>`)}
      </div>`;

    const clients = `
      <div id="clients-list"></div>`;

    const settings = `
      <div class="grid">
        ${card(t("automation"), `
          <div class="two">
            ${textField({ id: "ctrl-interval", label: t("intervalS"), type: "number", min: 5, max: 120, step: 1 })}
            ${textField({ id: "ctrl-timeout", label: t("timeoutS"), type: "number", min: 10, max: 300, step: 5 })}
          </div>
          ${switchRow("ctrl-auto-announce", t("autoAnnounce"))}
          ${switchRow("ctrl-auto-summary", t("autoSummary"))}`)}
        ${card(t("diagnostics"), `
          <div class="stats">
            <div><b id="diag-latency">--</b><span>${esc(t("latency"))}</span></div>
            <div><b id="diag-frames">0</b><span>${esc(t("frames"))}</span></div>
            <div><b id="diag-watchers">0</b><span>${esc(t("watchers"))}</span></div>
            <div><b id="diag-errors">0</b><span>${esc(t("errors"))}</span></div>
          </div>`)}
        ${card(t("setup"), `
          ${selectField({ id: "setup-camera", label: t("camera") })}
          ${selectField({ id: "setup-speaker", label: t("speaker") })}
          ${selectField({ id: "setup-tts", label: t("ttsEngine") })}
          ${selectField({ id: "setup-model", label: t("aiModel") })}
          <div class="save">${button(t("save"), { id: "btn-save-setup" })}</div>`)}
      </div>`;

    const panes = `
      <div class="page" id="pane-overview">${overview}</div>
      <div class="page" id="pane-history" hidden>${history}</div>
      <div class="page" id="pane-clients" hidden>${clients}</div>
      <div class="page" id="pane-settings" hidden>${settings}</div>
      <div id="top"></div>`;

    this.shadowRoot.innerHTML = `<style>${PANEL_CSS}</style>`
      + (hasFrame
        ? `<hass-tabs-subpage id="frame">${panes}</hass-tabs-subpage>`
        : `<div class="fb-head"><h1>${esc(t("title"))}</h1></div><nav class="fb-tabs" id="fb-tabs"></nav>${panes}`);

    this._frame = hasFrame ? this.$("frame") : null;
    if (this._frame) {
      this._frame.mainPage = true;
      this._frame.hass = this._hass;
      this._frame.narrow = !!this._narrow;
    }

    // Fresh DOM: forget everything that pointed into the old one.
    this._clientRows = {};
    this._setupPopulated = false;
    this._chipsHtml = null;
    this._historyKey = null;
    this._packKey = null;
    this._modelKey = null;
    this._fillStaticSelects();
    this._bindEvents();
    this._showTab();
    this._built = true;
  }

  _fillStaticSelects() {
    const t = (k) => this._t(k);
    setOptions(this.$("ctrl-mode"), [
      { value: "coach", label: t("modeCoach") }, { value: "coplay", label: t("modeCoplay") },
      { value: "opponent", label: t("modeOpponent") }, { value: "analyst", label: t("modeAnalyst") },
    ], "coach");
    setOptions(this.$("ctrl-source-type"), [
      { value: "auto", label: t("sourceAuto") }, { value: "console", label: t("sourceConsole") },
      { value: "tabletop", label: t("sourceTabletop") },
    ], "auto");
    setOptions(this.$("ctrl-spoiler"), [
      { value: "none", label: t("spoilerNone") }, { value: "low", label: t("spoilerLow") },
      { value: "medium", label: t("spoilerMedium") }, { value: "high", label: t("spoilerHigh") },
    ], "medium");
    setOptions(this.$("ctrl-game-pick"), [{ value: NONE, label: t("gameAuto") }], NONE);
  }

  // -- Events ----------------------------------------------------------------------

  _bindEvents() {
    const root = this.shadowRoot;
    root.addEventListener("click", (e) => {
      const el = e.target.closest && e.target.closest("[data-act],#btn-ask,#btn-save-setup");
      if (!el || el.disabled || el.hasAttribute("disabled")) return;
      if (el.id === "btn-ask") return this._submitQuestion();
      if (el.id === "btn-save-setup") return this._saveSetup(el);
      this._action(el.dataset.act, el);
    });
    // ha-select reports "selected" (detail.value); the plain fallback uses "change".
    root.addEventListener("selected", (e) => {
      const el = e.target;
      if (el.localName !== "ha-select") return;
      const value = e.detail && e.detail.value !== undefined ? String(e.detail.value) : el.value;
      this._onSelect(el, value);
    });
    root.addEventListener("change", (e) => {
      const el = e.target;
      if (el.localName === "select") this._onSelect(el, el.value);
      else if (el.localName === "ha-switch" || (el.localName === "input" && el.type === "checkbox")) this._onSwitch(el);
      else if (el.localName === "ha-input" || el.localName === "input") this._onField(el);
    });
    root.addEventListener("focusout", (e) => {
      if (e.target.localName === "ha-input" || e.target.localName === "input") this._onField(e.target);
    });
    root.addEventListener("keydown", (e) => {
      if (e.key !== "Enter") return;
      const id = e.target.id;
      if (id === "ask-input") { e.preventDefault(); this._submitQuestion(); }
      if (id === "ctrl-game") { e.preventDefault(); this._onField(e.target); }
    });
  }

  _onSelect(el, value) {
    const entity = { "ctrl-mode": this._ids.mode, "ctrl-source-type": this._ids.sourceType, "ctrl-spoiler": this._ids.spoiler }[el.id];
    if (entity) {
      const st = this._getState(entity);
      if (st && st.state === value) return;
      this._callService("select", "select_option", entity, { option: value });
    } else if (el.id === "ctrl-game-pick") {
      if (this._pickFilling) return;
      const name = value === NONE ? "" : value;
      if (name === this._lastHint) return;
      this._lastHint = name;
      this._callDomainService("set_game_hint", { game_hint: name });
    }
  }

  _onSwitch(el) {
    const entity = { "ctrl-auto-announce": this._ids.autoAnnounce, "ctrl-auto-summary": this._ids.autoSummary }[el.id];
    if (!entity) return;
    const st = this._getState(entity);
    if (st && (st.state === "on") === !!el.checked) return;
    this._callService("switch", el.checked ? "turn_on" : "turn_off", entity);
  }

  _onField(el) {
    if (el.id === "ctrl-game") {
      const hint = String(el.value || "").trim();
      if (hint === this._lastHint) return;
      this._lastHint = hint;
      this._callDomainService("set_game_hint", { game_hint: hint });
    } else if (el.id === "ctrl-interval" || el.id === "ctrl-timeout") {
      const isInterval = el.id === "ctrl-interval";
      const st = this._getState(isInterval ? this._ids.interval : this._ids.timeout);
      const value = Number(el.value);
      if (el.value === "" || Number.isNaN(value) || (st && Number(st.state) === value)) return;
      this._callService("number", "set_value", isInterval ? this._ids.interval : this._ids.timeout, { value });
    }
  }

  async _submitQuestion() {
    const input = this.$("ask-input");
    const btn = this.$("btn-ask");
    const question = String(input.value || "").trim();
    if (!question || btn.disabled) return;
    btn.disabled = true;
    btn.textContent = this._t("askSending");
    const ok = await this._callDomainService("ask", { question });
    btn.disabled = false;
    btn.textContent = this._t("askSend");
    if (ok) {
      input.value = "";
      this._notify(this._t("askSent"));
    }
    input.focus();
  }

  _action(act, el) {
    switch (act) {
      case "tab": return this._gotoTab(el.dataset.tab);
      case "clear": return this._confirmClear();
      case "start": case "stop": case "analyze": case "announce": case "summarize_session":
        return this._callDomainService(act);
      default: return undefined;
    }
  }

  async _saveSetup(btn) {
    btn.disabled = true;
    const val = (id) => { const v = this.$(id).value; return v === NONE ? "" : (v || ""); };
    const data = {
      camera_entity: val("setup-camera"),
      tts_entity: val("setup-tts"),
      tts_target: val("setup-speaker"),
    };
    const model = val("setup-model");
    if (model) data.model = model;
    const ok = await this._callDomainService("configure", data);
    if (ok) this._notify(this._t("saved"));
    btn.textContent = this._t("saved");
    setTimeout(() => { btn.textContent = this._t("save"); btn.disabled = false; }, 2000);
  }

  // -- Dialog (replaces confirm()) ----------------------------------------------------

  _confirmClear() {
    const t = (k) => this._t(k);
    const cancel = button(t("cancel"), { id: "dlg-no", slot: "footer", outlined: true, extra: " dialogInitialFocus" });
    const yes = button(t("clearHistory"), { id: "dlg-yes", slot: "footer", danger: true });
    const body = `<p>${esc(t("confirmClear"))}</p>`;
    const top = this.$("top");
    top.innerHTML = def("ha-dialog")
      ? `<ha-dialog id="dlg" header-title="${esc(t("confirmClearTitle"))}" prevent-scrim-close>${body}${cancel}${yes}</ha-dialog>`
      : `<dialog id="dlg" class="fb-dialog"><h2>${esc(t("confirmClearTitle"))}</h2>${body}<div class="actions">${cancel}${yes}</div></dialog>`;
    const dlg = this.$("dlg");
    const close = () => { if (this.$("dlg") === dlg) top.innerHTML = ""; };
    if (dlg.localName === "ha-dialog") {
      dlg.headerTitle = t("confirmClearTitle");
      dlg.preventScrimClose = true;
      dlg.open = true;
    } else if (dlg.showModal) {
      try { dlg.showModal(); } catch (_e) { dlg.setAttribute("open", ""); }
    }
    this.$("dlg-no").addEventListener("click", close);
    this.$("dlg-yes").addEventListener("click", async () => {
      close();
      const ok = await this._callDomainService("clear_history");
      if (ok) this._notify(t("historyCleared"));
    });
    dlg.addEventListener("closed", close);
    dlg.addEventListener("close", close);
  }

  // -- Services and toasts ---------------------------------------------------------

  /* HA shows the toast itself (bottom of the screen). */
  _notify(message) {
    this.dispatchEvent(new CustomEvent("hass-notification", {
      detail: { message, duration: 4000 }, bubbles: true, composed: true,
    }));
  }

  async _callService(domain, service, entityId, data = {}) {
    if (!this._hass) return false;
    try {
      await this._hass.callService(domain, service, { entity_id: entityId, ...data });
      return true;
    } catch (err) {
      console.error(`Gaming Assistant: ${domain}.${service} failed:`, err);
      this._notify(`${this._t("callFailed")}: ${err && err.message ? err.message : `${domain}.${service}`}`);
      return false;
    }
  }

  async _callDomainService(service, data = {}) {
    if (!this._hass) return false;
    try {
      await this._hass.callService(DOMAIN, service, data);
      return true;
    } catch (err) {
      console.error(`Gaming Assistant: ${DOMAIN}.${service} failed:`, err);
      this._notify(`${this._t("callFailed")}: ${err && err.message ? err.message : `${DOMAIN}.${service}`}`);
      return false;
    }
  }

  /* Resolve each ENTITIES key to the id that exists on this install (first candidate wins). */
  get _ids() {
    const states = (this._hass && this._hass.states) || {};
    const ids = {};
    for (const [key, cand] of Object.entries(ENTITIES)) {
      const list = Array.isArray(cand) ? cand : [cand];
      ids[key] = list.find((e) => states[e]) || list[0];
    }
    return ids;
  }

  _getState(entityId) {
    if (!this._hass || !this._hass.states[entityId]) return null;
    return this._hass.states[entityId];
  }

  _isEditing(el) {
    return !!el && this.shadowRoot.activeElement === el;
  }

  // -- State -> UI -----------------------------------------------------------------------

  _updateStates() {
    if (!this._hass || !this._built) return;
    const t = (k) => this._t(k);

    // Status chips
    const gaming = this._getState(this._ids.gamingMode);
    const isActive = !!gaming && gaming.state === "on";
    const status = this._getState(this._ids.status);
    const history = this._getState(this._ids.history);
    const attrs = (status && status.attributes) || {};
    const chips = [
      chip(isActive ? t("active") : t("inactive"), isActive ? "ok" : ""),
      chip(status ? status.state : "--", status && status.state === "analyzing" ? "now" : ""),
      chip(`${t("tips")}: ${history ? history.state || "0" : "0"}`),
      chip(`${t("model")}: ${attrs.active_model || "--"}`),
      chip(`${t("client")}: ${attrs.active_client_id || "--"}`),
    ].join("");
    if (chips !== this._chipsHtml) {
      this._chipsHtml = chips;
      this.$("chips").innerHTML = chips;
    }

    // Current tip
    const tip = this._getState(this._ids.tip);
    const tipBox = this.$("current-tip");
    if (tip) {
      const fullTip = (tip.attributes && tip.attributes.full_tip) || tip.state;
      if (fullTip && fullTip !== "Waiting for tips...") {
        tipBox.textContent = fullTip;
        tipBox.classList.remove("empty");
      } else {
        tipBox.textContent = t("waitingForTips");
        tipBox.classList.add("empty");
      }
      const game = tip.attributes && tip.attributes.game;
      this.$("current-tip-game").textContent = game ? `${t("game")}: ${game}` : "";
    }

    // Entity-backed controls (never overwritten while the user is working in them)
    this._syncSelect(this.$("ctrl-mode"), this._ids.mode);
    this._syncSelect(this.$("ctrl-source-type"), this._ids.sourceType);
    this._syncSelect(this.$("ctrl-spoiler"), this._ids.spoiler);
    const interval = this._getState(this._ids.interval);
    const intEl = this.$("ctrl-interval");
    if (interval && !this._isEditing(intEl) && String(intEl.value) !== String(interval.state)) intEl.value = interval.state;
    const timeout = this._getState(this._ids.timeout);
    const toEl = this.$("ctrl-timeout");
    if (timeout && !this._isEditing(toEl) && String(toEl.value) !== String(timeout.state)) toEl.value = timeout.state;
    const autoAnn = this._getState(this._ids.autoAnnounce);
    if (autoAnn) this.$("ctrl-auto-announce").checked = autoAnn.state === "on";
    const autoSum = this._getState(this._ids.autoSummary);
    if (autoSum) this.$("ctrl-auto-summary").checked = autoSum.state === "on";

    // History
    if (history && history.attributes && history.attributes.recent_tips) {
      const tips = history.attributes.recent_tips.slice().reverse();
      const key = tips.map((x) => x.tip).join("\n");
      if (key !== this._historyKey) {
        this._historyKey = key;
        this.$("history-list").innerHTML = tips.length
          ? tips.map((entry, i) =>
            `<div class="hist-item"><span class="hist-num">${i + 1}.</span>${esc(entry.tip)}</div>`).join("")
          : `<span class="empty">${esc(t("noTipsYet"))}</span>`;
      }
    }

    // Session summary
    const summary = this._getState(this._ids.sessionSummary);
    const sumEl = this.$("session-summary");
    if (summary) {
      const full = (summary.attributes && summary.attributes.full_summary) || summary.state;
      const has = !!full && full !== "No summary yet";
      sumEl.textContent = has ? full : t("noSummary");
      sumEl.classList.toggle("empty", !has);
    }

    // Diagnostics
    const latency = this._getState(this._ids.latency);
    if (latency) {
      const val = parseFloat(latency.state);
      this.$("diag-latency").textContent = Number.isNaN(val) ? "--" : val.toFixed(1);
    }
    const frames = this._getState(this._ids.frames);
    if (frames) this.$("diag-frames").textContent = frames.state || "0";
    const watchers = this._getState(this._ids.watchers);
    if (watchers) this.$("diag-watchers").textContent = watchers.state || "0";
    const errors = this._getState(this._ids.errorCount);
    if (errors) this.$("diag-errors").textContent = errors.state || "0";

    if (status && status.attributes) {
      this._updateGame(status.attributes);
      this._updateModelDropdown(status.attributes);
    }

    this._updateClients();

    if (!this._setupPopulated) {
      this._populateSetupDropdowns();
      this._setupPopulated = true;
    }
  }

  _syncSelect(el, entityId) {
    const st = this._getState(entityId);
    if (!el || !st || !st.state || st.state === "unknown" || st.state === "unavailable") return;
    if (el.value !== st.state) setSelectValue(el, st.state);
  }

  _updateGame(attrs) {
    const packs = attrs.available_game_packs || [];
    const hint = attrs.default_game_hint || "";
    const input = this.$("ctrl-game");
    const pick = this.$("ctrl-game-pick");
    const packKey = packs.map((p) => p.id).join(",");
    this._pickFilling = true;
    setTimeout(() => { this._pickFilling = false; }, 0);
    if (this._packKey !== packKey) {
      this._packKey = packKey;
      setOptions(pick, [{ value: NONE, label: this._t("gameAuto") }]
        .concat(packs.map((p) => ({ value: p.name, label: p.name }))), pick.value || NONE);
    }
    this._lastHint = hint;
    const names = packs.map((p) => p.name);
    if (!this._isEditing(pick)) {
      const want = hint && names.includes(hint) ? hint : NONE;
      if (pick.value !== want) pick.value = want;
    }
    if (!this._isEditing(input) && input.value !== hint) input.value = hint;
  }

  // -- Clients (GA-114) ----------------------------------------------------------------

  _updateClients() {
    const listEl = this.$("clients-list");
    if (!listEl) return;
    const sensor = this._getState(this._ids.clients);
    const clients = (sensor && sensor.attributes && sensor.attributes.clients) || {};
    const ids = Object.keys(clients);
    // Rebuild only when clients come or go, so edits in progress survive the
    // frequent state updates; the rows are filled in place below.
    const idsKey = ids.join("\n");
    if (listEl.dataset.idsKey !== idsKey) {
      listEl.dataset.idsKey = idsKey;
      listEl.textContent = "";
      this._clientRows = {};
      if (ids.length === 0) {
        listEl.innerHTML = alertBox("info", esc(this._t("noClients")));
      }
      const wrap = document.createElement("div");
      wrap.className = "grid";
      for (const id of ids) {
        this._clientRows[id] = this._buildClientRow(id);
        wrap.appendChild(this._clientRows[id].el);
      }
      if (ids.length) listEl.appendChild(wrap);
    }
    for (const id of ids) this._fillClientRow(this._clientRows[id], id, clients[id] || {});
  }

  _speakerOptions() {
    const states = (this._hass && this._hass.states) || {};
    return [{ value: NONE, label: this._t("globalSetting") }].concat(
      Object.keys(states).filter((e) => e.startsWith("media_player.")).sort()
        .map((e) => ({ value: e, label: states[e].attributes.friendly_name || e })));
  }

  _buildClientRow(id) {
    const t = (k) => this._t(k);
    const el = document.createElement("div");
    el.innerHTML = card("", `
      <div class="c-head"><span class="c-dot"></span><span class="c-title"></span></div>
      <div class="c-meta"></div>
      <div class="c-tip"></div>
      ${selectField({ cls: "c-mode", label: t("mode") })}
      ${selectField({ cls: "c-speaker", label: t("speaker") })}
      ${textField({ cls: "c-hint", label: t("game"), placeholder: t("clientGameHint") })}
      <div class="save">${button(t("save"), { cls: "c-save" })}</div>`);
    const q = (s) => el.querySelector(s);
    const row = {
      el, dot: q(".c-dot"), name: q(".c-title"), meta: q(".c-meta"), tip: q(".c-tip"),
      mode: q(".c-mode"), speaker: q(".c-speaker"), hint: q(".c-hint"), save: q(".c-save"),
      dirty: false, filling: false,
    };
    setOptions(row.mode, [
      { value: NONE, label: t("globalSetting") }, { value: "coach", label: t("modeCoach") },
      { value: "coplay", label: t("modeCoplay") }, { value: "opponent", label: t("modeOpponent") },
      { value: "analyst", label: t("modeAnalyst") },
    ], NONE);
    setOptions(row.speaker, this._speakerOptions(), NONE);

    const markDirty = () => { if (!row.filling) row.dirty = true; };
    el.addEventListener("input", markDirty);
    el.addEventListener("selected", markDirty);
    el.addEventListener("change", (e) => { if (e.target.localName === "select") markDirty(); });
    row.save.addEventListener("click", async () => {
      row.save.disabled = true;
      const ok = await this._callDomainService("set_client_options", {
        client_id: id,
        assistant_mode: row.mode.value === NONE || !row.mode.value ? "global" : row.mode.value,
        tts_target: row.speaker.value === NONE ? "" : (row.speaker.value || ""),
        game_hint: String(row.hint.value || "").trim(),
      });
      if (ok) {
        row.dirty = false;
        this._notify(t("saved"));
      }
      row.save.textContent = t("saved");
      setTimeout(() => { row.save.textContent = t("save"); row.save.disabled = false; }, 1500);
    });
    return row;
  }

  _fillClientRow(row, id, client) {
    const t = (k) => this._t(k);
    row.dot.className = "c-dot" + (client.online === true ? " online" : client.online === false ? " offline" : "");
    row.name.textContent = client.name && client.name !== id ? `${client.name} (${id})` : id;
    const parts = [client.type && client.type !== "unknown" ? client.type : ""];
    if (client.active) parts.push(t("activeClient"));
    if (client.game) parts.push(client.game);
    if (client.last_seen) parts.push(`${t("lastSeen")} ${String(client.last_seen).replace("T", " ")}`);
    row.meta.textContent = parts.filter(Boolean).join(" · ");
    row.tip.textContent = client.last_tip || "";
    row.tip.hidden = !client.last_tip;

    // Show the stored settings unless the user is editing this row.
    if (row.dirty || row.el.contains(this.shadowRoot.activeElement)) return;
    row.filling = true;
    const options = client.options || {};
    const mode = options.assistant_mode && options.assistant_mode !== "global" ? options.assistant_mode : NONE;
    if (row.mode.value !== mode) setSelectValue(row.mode, mode);
    const target = options.tts_target || NONE;
    if (row.speaker.value !== target) setSelectValue(row.speaker, target);
    const hint = options.game_hint || "";
    if (row.hint.value !== hint) row.hint.value = hint;
    setTimeout(() => { row.filling = false; }, 0);
  }

  // -- Setup dropdowns ---------------------------------------------------------------------

  _entityOptions(prefix, emptyLabel) {
    const states = this._hass.states;
    return [{ value: NONE, label: emptyLabel }].concat(
      Object.keys(states).filter((e) => e.startsWith(prefix)).sort()
        .map((e) => ({ value: e, label: states[e].attributes.friendly_name || e })));
  }

  _populateSetupDropdowns() {
    if (!this._hass) return;
    setOptions(this.$("setup-camera"), this._entityOptions("camera.", this._t("noCamera")), NONE);
    setOptions(this.$("setup-tts"), this._entityOptions("tts.", this._t("noTts")), NONE);
    setOptions(this.$("setup-speaker"), this._entityOptions("media_player.", this._t("defaultSpeaker")), NONE);

    // AI model: use the models fetched server-side by the coordinator
    const st = this._getState(this._ids.status);
    const attrs = (st && st.attributes) || {};
    const serverModels = attrs.available_models || [];
    const activeModel = attrs.active_model || "";
    const fallback = ["qwen2.5vl", "llava", "llava:13b", "bakllava", "llama3.2-vision"];
    const list = serverModels.length > 0 ? serverModels : fallback;
    const ordered = activeModel ? [activeModel, ...list.filter((m) => m !== activeModel)] : list;
    setOptions(this.$("setup-model"), ordered.map((m) => ({ value: m, label: m })), activeModel || ordered[0]);
    this._modelKey = serverModels.length > 0 ? ordered.join(",") : null;

    this._loadCurrentConfig();
  }

  async _loadCurrentConfig() {
    if (!this._hass) return;
    try {
      const entries = await this._hass.callWS({ type: "config_entries/get", domain: DOMAIN });
      if (!entries || entries.length === 0) return;
      let merged = {};
      try {
        const detail = await this._hass.callWS({
          type: "config_entries/get_single", entry_id: entries[0].entry_id,
        });
        merged = { ...(detail.data || {}), ...(detail.options || {}) };
      } catch (_e) {
        setSelectValue(this.$("setup-model"), "qwen2.5vl");
        return;
      }
      if (!this._built) return;
      if (merged.camera_entity) setSelectValue(this.$("setup-camera"), merged.camera_entity);
      if (merged.tts_entity) setSelectValue(this.$("setup-tts"), merged.tts_entity);
      if (merged.tts_target) setSelectValue(this.$("setup-speaker"), merged.tts_target);
      if (merged.model) setSelectValue(this.$("setup-model"), merged.model);
    } catch (err) {
      console.warn("Gaming Assistant: Could not load config entries:", err);
    }
  }

  _updateModelDropdown(attrs) {
    const el = this.$("setup-model");
    const models = attrs.available_models || [];
    if (!el || models.length === 0) return;
    const activeModel = attrs.active_model || "";
    const ordered = activeModel ? [activeModel, ...models.filter((m) => m !== activeModel)] : models;
    const key = ordered.join(",");
    if (this._modelKey === key) return;
    this._modelKey = key;
    const current = el.value;
    setOptions(el, ordered.map((m) => ({ value: m, label: m })));
    const preferred = activeModel || current;
    if (preferred) setSelectValue(el, preferred);
  }
}

customElements.define("gaming-assistant-panel", GamingAssistantPanel);
