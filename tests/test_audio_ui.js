const fs = require("fs");
const path = require("path");

const root = path.resolve(__dirname, "..");
const source = fs.readFileSync(path.join(root, "client", "webui", "scripts", "index.js"), "utf8");

if (!source.includes('bridgeApiCall("audio_status")')) throw new Error("audio status bridge call missing");
if (!source.includes('document.getElementById("audioBandLow")')) throw new Error("low band meter missing");
if (!source.includes('document.getElementById("audioBandHigh")')) throw new Error("high band meter missing");
if (!source.includes("stopAudioStatusMonitor()")) throw new Error("audio status cleanup missing");

console.log("audio UI source checks passed");
