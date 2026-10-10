// Execute the production UI logic with a small DOM double and no ESP32 writes.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function element(value = "") {
    const classes = new Set();
    return {
        value, textContent: "", children: [], style: {}, dataset: {}, hidden: false,
        appendChild(child) { this.children.push(child); },
        setAttribute() {},
        set innerHTML(value) { this.children = []; },
        classList: {
            contains: name => classes.has(name),
            toggle(name, enabled) { if (enabled) classes.add(name); else classes.delete(name); },
        },
    };
}

const ids = Object.fromEntries([
    "colorList", "paintColorPicker", "brightness", "brightValue", "speed", "speedValue",
    "whiteBalanceRed", "whiteBalanceGreen", "whiteBalanceBlue",
    "whiteBalanceRedValue", "whiteBalanceGreenValue", "whiteBalanceBlueValue",
    "mediaColorStatus", "mediaColorLabel", "mediaColorDetail", "mediaColorSwatch", "matrixState",
].map(id => [id, element()]));
const buttons = ["静态常亮", "呼吸渐变", "流光溢彩", "媒体封面"].map(text => {
    const button = element();
    button.textContent = text;
    return button;
});
const calls = [];
let healthTick;
let recoveredHealth = true;
const matrix = Array.from({ length: 6 }, () => Array(144).fill("#000000"));
const local = {
    version: 1, mode: "媒体封面", source: "quick", colors: ["#112233", "#445566"],
    paintColor: "#aabbcc", brightness: 80, speed: 50, whiteBalance: [255, 190, 110],
    matrix144x6: matrix,
};
const context = vm.createContext({
    document: {
        readyState: "loading",
        getElementById: id => ids[id] || null,
        createElement: () => element(),
        querySelector: () => buttons.find(button => button.classList.contains("active")),
        querySelectorAll(selector) {
            if (selector === "#colorList .palette-color") return ids.colorList.children.map(row => row.children[0]);
            if (selector === ".mode-button, .mode-btn") return buttons;
            return [];
        },
    },
    window: {
        addEventListener() {}, setTimeout: () => 1, clearTimeout() {},
        setInterval(handler, delay) { if (delay === 3000) healthTick = handler; return delay; },
        clearInterval() {},
        pywebview: { api: {
            load_state: async () => ({ ok: true, state: local }),
            save_state: async state => { calls.push(["save", state]); return { ok: true }; },
            sync: async () => { calls.push(["sync"]); return ({ ok: true, connected: true, state: {
                mode: "静态常亮", source: "quick", colors: ["#dc2846"],
                brightness: 72, whiteBalance: [255, 180, 90],
            } }); },
            health: async () => { calls.push(["health"]); return { ok: true, connected: true, recovered: recoveredHealth }; },
            apply: async state => {
                calls.push(["apply", state]);
                return { ok: true, connected: true, media: { active: true, source: "default", playing: false } };
            },
            media_status: async () => ({ ok: true, connected: true, media: {
                active: true, source: "cover", playing: true, color: "#dc2846", title: "Track", artist: "Artist",
            } }),
            send_shape: async () => ({ ok: true, connected: true }),
        } },
    },
});
const script = fs.readFileSync(path.join(__dirname, "../client/webui/scripts/index.js"), "utf8");
vm.runInContext(script, context);
const run = source => vm.runInContext(source, context);
const plain = value => JSON.parse(JSON.stringify(value));

async function main() {
    await run("restoreLocalState()");
    const restored = plain(run("currentSettings()"));
    assert.equal(restored.version, 1); // Missing version would make save_state reject the state.
    assert.equal(restored.mode, "媒体封面");
    assert.deepEqual(restored.colors, ["#112233", "#445566"]);
    assert.equal(ids.mediaColorStatus.hidden, false);

    await run("syncBoardState(currentSettings())");
    const applied = plain(calls.find(call => call[0] === "apply")[1]);
    assert.equal(applied.mode, "媒体封面");
    assert.deepEqual(applied.colors, ["#112233", "#445566"]); // Not the board's last artwork color.
    assert.equal(applied.brightness, 72);
    assert.deepEqual(applied.whiteBalance, [255, 180, 90]);
    assert.equal(applied.paintColor, "#aabbcc");

    // Activating a client worker is not itself a device heartbeat / ACK.
    run("lastHeartbeatAt = 123");
    await run("resumeMediaEffect()");
    assert.equal(run("lastHeartbeatAt"), 123);

    await run("persistState()");
    assert.equal(calls.find(call => call[0] === "save")[1].mode, "媒体封面");

    await run("refreshMediaStatus()");
    assert.equal(ids.mediaColorSwatch.style.backgroundColor, "#dc2846");
    assert.equal(ids.mediaColorDetail.textContent, "Track · Artist");
    assert.deepEqual(plain(run("getPaletteColors()")), ["#112233", "#445566"]);

    const before = calls.filter(call => call[0] === "apply").length;
    run("maintenanceMode = true");
    await run("resumeMediaEffect()");
    await run("applyEffectSettings(currentSettings())"); // Palette edits and mode-button activation.
    assert.equal(calls.filter(call => call[0] === "apply").length, before);
    run("maintenanceMode = false");

    await run('sendShape("preset:horizontal")');
    assert.equal(run("currentSettings().mode"), "自定义矩阵");
    assert.equal(ids.mediaColorStatus.hidden, true);
    await run("resumeMediaEffect()");
    assert.equal(calls.filter(call => call[0] === "apply").length, before);

    await run("restoreLocalState()");
    run("mediaRunning = true; startHealthMonitor()");
    await new Promise(resolve => setImmediate(resolve));
    calls.length = 0;
    await healthTick();
    assert.deepEqual(calls.map(call => call[0]), ["health", "sync", "apply"]);
    assert.equal(calls[2][1].brightness, 72);
    assert.deepEqual(plain(calls[2][1].colors), ["#112233", "#445566"]);
    // A failed sync leaves following suspended; healthy later ticks must retry it.
    run('renderMediaStatus({ active: true, suspended: true, source: "default" })');
    assert.equal(run("mediaRunning"), false);
    recoveredHealth = false;
    calls.length = 0;
    await healthTick();
    assert.deepEqual(calls.map(call => call[0]), ["health", "sync", "apply"]);
    console.log("Media UI behavior checks passed: restore, sync, persistence, palette, maintenance, matrix send, recovered health");
}
main().catch(error => { console.error(error); process.exitCode = 1; });
