const runtimeBackgroundUrl = window.__runtimeBackgroundUrl || "";

window.htmlHeadContent = `
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<meta lang="zh-CN" />
<style>
  :root {
    --ink: #e8f0ed;
    --ink-muted: #9db2b0;
    --teal: #8dc9bc;
    --teal-deep: #5fa99d;
    --coral: #d88773;
    --panel: rgba(7, 25, 34, 0.88);
    --panel-deep: rgba(4, 16, 23, 0.86);
    --line: rgba(141, 201, 188, 0.24);
  }

  * { box-sizing: border-box; }

  html, body { min-height: 100%; }

  body {
    margin: 0;
    min-width: 760px;
    color: var(--ink);
    background-color: #07131b;
    background-image: linear-gradient(rgba(4, 12, 18, 0.56), rgba(4, 12, 18, 0.78)), url("${runtimeBackgroundUrl}");
    background-size: cover;
    background-position: center;
    background-attachment: fixed;
    font-family: "Segoe UI", "Microsoft YaHei UI", sans-serif;
  }

  button, input { font: inherit; }
  button { color: inherit; }

  .app-shell {
    width: min(1180px, calc(100vw - 44px));
    margin: 0 auto;
    padding: 28px 0 22px;
  }

  .topbar, .panel-heading, .matrix-toolbar, .control-label {
    display: flex;
    align-items: center;
  }

  .topbar {
    justify-content: space-between;
    gap: 24px;
    margin-bottom: 22px;
  }

  .topbar-actions { display: flex; align-items: center; gap: 8px; }

  .connection-status { display: inline-flex; align-items: center; gap: 10px; min-width: 220px; padding: 10px 13px; color: var(--ink-muted); background: rgba(7, 25, 34, 0.82); border: 1px solid var(--line); border-radius: 14px; }
  .status-dot { width: 9px; height: 9px; flex: 0 0 9px; border-radius: 50%; background: #d6b277; box-shadow: 0 0 0 5px rgba(214, 178, 119, 0.12); }
  .connection-status[data-state="online"] .status-dot { background: var(--teal); box-shadow: 0 0 0 5px rgba(141, 201, 188, 0.12); }
  .connection-status[data-state="offline"], .connection-status[data-state="error"] { border-color: rgba(216, 135, 115, 0.4); }
  .connection-status[data-state="offline"] .status-dot, .connection-status[data-state="error"] .status-dot { background: var(--coral); box-shadow: 0 0 0 5px rgba(216, 135, 115, 0.12); }
  .status-copy { display: grid; gap: 2px; min-width: 70px; }
  .status-state { color: var(--ink); font-size: 12px; font-weight: 750; }
  .status-age, .status-message { color: var(--ink-muted); font-size: 10px; }
  .status-message { margin-left: auto; text-align: right; }
  .maintenance-button.tool-button { min-height: 0; padding: 9px 13px; color: var(--ink-muted); background: rgba(19, 43, 53, 0.78); border: 1px solid rgba(216, 135, 115, 0.36); border-radius: 10px; cursor: pointer; font-size: 12px; transition: background 160ms ease, border-color 160ms ease, color 160ms ease, transform 160ms ease; }
  .maintenance-button.tool-button:hover { color: var(--coral); background: rgba(38, 61, 67, 0.9); border-color: var(--coral); transform: translateY(-1px); }
  .maintenance-button.tool-button:active { color: #07131b; background: var(--coral); border-color: var(--coral); transform: none; }
  .maintenance-button:disabled { opacity: 0.58; cursor: default; transform: none; }
  .maintenance-button:focus-visible { outline: 2px solid var(--teal); outline-offset: 3px; }
  .device-actions { display: flex; align-items: center; gap: 6px; }

  body.modal-open { overflow: hidden; }
  .modal-layer { position: fixed; inset: 0; z-index: 1000; display: grid; place-items: center; padding: 24px; background: rgba(3, 13, 19, 0.62); backdrop-filter: blur(10px); }
  .modal-layer[hidden] { display: none; }
  .modal-backdrop { position: absolute; inset: 0; }
  .modal-dialog { position: relative; width: min(440px, 100%); padding: 24px; color: var(--ink); background: linear-gradient(145deg, rgba(12, 35, 45, 0.98), rgba(7, 23, 31, 0.98)); border: 1px solid var(--line); border-radius: 20px 8px 20px 20px; box-shadow: 0 24px 70px rgba(0, 0, 0, 0.42); }
  .modal-dialog[data-variant="danger"] { border-color: rgba(216, 135, 115, 0.55); }
  .modal-eyebrow { margin-bottom: 8px; color: var(--teal); font-size: 10px; font-weight: 750; letter-spacing: 0.14em; text-transform: uppercase; }
  .modal-title { margin: 0; color: var(--ink); font-size: 20px; letter-spacing: -0.03em; }
  .modal-message { margin: 10px 0 0; color: var(--ink-muted); font-size: 12px; line-height: 1.7; white-space: pre-wrap; }
  .modal-input-wrap { display: grid; gap: 7px; margin-top: 18px; color: var(--ink-muted); font-size: 11px; }
  .modal-input-wrap[hidden] { display: none; }
  .modal-input { width: 100%; min-height: 40px; padding: 9px 11px; color: var(--ink); background: rgba(4, 16, 23, 0.72); border: 1px solid var(--line); border-radius: 10px; outline: none; }
  .modal-input:focus { border-color: var(--teal); box-shadow: 0 0 0 3px rgba(141, 201, 188, 0.12); }
  .white-balance-modal-panel { margin-top: 20px; padding: 14px; background: rgba(4, 16, 23, 0.5); border: 1px solid var(--line); border-radius: 14px; }
  .white-balance-modal-panel[hidden] { display: none; }
  .white-balance-modal-panel .white-balance-grid { gap: 12px; }
  .white-balance-open { display: flex; align-items: center; justify-content: space-between; gap: 12px; width: 100%; text-align: left; }
  .white-balance-summary { color: var(--teal-deep); font-size: 10px; font-variant-numeric: tabular-nums; white-space: nowrap; }
  .modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 22px; }
  .modal-actions .tool-button { min-width: 78px; }
  .modal-confirm.danger { color: #07131b; background: var(--coral); border-color: var(--coral); }
  .modal-confirm.danger:hover { color: #07131b; background: #e9ad99; border-color: #e9ad99; }

  .brand { display: flex; align-items: center; gap: 14px; }
  .brand-mark {
    display: grid;
    place-items: center;
    width: 52px;
    height: 52px;
    color: #07131b;
    background: var(--teal);
    border-radius: 16px;
    font-size: 20px;
    font-weight: 800;
  }
  .brand-kicker {
    color: var(--teal);
    font-size: 11px;
    font-weight: 750;
    letter-spacing: 0.16em;
  }
  .brand-name { margin-top: 5px; font-size: 22px; font-weight: 750; }

  .workspace { display: grid; grid-template-columns: minmax(0, 1.35fr) minmax(330px, 0.9fr); gap: 18px; }
  .matrix-panel, .control-panel {
    min-width: 0;
    padding: 22px;
    background: var(--panel);
    border: 1px solid var(--line);
    border-radius: 26px;
    box-shadow: 0 18px 50px rgba(1, 8, 12, 0.26);
  }
  .matrix-panel { display: flex; flex-direction: column; }
  .panel-heading { justify-content: space-between; gap: 16px; margin-bottom: 18px; }
  h2 { margin: 0; font-size: 22px; letter-spacing: -0.03em; }
  .panel-heading p { margin: 6px 0 0; color: var(--ink-muted); font-size: 12px; }
  .matrix-meta, .value-display { color: var(--teal-deep); font-size: 12px; font-weight: 750; }

  .matrix-toolbar { flex-wrap: wrap; gap: 8px; margin-bottom: 14px; }
  .tool-button, .mode-button, .palette-remove, .palette-add {
    border: 1px solid var(--line);
    background: rgba(19, 43, 53, 0.78);
    border-radius: 10px;
    cursor: pointer;
    transition: background 160ms ease, border-color 160ms ease, color 160ms ease, transform 160ms ease;
  }
  .tool-button { padding: 9px 13px; color: var(--ink-muted); font-size: 12px; }
  .tool-button.primary { color: #07131b; background: var(--teal-deep); border-color: var(--teal-deep); }
  .tool-button:hover, .mode-button:hover, .palette-remove:hover, .palette-add:hover {
    color: var(--teal-deep);
    border-color: var(--teal);
    transform: translateY(-1px);
  }
  .tool-button.primary:hover, .tool-button:active, .mode-button.active, .palette-remove:active, .palette-add:active {
    color: #07131b;
    background: var(--teal);
    border-color: var(--teal);
  }
  .matrix-paint-picker {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    min-height: 34px;
    margin-left: auto;
    padding: 5px 9px 5px 12px;
    color: var(--ink-muted);
    background: rgba(19, 43, 53, 0.78);
    border: 1px solid var(--line);
    border-radius: 10px;
    font-size: 11px;
  }
  #paintColorPicker { width: 30px; height: 26px; padding: 2px; background: transparent; border: 1px solid var(--line); border-radius: 6px; cursor: pointer; }

  .matrix-viewport {
    padding: 18px 16px;
    overflow-x: auto;
    background: var(--panel-deep);
    border: 1px solid var(--line);
    border-radius: 16px;
    scrollbar-color: var(--teal) transparent;
  }
  .matrix-container { display: flex; flex-direction: column; gap: 3px; width: max-content; min-width: 100%; }
  .pixel-row { display: flex; gap: 3px; }
  .pixel { flex: 0 0 9px; width: 9px; height: 9px; padding: 0; background: #17323d; border: 1px solid rgba(169, 203, 195, 0.12); border-radius: 3px; cursor: crosshair; }
  .pixel:hover { transform: scale(1.45); border-color: var(--teal-deep); }
  .matrix-footnote { display: flex; justify-content: flex-end; margin-top: 13px; color: var(--ink-muted); font-size: 11px; }
  .shape-panel { display: flex; flex: 1; min-height: 0; flex-direction: column; margin-top: 18px; padding-top: 18px; border-top: 1px solid var(--line); }
  .shape-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 10px; }
  .shape-heading h3 { margin: 0; font-size: 14px; }
  .shape-heading p { margin: 4px 0 0; color: var(--ink-muted); font-size: 11px; }
  .shape-actions { display: flex; gap: 8px; align-items: center; }
  #shapeName { width: 130px; min-height: 32px; padding: 6px 9px; color: var(--ink); background: rgba(19, 43, 53, 0.78); border: 1px solid var(--line); border-radius: 8px; font-size: 11px; }
  #saveShape { min-height: 32px; padding: 6px 10px; }
  .shape-list { display: grid; flex: 1; min-height: 0; grid-template-columns: repeat(3, minmax(0, 1fr)); align-content: start; gap: 8px; overflow-y: scroll; padding: 2px 4px 4px 0; scrollbar-color: var(--teal) transparent; }
  .shape-card { display: grid; gap: 7px; padding: 9px; background: rgba(19, 43, 53, 0.62); border: 1px solid var(--line); border-radius: 12px; }
  .shape-card-body { display: grid; gap: 5px; align-content: start; }
  .shape-card-body strong { color: var(--ink); font-size: 11px; line-height: 1.2; }
  .shape-kind { color: var(--teal-deep); font-size: 9px; }
  .shape-card-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
  .shape-card-name { overflow: hidden; color: var(--ink); font-size: 11px; font-weight: 700; text-overflow: ellipsis; white-space: nowrap; }
  .shape-card-kind { color: var(--teal-deep); font-size: 9px; }
  .shape-preview { display: grid; grid-template-columns: repeat(24, minmax(0, 1fr)); grid-template-rows: repeat(6, minmax(0, 1fr)); aspect-ratio: 4 / 1; gap: 2px; padding: 6px; background: var(--panel-deep); border-radius: 8px; }
  .shape-preview-cell { width: 100%; height: 100%; min-width: 0; min-height: 0; background: #17323d; border-radius: 2px; }
  .shape-preview-cell.lit { background: var(--teal); }
  .shape-card-actions { display: flex; flex-wrap: wrap; gap: 5px; }
  .shape-card-actions button { min-height: 25px; padding: 4px 7px; color: var(--ink-muted); background: transparent; border: 1px solid var(--line); border-radius: 7px; cursor: pointer; font-size: 10px; }
  .shape-card-actions button:hover, .shape-card-actions button:active { color: #07131b; background: var(--teal); border-color: var(--teal); }

  .control-section + .control-section { margin-top: 22px; padding-top: 20px; border-top: 1px solid var(--line); }
  .control-label { justify-content: space-between; gap: 12px; margin-bottom: 10px; font-size: 12px; font-weight: 700; }
  .white-balance-grid { display: grid; gap: 8px; }
  .white-balance-row { display: grid; grid-template-columns: 40px minmax(0, 1fr) 30px; gap: 8px; align-items: center; color: var(--ink-muted); font-size: 11px; }
  .white-balance-row output { color: var(--teal-deep); text-align: right; font-variant-numeric: tabular-nums; }
  .white-balance-row input[type="range"] { margin: 0; }
  .white-balance-reset { width: 100%; margin-top: 10px; padding: 7px 9px; color: var(--ink-muted); font-size: 11px; }
  .mode-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
  .mode-button { min-height: 40px; padding: 8px 10px; color: var(--ink-muted); font-size: 12px; text-align: left; }
  .media-color-status { display: flex; align-items: center; gap: 10px; margin-top: 12px; padding: 10px; border: 1px solid var(--line); border-radius: 10px; background: var(--panel-deep); }
  .media-color-status[hidden] { display: none; }
  .media-color-swatch { width: 28px; height: 28px; flex: 0 0 28px; border-radius: 8px; border: 1px solid var(--line); background: var(--teal); }
  .media-color-copy { display: grid; min-width: 0; gap: 4px; }
  .media-color-label { color: var(--ink); font-size: 11px; }
  .media-color-detail { color: var(--ink-muted); font-size: 10px; overflow-wrap: anywhere; }
  .palette-list { display: grid; height: 184px; gap: 8px; align-content: start; overflow-y: scroll; padding: 8px 6px 8px 8px; border: 1px solid var(--line); border-radius: 12px; scrollbar-color: var(--teal) transparent; }
  .palette-row { display: grid; grid-template-columns: minmax(0, 1fr); gap: 8px; align-items: center; }
  .palette-row.removable { grid-template-columns: minmax(0, 1fr) auto; }
  .palette-color { display: block; min-width: 0; width: 100%; height: 38px; padding: 4px; background: rgba(19, 43, 53, 0.78); border: 1px solid var(--line); border-radius: 10px; cursor: pointer; }
  .palette-remove { width: 34px; height: 34px; color: var(--ink-muted); font-size: 11px; }
  .palette-add { width: 100%; margin-top: 9px; padding: 8px; color: var(--ink-muted); font-size: 11px; }
  input[type="range"] { width: 100%; height: 4px; margin: 7px 0 2px; accent-color: var(--teal); cursor: pointer; }

  @media (max-width: 900px) {
    body { min-width: 0; }
    .app-shell { width: min(100% - 26px, 700px); padding-top: 18px; }
    .workspace { grid-template-columns: 1fr; }
    .connection-status { min-width: 0; }
    .shape-list { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  }
  @media (max-width: 600px) {
    .topbar { align-items: flex-start; flex-direction: column; }
    .topbar-actions { width: 100%; align-items: stretch; flex-direction: column; }
    .connection-status { width: 100%; }
    .device-actions { width: 100%; }
    .device-actions .tool-button, .maintenance-button { flex: 1; }
    .maintenance-button { width: 100%; }
    .shape-heading { align-items: flex-start; flex-direction: column; }
    .shape-actions { width: 100%; }
    #shapeName { flex: 1; width: auto; }
    .shape-list { grid-template-columns: 1fr; }
  }
</style>`;

window.htmlBodyContent = `
<main class="app-shell">
  <header class="topbar">
    <div class="brand">
      <div class="brand-mark">LD</div>
      <div><div class="brand-kicker">AETHERIA DESKTOP/CLOUD LED</div><div class="brand-name">WS2812 控制台</div></div>
    </div>
    <div class="topbar-actions">
      <div class="connection-status" id="connectionStatus" data-state="connecting" aria-live="polite">
        <span class="status-dot" aria-hidden="true"></span>
        <span class="status-copy"><span class="status-state" id="connectionState">连接中</span><span class="status-age" id="heartbeatAge">尚未收到心跳</span></span>
        <span class="status-message" id="statusMessage">正在连接设备</span>
      </div>
      <div class="device-actions">
        <button class="tool-button" id="restartButton" type="button">重启设备</button>
        <button class="tool-button" id="resetStateButton" type="button">重置设备</button>
        <button class="tool-button maintenance-button" id="maintenanceButton" type="button">进入维护模式</button>
      </div>
    </div>
  </header>

  <section class="workspace">
    <section class="matrix-panel">
      <div class="panel-heading"><div><h2>点阵编辑区</h2><p>点击或拖动，为每一颗灯选择颜色</p></div><div class="matrix-meta">MATRIX / 0864 DOTS</div></div>
      <div class="matrix-toolbar">
        <button class="tool-button" id="clearMatrix" type="button">清空画布</button>
        <button class="tool-button" id="invertMatrix" type="button">反转颜色</button>
        <button class="tool-button primary" id="sendMatrix" type="button">发送矩阵</button>
        <label class="matrix-paint-picker" title="仅改变矩阵画笔颜色"><span>画笔颜色</span><input id="paintColorPicker" type="color" value="#8dc9bc" aria-label="矩阵画笔颜色" /></label>
      </div>
      <div class="matrix-viewport"><div class="matrix-container" id="matrixContainer"></div></div>
      <div class="matrix-footnote"><span id="matrixState">画布就绪</span></div>
      <section class="shape-panel" aria-labelledby="shapePanelTitle">
        <div class="shape-heading"><div><h3 id="shapePanelTitle">矩阵形状</h3><p>预设不可修改；自定义形状可保存和管理</p></div><div class="shape-actions"><input id="shapeName" type="text" maxlength="40" placeholder="形状名称" aria-label="形状名称" /><button class="tool-button" id="saveShape" type="button">保存当前矩阵</button></div></div>
        <div class="shape-list" id="shapeList"></div>
      </section>
    </section>

    <aside class="control-panel">
      <div class="panel-heading"><div><h2>光线参数</h2><p>调整当前效果的基准状态</p></div></div>
      <div class="control-section">
        <div class="control-label"><span>快捷颜色</span><span class="value-display">渐变 / 单色</span></div>
        <div class="palette-list" id="colorList"><div class="palette-row"><input class="palette-color" type="color" value="#d88773" aria-label="默认快捷颜色" /></div></div>
        <button class="palette-add" id="addColor" type="button">＋ 添加颜色</button>
      </div>
      <div class="control-section">
        <div class="control-label"><span>白平衡</span><span class="value-display">输出校正</span></div>
        <button class="tool-button white-balance-open" id="whiteBalanceButton" type="button"><span>调整白平衡</span><span class="white-balance-summary" id="whiteBalanceSummary">R 255 · G 255 · B 255</span></button>
      </div>
      <div class="control-section"><div class="control-label"><span>亮度</span><span class="value-display" id="brightValue">72%</span></div><input id="brightness" type="range" min="0" max="100" value="72" /></div>
      <div class="control-section"><div class="control-label"><span>节奏</span><span class="value-display" id="speedValue">50</span></div><input id="speed" type="range" min="10" max="200" value="50" /></div>
      <div class="control-section"><div class="control-label"><span>快捷效果</span><span class="value-display">4 effects</span></div><div class="mode-grid"><button class="mode-btn mode-button active" type="button">静态常亮</button><button class="mode-btn mode-button" type="button">呼吸渐变</button><button class="mode-btn mode-button" type="button">流光溢彩</button><button class="mode-btn mode-button" type="button">媒体封面</button></div>
        <div class="media-color-status" id="mediaColorStatus" aria-live="polite" hidden><span class="media-color-swatch" id="mediaColorSwatch" aria-hidden="true"></span><span class="media-color-copy"><span class="media-color-label" id="mediaColorLabel">使用默认快捷颜色</span><span class="media-color-detail" id="mediaColorDetail">暂无媒体播放 · 平滑回退</span></span></div>
      </div>
    </aside>
  </section>

  <div class="modal-layer" id="appModal" hidden>
    <div class="modal-backdrop" data-modal-backdrop></div>
    <section class="modal-dialog" data-variant="neutral" role="dialog" aria-modal="true" aria-labelledby="modalTitle" aria-describedby="modalMessage">
      <div class="modal-eyebrow" id="modalEyebrow">AETHERIA DESKTOP/CLOUD LED</div>
      <h2 class="modal-title" id="modalTitle">确认操作</h2>
      <p class="modal-message" id="modalMessage"></p>
      <label class="modal-input-wrap" id="modalInputWrap" hidden>
        <span id="modalInputLabel">名称</span>
        <input class="modal-input" id="modalInput" type="text" autocomplete="off" />
      </label>
      <div class="white-balance-modal-panel" id="whiteBalanceModalPanel" hidden>
        <div class="white-balance-grid" aria-label="白平衡通道校正">
          <label class="white-balance-row"><span>红 R</span><input id="whiteBalanceRed" data-white-balance type="range" min="0" max="255" value="255" /><output id="whiteBalanceRedValue">255</output></label>
          <label class="white-balance-row"><span>绿 G</span><input id="whiteBalanceGreen" data-white-balance type="range" min="0" max="255" value="255" /><output id="whiteBalanceGreenValue">255</output></label>
          <label class="white-balance-row"><span>蓝 B</span><input id="whiteBalanceBlue" data-white-balance type="range" min="0" max="255" value="255" /><output id="whiteBalanceBlueValue">255</output></label>
        </div>
        <button class="tool-button white-balance-reset" id="resetWhiteBalance" type="button">恢复默认白平衡</button>
      </div>
      <div class="modal-actions">
        <button class="tool-button modal-cancel" id="modalCancelButton" type="button">取消</button>
        <button class="tool-button primary modal-confirm" id="modalConfirmButton" type="button">确认</button>
      </div>
    </section>
  </div>

</main>`;
