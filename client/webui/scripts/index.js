const COLUMNS = 144;
const ROWS = 6;
const BLACK = "#000000";
let matrixData = [];
let isDrawing = false;
let lastHeartbeatAt = null;
let healthTimer = null;
let heartbeatAgeTimer = null;
let currentShapes = [];
let loadedShapeId = null;
let currentMode = "静态常亮";
let reconnecting = false;
let healthCheckInFlight = false;
let maintenanceMode = false;
let persistTimer = null;
let persistInFlight = null;
let whiteBalanceTimer = null;
let activeModalResolve = null;
let activeModalMode = "notice";
let modalPreviousFocus = null;

function renderPage() {
    document.querySelector("head").innerHTML = window.htmlHeadContent;
    document.body.innerHTML = window.htmlBodyContent;
}

function closeModal(result = null) {
    const modal = document.getElementById("appModal");
    if (!modal || !activeModalResolve) return;

    const resolve = activeModalResolve;
    activeModalResolve = null;
    modal.hidden = true;
    modal.removeAttribute("data-variant");
    document.body.classList.remove("modal-open");
    if (modalPreviousFocus && typeof modalPreviousFocus.focus === "function") {
        modalPreviousFocus.focus();
    }
    modalPreviousFocus = null;
    resolve(result);
}

function openModal({
    title,
    message = "",
    mode = "confirm",
    variant = "neutral",
    confirmLabel = "确认",
    cancelLabel = "取消",
    inputLabel = "名称",
    inputValue = "",
    inputPlaceholder = "",
}) {
    const modal = document.getElementById("appModal");
    if (!modal) return Promise.resolve(mode === "notice" ? true : mode === "confirm" ? false : null);
    if (activeModalResolve) closeModal(null);

    const titleElement = document.getElementById("modalTitle");
    const messageElement = document.getElementById("modalMessage");
    const inputWrap = document.getElementById("modalInputWrap");
    const inputLabelElement = document.getElementById("modalInputLabel");
    const input = document.getElementById("modalInput");
    const cancelButton = document.getElementById("modalCancelButton");
    const confirmButton = document.getElementById("modalConfirmButton");

    activeModalMode = mode;
    modalPreviousFocus = document.activeElement;
    modal.dataset.variant = variant;
    titleElement.textContent = title;
    messageElement.textContent = message;
    inputWrap.hidden = mode !== "prompt";
    inputLabelElement.textContent = inputLabel;
    input.value = inputValue;
    input.placeholder = inputPlaceholder;
    cancelButton.textContent = cancelLabel;
    cancelButton.hidden = mode === "notice";
    confirmButton.textContent = confirmLabel;
    modal.hidden = false;
    document.body.classList.add("modal-open");

    return new Promise(resolve => {
        activeModalResolve = resolve;
        window.requestAnimationFrame(() => {
            if (mode === "prompt") input.focus();
            else confirmButton.focus();
        });
    });
}

function showNotice(title, message, options = {}) {
    return openModal({ ...options, title, message, mode: "notice" });
}

function showConfirm(title, message, options = {}) {
    return openModal({
        ...options,
        title,
        message,
        mode: "confirm",
        variant: options.variant || "danger",
    });
}

function showPrompt(title, message, inputValue = "", options = {}) {
    return openModal({
        ...options,
        title,
        message,
        inputValue,
        mode: "prompt",
    });
}

function modalCancelResult() {
    return activeModalMode === "notice" ? true : activeModalMode === "confirm" ? false : null;
}

function handleModalKeydown(event) {
    const modal = document.getElementById("appModal");
    if (!modal || modal.hidden || !activeModalResolve) return;
    if (event.key === "Escape") {
        event.preventDefault();
        closeModal(modalCancelResult());
    } else if (event.key === "Enter" && activeModalMode === "prompt" && document.activeElement === document.getElementById("modalInput")) {
        event.preventDefault();
        closeModal(document.getElementById("modalInput").value);
    }
}

function bindModalEvents() {
    const modal = document.getElementById("appModal");
    const cancelButton = document.getElementById("modalCancelButton");
    const confirmButton = document.getElementById("modalConfirmButton");
    const backdrop = modal?.querySelector("[data-modal-backdrop]");
    if (!modal || !cancelButton || !confirmButton) return;

    cancelButton.addEventListener("click", () => closeModal(modalCancelResult()));
    confirmButton.addEventListener("click", () => {
        const input = document.getElementById("modalInput");
        closeModal(activeModalMode === "prompt" ? input.value : true);
    });
    backdrop?.addEventListener("click", () => {
        if (activeModalMode === "notice") closeModal(true);
    });
    document.addEventListener("keydown", handleModalKeydown);
}

function formatHeartbeatAge() {
    if (!lastHeartbeatAt) return "尚未收到心跳";
    const seconds = Math.max(0, Math.floor((Date.now() - lastHeartbeatAt) / 1000));
    return seconds === 0 ? "刚刚收到心跳" : `心跳 ${seconds} 秒前`;
}

function renderConnectionStatus(state, message = "") {
    const root = document.getElementById("connectionStatus");
    const stateElement = document.getElementById("connectionState");
    const ageElement = document.getElementById("heartbeatAge");
    const messageElement = document.getElementById("statusMessage");
    if (!root) return;

    root.dataset.state = state;
    const stateLabel = {
        connecting: "连接中",
        online: "在线",
        offline: "离线",
        error: "错误",
    }[state] || state;
    if (stateElement) {
        stateElement.textContent = stateLabel;
    }
    if (ageElement) ageElement.textContent = formatHeartbeatAge();
    if (messageElement) messageElement.textContent = message;
}

function updateHeartbeatAge() {
    const ageElement = document.getElementById("heartbeatAge");
    if (ageElement) ageElement.textContent = formatHeartbeatAge();
}

function setStatus(message, online = null) {
    if (online === true) {
        lastHeartbeatAt = Date.now();
        renderConnectionStatus("online", message);
        return;
    }
    if (online === false) {
        renderConnectionStatus("offline", message);
        return;
    }

    const root = document.getElementById("connectionStatus");
    renderConnectionStatus(root?.dataset.state || "connecting", message);
}

function setMatrixState(message) {
    const state = document.getElementById("matrixState");
    if (state) state.textContent = message;
}

function bridgeApiCall(method, ...args) {
    if (!window.pywebview || !window.pywebview.api) {
        return new Promise(resolve => {
            window.setTimeout(() => resolve(bridgeApiCall(method, ...args)), 100);
        });
    }
    const handler = window.pywebview.api[method];
    if (typeof handler !== "function") {
        return Promise.resolve({ ok: false, error: `桥接方法不存在: ${method}` });
    }
    return Promise.resolve(handler(...args)).catch(error => ({
        ok: false,
        error: error.message || "请求失败",
    }));
}

function bridgeCall(method, ...args) {
    if (!window.pywebview || !window.pywebview.api) {
        setStatus("桥接尚未就绪", false);
        return new Promise(resolve => {
            window.setTimeout(() => resolve(bridgeCall(method, ...args)), 100);
        });
    }
    return bridgeApiCall(method, ...args).then(result => {
        const connected = result.connected ?? (method === "health" && result.ok === false ? false : null);
        const defaultMessage = connected === true ? "设备已响应" : "设备未连接";
        const message = result.error || (method === "health" && connected !== true ? "心跳未收到" : defaultMessage);
        setStatus(message, connected);
        return result;
    });
}

function getPaletteColors() {
    return Array.from(document.querySelectorAll("#colorList .palette-color"), input => input.value);
}

const WHITE_BALANCE_CHANNELS = ["Red", "Green", "Blue"];

function getWhiteBalanceValues() {
    return WHITE_BALANCE_CHANNELS.map(channel => {
        const input = document.getElementById(`whiteBalance${channel}`);
        const value = Number(input?.value);
        return Number.isFinite(value) ? Math.max(0, Math.min(255, Math.round(value))) : 255;
    });
}

function applyWhiteBalanceControls(values) {
    if (!Array.isArray(values) || values.length !== 3) return;
    WHITE_BALANCE_CHANNELS.forEach((channel, index) => {
        const value = Math.max(0, Math.min(255, Math.round(Number(values[index]))));
        const input = document.getElementById(`whiteBalance${channel}`);
        const output = document.getElementById(`whiteBalance${channel}Value`);
        if (input) input.value = String(value);
        if (output) output.textContent = String(value);
    });
}

function addPaletteColor() {
    const list = document.getElementById("colorList");
    const row = document.createElement("div");
    row.className = "palette-row removable";

    const input = document.createElement("input");
    input.type = "color";
    input.className = "palette-color";
    input.value = "#00ffff";
    input.setAttribute("aria-label", `快捷颜色 ${list.children.length + 1}`);
    row.appendChild(input);

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "palette-remove";
    remove.dataset.action = "removeColor";
    remove.textContent = "×";
    remove.setAttribute("aria-label", "删除快捷颜色");
    row.appendChild(remove);
    list.appendChild(row);
}

function renderPaletteColors(colors) {
    const list = document.getElementById("colorList");
    if (!list) return;
    list.innerHTML = "";
    colors.forEach((color, index) => {
        const row = document.createElement("div");
        row.className = index > 0 ? "palette-row removable" : "palette-row";

        const input = document.createElement("input");
        input.type = "color";
        input.className = "palette-color";
        input.value = color;
        input.setAttribute("aria-label", index === 0 ? "默认快捷颜色" : `快捷颜色 ${index + 1}`);
        row.appendChild(input);

        if (index > 0) {
            const remove = document.createElement("button");
            remove.type = "button";
            remove.className = "palette-remove";
            remove.dataset.action = "removeColor";
            remove.textContent = "×";
            remove.setAttribute("aria-label", "删除快捷颜色");
            row.appendChild(remove);
        }
        list.appendChild(row);
    });
}

function bindColorList(onChange) {
    const list = document.getElementById("colorList");
    document.getElementById("addColor").addEventListener("click", () => {
        addPaletteColor();
        onChange();
    });
    list.addEventListener("input", event => {
        if (event.target.classList.contains("palette-color")) onChange();
    });
    list.addEventListener("click", event => {
        const remove = event.target.closest("[data-action=\"removeColor\"]");
        if (!remove) return;
        remove.closest(".palette-row").remove();
        onChange();
    });
}

function currentSettings() {
    const colors = getPaletteColors();
    const activeMode = document.querySelector(".mode-button.active, .mode-btn.active")?.textContent.trim();
    const mode = currentMode === "自定义矩阵" ? currentMode : (activeMode || currentMode);
    const source = mode === "自定义矩阵" ? "matrix" : "quick";
    return {
        color: colors[0] || "#ff0080",
        colors,
        source,
        paintColor: document.getElementById("paintColorPicker")?.value || "#8dc9bc",
        brightness: Number(document.getElementById("brightness").value),
        speed: Number(document.getElementById("speed").value),
        whiteBalance: getWhiteBalanceValues(),
        mode,
        matrix144x6: cloneMatrix(matrixData),
    };
}

function updateRhythmControl() {
    const speed = document.getElementById("speed");
    const value = document.getElementById("speedValue");
    if (!speed) return;

    if (value) value.textContent = speed.value;
}

function applyUiState(state) {
    if (!state || typeof state !== "object") return false;
    const colors = Array.isArray(state.colors) && state.colors.length
        ? state.colors
        : (getPaletteColors().length ? getPaletteColors() : ["#d88773"]);
    renderPaletteColors(colors);

    const paintColor = document.getElementById("paintColorPicker");
    if (paintColor && typeof state.paintColor === "string") paintColor.value = state.paintColor;

    const brightness = document.getElementById("brightness");
    if (brightness && Number.isFinite(Number(state.brightness))) {
        brightness.value = String(state.brightness);
        document.getElementById("brightValue").textContent = `${brightness.value}%`;
    }
    const speed = document.getElementById("speed");
    if (speed && Number.isFinite(Number(state.speed))) {
        speed.value = String(state.speed);
        document.getElementById("speedValue").textContent = speed.value;
    }
    applyWhiteBalanceControls(state.whiteBalance);
    updateRhythmControl(state.mode);

    currentMode = state.mode === "自定义矩阵" || state.source === "matrix"
        ? "自定义矩阵"
        : (state.mode || "静态常亮");
    const modeButtons = document.querySelectorAll(".mode-button, .mode-btn");
    modeButtons.forEach(button => {
        button.classList.toggle(
            "active",
            currentMode !== "自定义矩阵" && button.textContent.trim() === currentMode,
        );
    });
    if (Array.isArray(state.matrix144x6) && state.matrix144x6.length === ROWS) {
        matrixData = cloneMatrix(state.matrix144x6);
        renderMatrix();
    }
    setMatrixState(currentMode === "自定义矩阵" ? "已恢复 · 自定义矩阵" : "已恢复 · " + currentMode);
    return true;
}

function applySyncedState(state, fallback) {
    const base = fallback || currentSettings();
    const merged = { ...base, ...state };
    if (fallback?.paintColor) merged.paintColor = fallback.paintColor;
    if ((state.mode === "流光溢彩" || state.mode === "彩虹跑马") && (!Array.isArray(state.colors) || !state.colors.length)) {
        const fallbackColors = Array.isArray(fallback?.colors) && fallback.colors.length
            ? fallback.colors
            : ["#d88773"];
        merged.colors = fallbackColors;
    }
    if (!Array.isArray(merged.matrix144x6) || merged.matrix144x6.length !== ROWS) {
        merged.matrix144x6 = base.matrix144x6;
    }
    applyUiState(merged);
    return merged;
}

async function syncBoardState(fallback = null) {
    const synced = await bridgeCall("sync");
    if (synced.ok) {
        applySyncedState(synced.state, fallback || currentSettings());
    }
    return synced;
}

async function restoreLocalState() {
    const result = await bridgeApiCall("load_state");
    if (!result.ok || !result.state) return null;
    applyUiState(result.state);
    return result.state;
}

function persistState() {
    if (persistInFlight) return persistInFlight;
    persistInFlight = bridgeApiCall("save_state", currentSettings())
        .catch(() => ({ ok: false }))
        .finally(() => { persistInFlight = null; });
    return persistInFlight;
}

function schedulePersist() {
    if (persistTimer) window.clearTimeout(persistTimer);
    persistTimer = window.setTimeout(() => {
        persistTimer = null;
        persistState();
    }, 250);
}

function flushPersistedState() {
    if (persistTimer) {
        window.clearTimeout(persistTimer);
        persistTimer = null;
    }
    return persistState();
}

function paintPixel(pixel) {
    const row = Number(pixel.dataset.r);
    const column = Number(pixel.dataset.c);
    const color = document.getElementById("paintColorPicker").value;
    pixel.style.backgroundColor = color;
    matrixData[row][column] = color;
    schedulePersist();
}

function renderMatrix() {
    document.querySelectorAll(".pixel").forEach(pixel => {
        const row = Number(pixel.dataset.r);
        const column = Number(pixel.dataset.c);
        const value = matrixData[row]?.[column] || BLACK;
        pixel.style.backgroundColor = value === BLACK ? "#111" : value;
    });
}

function cloneMatrix(matrix) {
    return matrix.map(row => row.slice());
}

function initMatrix() {
    const container = document.getElementById("matrixContainer");
    matrixData = [];
    container.innerHTML = "";

    for (let row = 0; row < ROWS; row++) {
        const rowElement = document.createElement("div");
        rowElement.className = "pixel-row";
        const rowData = [];

        for (let column = 0; column < COLUMNS; column++) {
            const pixel = document.createElement("div");
            pixel.className = "pixel";
            pixel.dataset.r = row;
            pixel.dataset.c = column;
            pixel.style.backgroundColor = "#111";
            rowData.push(BLACK);
            pixel.addEventListener("mousedown", event => {
                event.preventDefault();
                isDrawing = true;
                paintPixel(pixel);
            });
            pixel.addEventListener("mouseover", () => isDrawing && paintPixel(pixel));
            rowElement.appendChild(pixel);
        }
        matrixData.push(rowData);
        container.appendChild(rowElement);
    }
}

function shapeCellIsLit(shape, row, column) {
    const value = shape.matrix?.[row]?.[column];
    return shape.kind === "preset" ? value === 1 : value && value !== BLACK;
}

function renderShapePreview(shape) {
    const preview = document.createElement("div");
    preview.className = "shape-preview";
    for (let row = 0; row < ROWS; row++) {
        for (let sample = 0; sample < 24; sample++) {
            const cell = document.createElement("span");
            const column = Math.min(COLUMNS - 1, Math.floor(sample * COLUMNS / 24));
            cell.className = "shape-preview-cell";
            if (shapeCellIsLit(shape, row, column)) cell.classList.add("lit");
            preview.appendChild(cell);
        }
    }
    return preview;
}

function shapeAction(label, action, shapeId) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "shape-action";
    button.dataset.action = action;
    button.dataset.id = shapeId;
    button.textContent = label;
    return button;
}

function renderShapeList(shapes) {
    const list = document.getElementById("shapeList");
    if (!list) return;
    list.innerHTML = "";

    if (!shapes.length) {
        const empty = document.createElement("p");
        empty.className = "shape-empty";
        empty.textContent = "还没有保存的矩阵形状";
        list.appendChild(empty);
        return;
    }

    shapes.forEach(shape => {
        const card = document.createElement("article");
        card.className = "shape-card";
        card.dataset.kind = shape.kind;
        card.appendChild(renderShapePreview(shape));

        const body = document.createElement("div");
        body.className = "shape-card-body";
        const title = document.createElement("strong");
        title.textContent = shape.name;
        const kind = document.createElement("span");
        kind.className = "shape-kind";
        kind.textContent = shape.kind === "preset" ? "预设" : "我的形状";
        body.append(title, kind);

        const actions = document.createElement("div");
        actions.className = "shape-card-actions";
        actions.append(
            shapeAction("发送", "shape-send", shape.id),
            shapeAction("载入", "shape-load", shape.id),
        );
        if (shape.kind === "user") {
            actions.append(
                shapeAction("更新", "shape-update", shape.id),
                shapeAction("删除", "shape-delete", shape.id),
            );
        }
        body.appendChild(actions);
        card.appendChild(body);
        list.appendChild(card);
    });
}

async function loadShapes() {
    const result = await bridgeApiCall("list_shapes");
    if (!result.ok) {
        setStatus(result.error || "矩阵形状读取失败");
        return result;
    }
    currentShapes = result.shapes || [];
    renderShapeList(currentShapes);
    return result;
}

function shapeMatrix(shape) {
    if (shape.kind !== "preset") return cloneMatrix(shape.matrix);
    const paintColor = document.getElementById("paintColorPicker")?.value || "#8dc9bc";
    return shape.matrix.map(row => row.map(value => value === 1 ? paintColor : BLACK));
}

function selectMatrixSource() {
    currentMode = "自定义矩阵";
}

function loadShape(shapeId) {
    const shape = currentShapes.find(item => item.id === shapeId);
    if (!shape) return;
    matrixData = shapeMatrix(shape);
    renderMatrix();
    loadedShapeId = shape.kind === "user" ? shape.id : null;
    const nameInput = document.getElementById("shapeName");
    if (nameInput) nameInput.value = shape.kind === "user" ? shape.name : "";
    selectMatrixSource();
    setMatrixState(`已载入：${shape.name}`);
    schedulePersist();
}

async function sendShape(shapeId) {
    const brightness = Math.round(Number(document.getElementById("brightness").value) * 255 / 100);
    const paintColor = document.getElementById("paintColorPicker")?.value || "#8dc9bc";
    return bridgeCall("send_shape", shapeId, brightness, paintColor);
}

async function saveCurrentShape() {
    const input = document.getElementById("shapeName");
    let name = input?.value.trim();
    if (!name) {
        const promptedName = await showPrompt(
            "保存矩阵形状",
            "为当前矩阵输入一个名称。",
            "我的形状",
            { inputLabel: "形状名称", confirmLabel: "保存", inputPlaceholder: "例如：晚安灯牌" },
        );
        name = promptedName?.trim();
    }
    if (!name) return { ok: false, error: "形状名称不能为空" };
    const result = await bridgeApiCall("save_shape", name, cloneMatrix(matrixData));
    if (!result.ok) setStatus(result.error || "矩阵保存失败");
    if (result.ok) {
        loadedShapeId = result.shape.id;
        if (input) input.value = result.shape.name;
        await loadShapes();
    }
    return result;
}

async function updateCurrentShape(shapeId = loadedShapeId) {
    if (!shapeId) return { ok: false, error: "请先载入一个自定义形状" };
    const shape = currentShapes.find(item => item.id === shapeId);
    if (!shape || shape.kind !== "user") return { ok: false, error: "预设形状不可修改" };
    const input = document.getElementById("shapeName");
    const name = input?.value.trim() || shape.name;
    const result = await bridgeApiCall("update_shape", shapeId, name, cloneMatrix(matrixData));
    if (!result.ok) setStatus(result.error || "矩阵更新失败");
    if (result.ok) await loadShapes();
    return result;
}

async function deleteShape(shapeId) {
    const shape = currentShapes.find(item => item.id === shapeId);
    if (!shape || shape.kind !== "user") return { ok: false, error: "预设形状不可删除" };
    if (!await showConfirm("删除矩阵形状", `确定删除“${shape.name}”吗？`, { confirmLabel: "删除" })) {
        return { ok: false, cancelled: true };
    }
    const result = await bridgeApiCall("delete_shape", shapeId);
    if (!result.ok) setStatus(result.error || "矩阵删除失败");
    if (result.ok) {
        if (loadedShapeId === shapeId) loadedShapeId = null;
        await loadShapes();
    }
    return result;
}

function bindShapeEvents() {
    document.getElementById("saveShape")?.addEventListener("click", saveCurrentShape);
    document.getElementById("shapeList")?.addEventListener("click", event => {
        const action = event.target.closest("[data-action]");
        if (!action) return;
        const shapeId = action.dataset.id;
        if (action.dataset.action === "shape-send") sendShape(shapeId);
        if (action.dataset.action === "shape-load") loadShape(shapeId);
        if (action.dataset.action === "shape-update") updateCurrentShape(shapeId);
        if (action.dataset.action === "shape-delete") deleteShape(shapeId);
    });
}

function startHealthMonitor() {
    if (healthTimer) window.clearInterval(healthTimer);
    if (heartbeatAgeTimer) window.clearInterval(heartbeatAgeTimer);

    const checkHealth = async () => {
        if (maintenanceMode) return;
        if (healthCheckInFlight) return;
        healthCheckInFlight = true;
        try {
            const result = await bridgeCall("health");
            if (result.ok || reconnecting) return result;

            reconnecting = true;
            renderConnectionStatus("connecting", "正在重新握手");
            const connection = await bridgeCall("connect");
            reconnecting = false;
            if (!connection.ok) {
                setStatus(connection.error || "握手失败", false);
                return connection;
            }
            const synced = await syncBoardState(currentSettings());
            if (!synced.ok) setStatus(synced.error || "设备状态同步失败", true);
            return connection;
        } finally {
            healthCheckInFlight = false;
        }
    };
    checkHealth();
    healthTimer = window.setInterval(checkHealth, 3000);
    heartbeatAgeTimer = window.setInterval(updateHeartbeatAge, 1000);
}

async function enterMaintenanceMode() {
    if (maintenanceMode) return { ok: false, maintenance: true };
    if (!await showConfirm(
        "进入维护 / 上传模式",
        "设备将停止运行并断开客户端连接，确认继续吗？",
        { confirmLabel: "进入维护" },
    )) {
        return { ok: false, cancelled: true };
    }

    const button = document.getElementById("maintenanceButton");
    if (button) {
        button.disabled = true;
        button.textContent = "正在切换…";
    }

    const result = await bridgeCall("enter_maintenance");
    if (!result.ok) {
        if (button) {
            button.disabled = false;
            button.textContent = "进入维护模式";
        }
        return result;
    }

    maintenanceMode = true;
    if (healthTimer) {
        window.clearInterval(healthTimer);
        healthTimer = null;
    }
    if (heartbeatAgeTimer) {
        window.clearInterval(heartbeatAgeTimer);
        heartbeatAgeTimer = null;
    }
    if (button) {
        button.disabled = false;
        button.textContent = "恢复连接";
    }
    renderConnectionStatus("offline", "可使用 Thonny 上传");
    setStatus("已进入维护模式，可使用 Thonny", false);
    return result;
}

async function restoreConnection() {
    if (!maintenanceMode) return { ok: false, connected: true };

    const button = document.getElementById("maintenanceButton");
    if (button) {
        button.disabled = true;
        button.textContent = "正在恢复…";
    }
    renderConnectionStatus("connecting", "正在恢复连接");

    const connection = await bridgeCall("connect");
    if (!connection.ok) {
        if (button) {
            button.disabled = false;
            button.textContent = "恢复连接";
        }
        setStatus(connection.error || "恢复连接失败", false);
        return connection;
    }

    const synced = await syncBoardState(currentSettings());
    if (!synced.ok) {
        if (button) {
            button.disabled = false;
            button.textContent = "恢复连接";
        }
        setStatus(synced.error || "设备状态同步失败", true);
        return { ok: false, connected: true, error: synced.error || "设备状态同步失败" };
    }

    maintenanceMode = false;
    if (button) {
        button.disabled = false;
        button.textContent = "进入维护模式";
    }
    setStatus("设备状态已同步", true);
    startHealthMonitor();
    return { ...connection, synced: true };
}

function setDeviceActionsDisabled(disabled) {
    document.querySelectorAll("#restartButton, #resetStateButton, #maintenanceButton").forEach(button => {
        button.disabled = disabled;
    });
}

function stopHealthMonitor() {
    if (healthTimer) {
        window.clearInterval(healthTimer);
        healthTimer = null;
    }
    if (heartbeatAgeTimer) {
        window.clearInterval(heartbeatAgeTimer);
        heartbeatAgeTimer = null;
    }
}

async function sendDeviceLifecycleCommand(method, buttonId, pendingLabel, successMessage) {
    if (maintenanceMode) {
        setStatus("维护模式下请先恢复连接", false);
        return { ok: false, maintenance: true };
    }

    const button = document.getElementById(buttonId);
    const label = button?.textContent || "设备操作";
    setDeviceActionsDisabled(true);
    if (button) button.textContent = pendingLabel;

    try {
        const result = await bridgeCall(method);
        if (result.ok) {
            lastHeartbeatAt = null;
            stopHealthMonitor();
            renderConnectionStatus("connecting", successMessage);
            setStatus(successMessage);
            startHealthMonitor();
        }
        return result;
    } finally {
        setDeviceActionsDisabled(false);
        if (button) button.textContent = label;
    }
}

async function restartDevice() {
    if (!await showConfirm("重启设备", "板端保存的状态会保留，确认继续吗？", { confirmLabel: "重启" })) {
        return { ok: false, cancelled: true };
    }
    return sendDeviceLifecycleCommand("restart", "restartButton", "正在重启…", "设备正在重启，等待重新上线");
}

async function resetDeviceState() {
    if (!await showConfirm("重置设备", "板端保存的状态将被删除并重启设备，确认继续吗？", { confirmLabel: "重置" })) {
        return { ok: false, cancelled: true };
    }
    return sendDeviceLifecycleCommand("reset_state", "resetStateButton", "正在重置…", "设备状态已清除，正在重启");
}

function bindEvents() {
    const brightness = document.getElementById("brightness");
    const speed = document.getElementById("speed");
    const whiteBalanceInputs = document.querySelectorAll("[data-white-balance]");
    const paintColorPicker = document.getElementById("paintColorPicker");
    const modeButtons = document.querySelectorAll(".mode-button, .mode-btn");
    document.getElementById("maintenanceButton")?.addEventListener("click", () => {
        void (maintenanceMode ? restoreConnection() : enterMaintenanceMode());
    });
    document.getElementById("restartButton")?.addEventListener("click", () => {
        void restartDevice();
    });
    document.getElementById("resetStateButton")?.addEventListener("click", () => {
        void resetDeviceState();
    });

    renderPaletteColors(getPaletteColors().length ? getPaletteColors() : ["#d88773"]);
    updateRhythmControl();
    bindModalEvents();

    document.addEventListener("mouseup", () => { isDrawing = false; });

    document.getElementById("clearMatrix").addEventListener("click", () => {
        matrixData.forEach(row => row.fill(BLACK));
        renderMatrix();
        setMatrixState("画布已清空");
        schedulePersist();
    });

    document.getElementById("invertMatrix").addEventListener("click", () => {
    matrixData = matrixData.map(row => row.map(value => {
        return value === "#000000" ? paintColorPicker.value : "#000000";
    }));
    renderMatrix();
    setMatrixState("画布颜色已反转");
    schedulePersist();
    });

    document.getElementById("sendMatrix").addEventListener("click", () => {
        currentMode = "自定义矩阵";
        const settings = currentSettings();
        bridgeCall("send_matrix", matrixData, null, Math.round(settings.brightness * 255 / 100))
            .then(result => {
                if (result.ok) setMatrixState("矩阵已发送");
            });
        schedulePersist();
    });

    function applyCurrentSettings() {
        bridgeCall("apply", currentSettings());
        schedulePersist();
    }

    function updateBrightnessParameter() {
        void bridgeCall("set_brightness", Number(brightness.value));
        schedulePersist();
    }

    function updateTimingParameter() {
        const speedValue = Math.max(1, Number(speed.value));
        const timingMs = Math.max(1, Math.round(1000 / speedValue));
        void bridgeCall("set_timing", timingMs);
        schedulePersist();
    }

    function updateWhiteBalanceParameter() {
        const values = getWhiteBalanceValues();
        void bridgeCall("set_white_balance", ...values).then(result => {
            if (result.ok) {
                applyWhiteBalanceControls(result.whiteBalance || values);
                schedulePersist();
            }
        });
    }

    function scheduleWhiteBalanceUpdate() {
        if (whiteBalanceTimer) window.clearTimeout(whiteBalanceTimer);
        whiteBalanceTimer = window.setTimeout(() => {
            whiteBalanceTimer = null;
            updateWhiteBalanceParameter();
        }, 100);
    }

    bindColorList(applyCurrentSettings);
    bindShapeEvents();

    brightness.addEventListener("input", () => {
        document.getElementById("brightValue").textContent = `${brightness.value}%`;
        updateBrightnessParameter();
    });
    speed.addEventListener("input", () => {
        document.getElementById("speedValue").textContent = speed.value;
        updateTimingParameter();
    });
    whiteBalanceInputs.forEach(input => input.addEventListener("input", () => {
        const output = document.getElementById(`${input.id}Value`);
        if (output) output.textContent = input.value;
        scheduleWhiteBalanceUpdate();
    }));
    document.getElementById("resetWhiteBalance")?.addEventListener("click", () => {
        applyWhiteBalanceControls([255, 255, 255]);
        updateWhiteBalanceParameter();
    });
    paintColorPicker.addEventListener("input", schedulePersist);
    modeButtons.forEach(button => button.addEventListener("click", () => {
        modeButtons.forEach(item => item.classList.remove("active"));
        button.classList.add("active");
        currentMode = button.textContent.trim();
        updateRhythmControl(button.textContent.trim());
        applyCurrentSettings();
    }));

    window.addEventListener("beforeunload", () => {
        flushPersistedState();
    });
}

function waitForRuntimeBackground() {
    const url = window.__runtimeBackgroundUrl;
    if (!url) return Promise.resolve();

    return new Promise(resolve => {
        const image = new Image();
        const finish = () => resolve();
        image.onload = finish;
        image.onerror = finish;
        image.src = url;
    });
}

function notifyUiReady() {
    if (!window.pywebview || !window.pywebview.api) {
        window.setTimeout(notifyUiReady, 50);
        return;
    }
    window.pywebview.api.ui_ready().catch(() => {});
}

async function startApplication() {
    renderPage();
    initMatrix();
    bindEvents();
    renderConnectionStatus("connecting", "正在连接设备");
    const localState = await restoreLocalState();
    const connection = await bridgeCall("connect");
    if (connection.ok) {
        const recovered = connection.recovered === true;
        const synced = await syncBoardState(recovered ? (localState || currentSettings()) : currentSettings());
        if (!synced.ok && localState) applyUiState(localState);
    }
    startHealthMonitor();
    await loadShapes();
    await waitForRuntimeBackground();
    if (!connection.ok && !lastHeartbeatAt) setStatus(connection.error || "设备尚未连接", false);
    notifyUiReady();
}

if (document.readyState === "complete") {
    startApplication();
} else {
    window.addEventListener("load", startApplication, { once: true });
}
