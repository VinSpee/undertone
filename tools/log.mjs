// SPDX-License-Identifier: GPL-3.0-only
// node tools/op.mjs log: read the pedal's state over USB MIDI instead of from its screen, with what each field means and a
// verdict. The request is DIAG (docs/EDITOR-PROTOCOL.md), read only; docs/pxedit.js and docs/pxota.js do the talking.
//   log [--follow] [--json] [--wait SEC] [--interval SEC] [--count N] [--scan SEC]
import { spawn, spawnSync } from "node:child_process";
import { existsSync, mkdirSync, statSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { C, Editor } from "../docs/pxedit.js";
import { IS_ALT, IS_OTA, PORT_RE, Updater } from "../docs/pxota.js";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const USAGE = `usage: node tools/op.mjs log [--follow] [--json] [--wait SEC] [--interval SEC] [--count N] [--scan SEC]
  --wait SEC      keep trying for this long until the pedal has finished starting (use it right after a flash)
  --interval SEC  time between two readings (default 2): the counters must rise between them
  --count N       how many readings (default 2; with --follow, no limit)
  --follow        keep reading until stopped
  --json          one JSON object per reading
  --scan SEC      then listen for the advertisement on this Mac: SEC seconds on its service UUID, SEC seconds on everything
Exit: 0 pass or running, 1 fail, 2 bad arguments, 3 undecided (still starting, the scanner could not run, no log channel).`;
const BLE_MIDI = "03B80E5A-EDE8-4B33-A751-6CE34EC4C700";

// firmware/base/diag.h ST_NAME, firmware/base/start.h rst_names (tests/test_log.mjs compares them)
export const BOOT_STAGES = ["?", "INPUTS", "PRESET", "ENGINE INIT", "ENGINE SET", "I2S START", "UI DRAW", "FIRST 6 S", "OK"];
export const RESET_CAUSES = ["POWER-ON", "VDDIO LOW", "WATCHDOG", "VCM", "LONG PRESS", "1.2V", "SOFT"];
const STAGE_OK = BOOT_STAGES.indexOf("OK");
const FAIL_STEPS = ["none", "task_create failed", "btctrler_task_init failed", "the controller task did not answer (btctrler_task_ready)", "ll_hci_adv_enable failed", "still starting after 5 s"];

// docs/BLE-TEST.md, "The advertising line"
const MEANING = {
  i: "baseband event interrupts (IRQ 45): rising means the radio runs",
  e: "HCI packets the controller returned",
  r: "receive interrupts (IRQ 29): above 0 means a scanner's request was heard",
  t: "library software timers that fired: rising means the controller's tick runs",
  s: "slot-timer stand-in calls: above 0 means the link scheduler wants a timer this image lacks",
  vm: "stored radio records: found mask (7 = VM 106, 107, 108), area / 4096, first two bytes of VM 106",
  CON: "baseband control 0x28000", IEN: "baseband interrupt enables 0x28028", IPND: "baseband pending 0x28030", STAT: "baseband busy flags 0x28038",
  IC45: "IRQ 45 configuration: bit 0 enabled, bits 3:1 priority, 0 = off", IC29: "IRQ 29 configuration: 0 = off", BEN: "BLE block enable 0x2FC80: bit 0 set = on",
};

const number = (line, key, radix = 10) => {
  const m = new RegExp(`\\b${key} ?(-?[0-9A-F]+)\\b`).exec(line);
  return m ? parseInt(m[1], radix) : null;
};

// the clock's line, Gamut's and the rate-diag build's (firmware/base/rate.h a_rate_text, docs/RATE48-TEST.md); hz is the rate measured
// over the last 10 s window of TIMER4 (24 MHz), null before the first one ends
const RATE_RE = /^RATE ASK (\d+) SR (\d+) GUARD (\w+) W (\d+) F (\d+) T (\d+) PLL0 (\w{8}) (\w{8}) PLL1 (\w{8}) (\w{8}) HSB (\w{8}) MUX (\w{8}) SYS (\w{8}) DIV (\w{8}) BEFORE (\w{8}) (\w{8}) (\w{8})$/;
export function parseRate(raw) {
  const m = RATE_RE.exec(raw);
  if (!m) return { raw, ok: false };
  const h = (i) => parseInt(m[i], 16), frames = +m[5], ticks = +m[6];
  return { raw, ok: true, ask: +m[1], sr: +m[2], guard: m[3], windows: +m[4], frames, ticks, hz: ticks ? frames * 24e6 / ticks : null,
    pll0: [h(7), h(8)], pll1: [h(9), h(10)], hsb: h(11), mux: h(12), sys: h(13), div: h(14), before: { pll0: h(15), sys: h(16), div: h(17) } };
}
const RATE_BIT25 = 1 << 25, RATE_SYS48 = 1 << 8;

// the status line, exactly as the screen scrolls it
export function parseBle(raw) {
  let m;
  if (raw.startsWith("ADV ")) {
    const f = { state: "advertising", raw };
    for (const k of ["i", "e", "r", "t", "s"]) f[k] = number(raw, k);
    for (const k of ["CON", "IEN", "IPND", "STAT", "IC45", "IC29", "BEN"]) f[k] = number(raw, k, 16);
    if ((m = / V ([0-9A-F]+) ([0-9A-F]+) ([0-9A-F]+)\b/.exec(raw))) f.vm = { found: parseInt(m[1], 16), area: parseInt(m[2], 16), trim: parseInt(m[3], 16) };
    return f;
  }
  if ((m = /^FAILED (\d+) (-?\d+)(?:  step (\S+) stage (\S+))?(?: wait ([0-9A-F]{8}))?/.exec(raw))) {
    return { state: "failed", raw, step: +m[1], code: +m[2], stepName: m[3] || null, stage: m[4] || null, wait: m[5] || null };
  }
  if ((m = /^STARTING (\d+)/.exec(raw))) return { state: "starting", raw, stage: +m[1] };
  return { state: raw.startsWith("OFF") ? "off" : "unknown", raw };
}

export function parseBoot(raw) {
  const rst = number(raw, "RST", 16) ?? 0;
  const stage = number(raw, "STAGE") ?? 0;
  return { raw, clockMs: number(raw, "UP"), safe: number(raw, "SAFE") === 1, stage, stageName: BOOT_STAGES[stage] ?? "?", resetBits: rst,
    resetBy: RESET_CAUSES.filter((_, i) => rst >> i & 1), failedBoots: number(raw, "GUARD") };
}

export function parseLast(raw) {
  if (!raw.startsWith("LAST FAILED")) return { raw, failed: false };
  const stage = number(raw, "STAGE") ?? 0;
  const out = { raw, failed: true, stage, stageName: BOOT_STAGES[stage] ?? "?", blocks: number(raw, "BLOCKS"), load: number(raw, "LOAD"), peak: number(raw, "PEAK"),
    nans: number(raw, "NAN"), cpu1: number(raw, "CPU1"), loops: number(raw, "LOOPS"), crash: null };
  const c = raw.indexOf(" CRASH ");
  if (c >= 0) {
    const t = raw.slice(c);
    out.crash = { vec: number(t, "VEC", 16), pc: number(t, "PC", 16), rets: number(t, "RETS", 16), dbg: number(t, "DBG", 16), emu: number(t, "EMU", 16), clockMs: number(t, "UP") };
  }
  return out;
}

// the second core's fault line (firmware/apps/gamut/ble/ble_diag.h ble_c1_text): "C1 OK", or its last fault's record; null
// when an older image sent no such line
export function parseC1(raw) {
  if (!raw || !raw.startsWith("C1 ")) return null;
  if (raw === "C1 OK") return { raw, faults: 0 };
  const m = /^C1 FAULT (\d+) CORE (\d+) DBG ([0-9A-F]+) PC ([0-9A-F]+) RETS ([0-9A-F]+) SP ([0-9A-F]+) R((?: [0-9A-F]+){16})$/.exec(raw);
  if (!m) return { raw, faults: null };
  return { raw, faults: +m[1], core: +m[2], dbg: parseInt(m[3], 16), pc: parseInt(m[4], 16), rets: parseInt(m[5], 16), sp: parseInt(m[6], 16),
    r: m[7].trim().split(" ").map((v) => parseInt(v, 16)) };
}

const hex = (v) => (v ?? 0).toString(16).toUpperCase().padStart(8, "0");

function lastBootWords(reading) {
  const l = reading.lastBoot;
  if (l.crash) return `it crashed at PC ${hex(l.crash.pc)} (RETS ${hex(l.crash.rets)}, vector ${l.crash.vec.toString(16).toUpperCase()}, pedal clock ${l.crash.clockMs} ms; look the addresses up in firmware/build-ble/symbols.txt)`;
  return `it stopped at ${l.stageName}, reset by ${reading.boot.resetBy.join(" + ") || "nothing recorded"}`;
}

// What cannot be read at each level, and what is left: the verdict's reason says it in words.
const SCREEN = "Look at the pedal's screen or ask for a photo: nothing else can show";
const NOT_READ = {
  none: `No pedal-like MIDI port. The pedal is unplugged, off, on the red CRASH screen, showing the 12 s LAST BOOT FAILED report (USB starts after it), or in its boot loader. ${SCREEN} the crash registers; they can be read here only after the next boot, in safe mode.`,
  silent: `A pedal-like MIDI port is there but nothing answers: the main loop is stuck or the firmware failed before USB service. ${SCREEN} what it is doing. If the pedal then resets by itself, read again; a pedal stuck like this needs a power cycle or the UBOOT rescue.`,
};

// { result: pass | running | fail | pending | unknown, reason } for the readings so far and a scan, if one ran
export function judge(readings, scan) {
  const now = readings[readings.length - 1];
  if (now.level === "none" || now.level === "silent") return { result: "unknown", reason: NOT_READ[now.level] };
  if (now.level === "identity") {
    return { result: "unknown", reason: IS_OTA(now.id)
      ? `The pedal is in update mode (${now.id.text}), not running firmware. Finish or restart the update; there is no status to read.`
      : IS_ALT(now.product)
        ? `${now.id.text} runs ${now.product.name} ${now.product.version}, an alternative firmware, not Gamut. This tool reads Gamut's status only. To put Gamut back: node tools/op.mjs flash --confirm-flash.`
        : `${now.id.text} answers only the identity query: it is not Gamut. There is no status to read.` };
  }
  if (now.level === "info") {
    return { result: "unknown", reason: `${now.info.identity} ${now.info.version} runs and answers MIDI (DSP load ${now.ping.load}%), but it has no log channel: only the Bluetooth test image and the builds with the clock's line (Gamut at 48 kHz, rate-diag) have one. Bluetooth state, counters and last-boot report cannot be read; use the screen.` };
  }
  if (now.level === "rate") return judgeRate(now.rate);
  const { boot, lastBoot, ble } = now;
  if (boot.safe) return { result: "fail", reason: `The last boot failed: ${lastBootWords(now)}. This boot is safe mode, so Bluetooth stayed off; the boot after this one tries again.` };
  if (ble.state === "failed") {
    const what = FAIL_STEPS[ble.step] ?? `step ${ble.step}`;
    return { result: "fail", reason: `Bluetooth start-up failed: ${what} (code ${ble.code}${ble.stage ? `, stage ${ble.stage}` : ""}${ble.wait ? `, controller waiting on ${ble.wait}` : ""}).` };
  }
  if (ble.state === "starting" || boot.stage !== STAGE_OK) return { result: "pending", reason: `Still starting: boot stage ${boot.stageName}, Bluetooth ${ble.raw}.` };
  if (ble.state !== "advertising") return { result: "fail", reason: ble.state === "off" ? "Bluetooth is off although the boot was normal." : `The status line is not one this tool knows: ${ble.raw}` };
  if (ble.BEN !== null && !(ble.BEN & 1)) return { result: "fail", reason: "The controller says it advertises, but the BLE block is off (BEN bit 0 clear)." };

  const first = readings.find((r) => r.level === "full" && r.ble.state === "advertising");
  if (first === now) return { result: "pending", reason: "One reading only: the counters must be seen rising in a second reading." };
  if (ble.i <= first.ble.i) {
    return { result: "fail", reason: ble.IC45 === 0 ? "No baseband events: interrupt 45 was never enabled (IC45 0)."
      : ble.IEN === 0 ? "No baseband events: interrupt 45 is on, but the baseband never enabled its event (IEN 0)."
        : "No baseband events: the counter i does not rise, so the radio is not running advertising events." };
  }
  const seconds = (Date.parse(now.time) - Date.parse(first.time)) / 1000;   // this computer's clock: the pedal's wraps
  const rate = `Baseband events run at ${((ble.i - first.ble.i) / seconds).toFixed(1)} a second (the advertising interval gives about 10)`;
  const notes = [];
  if (ble.t <= first.ble.t) notes.push("The library's software timers did not fire (t stands still).");
  if (ble.s > 0) notes.push(`The link scheduler asked for a slot timer this image lacks (s ${ble.s}).`);
  if (now.c1?.faults) notes.push(`The second core faulted (PC ${hex(now.c1.pc)}) and was retired: the sound runs on one core.`);
  if (ble.vm && ble.vm.found !== 7) notes.push(`Not all stored radio records were found (V ${ble.vm.found.toString(16)}, 7 expected): the radio has zeros for the missing trims.`);
  const judged = (result, reason) => ({ result, reason: [reason, ...notes].join(" "), notes });
  if (!scan) return judged("running", `${rate}. That is not proof of packets on the air: add --scan.`);
  if (!scan.ok) return judged("unknown", `${rate}, but the scanner could not run: ${scan.why}.`);
  if (scan.hits) return judged("pass", `This Mac saw the advertisement ${scan.hits} times: name "${scan.name}", RSSI ${scan.rssi} dBm, connectable ${scan.connectable}.`);
  return judged("fail", `${rate} and the controller reports advertising, but this Mac saw no advertisement in ${scan.seconds} s (${scan.others} other devices seen, so the scanner works).`);
}

// the clock's line (docs/RATE48-TEST.md, "Reading the result"): what it says of the rate
export function judgeRate(r) {
  const hex = (v) => v.toString(16).toUpperCase().padStart(8, "0");
  if (!r.ok) return { result: "unknown", reason: `The clock line is not one this tool knows: ${r.raw}` };
  if (r.pll0[1] !== r.before.pll0) return { result: "fail", reason: `PLL0 CON1 changed after the start (${hex(r.before.pll0)}, now ${hex(r.pll0[1])}): the PLL that probably clocks USB was written. Put the normal firmware back.` };
  const bit25 = r.before.pll0 & RATE_BIT25 ? `bit 25 of PLL0 CON1 (0x119A4) is set (${hex(r.before.pll0)})` : `bit 25 of PLL0 CON1 (0x119A4) is clear (${hex(r.before.pll0)})`;
  if (r.guard === "SAFE") return { result: "fail", reason: `This start is in safe mode, so it stayed at 44.1 kHz: the start before failed. ${bit25}.` };
  if (r.guard === "BIT25") return { result: "fail", reason: `48 kHz refused: ${bit25}, so the 48 kHz family's source is off. The pedal runs at 44.1 kHz; no clock register was written.` };
  if (!r.windows) return { result: "pending", reason: "No 10 s timing window has finished yet: read again in a few seconds." };
  const off = (r.hz / r.sr - 1) * 100, at = `${r.hz.toFixed(2)} Hz (${off >= 0 ? "+" : ""}${off.toFixed(3)} % from ${r.sr})`;
  if (Math.abs(off) > 0.5) return { result: "fail", reason: `Asked for ${r.sr} Hz, the guitar's blocks come at ${at}.` };
  if (r.guard === "PASS") return { result: "pass", reason: `The I2S runs from the 48 kHz family at ${at}. Next: the sound (docs/RATE48-TEST.md).` };
  return { result: "pass", reason: `The I2S runs at ${at}, and ${bit25}: ${r.before.pll0 & RATE_BIT25 ? "Gamut at 48 kHz will try 48 kHz" : "Gamut at 48 kHz will stay at 44.1 kHz"}.` };
}

// one reading, at the deepest level the pedal answers
async function read(access, timing) {
  const time = new Date().toISOString();
  const ports = [...access.inputs.values()].filter((p) => p.state !== "disconnected" && PORT_RE.test(p.name || ""));
  if (!ports.length) return { time, level: "none" };
  const ed = new Editor(access);
  const info = await ed.connect();
  if (!info) {
    const dev = await new Updater(access, null, timing).identify();
    return dev ? { time, level: "identity", id: dev.id, port: dev.name, product: dev.product } : { time, level: "silent", port: ports[0].name };
  }
  try {
    const lines = await ed.diag();
    if (lines[0]?.startsWith("RATE ")) return { time, level: "rate", info, rate: parseRate(lines[0]) };
    const [boot, last, ble, link, trace, c1] = lines;
    return { time, level: "full", info, boot: parseBoot(boot), lastBoot: parseLast(last), ble: parseBle(ble), link, trace, c1: parseC1(c1) };
  } catch (e) {
    if (e.code !== "timeout") throw e;
    const r = await ed.request(C.PING).catch(() => null);
    if (!r) return { time, level: "silent", port: info.port };      // it answered INFO, then went away: restarting
    return { time, level: "info", info, ping: { load: r[0], bypass: !!(r[1] & 1), secondCore: !!(r[1] & 2) } };
  } finally { ed.close(); }
}

const started = (r) => r.level === "info" || r.level === "identity" || (r.level === "rate" && (!r.rate.ok || r.rate.windows > 0 || r.rate.guard === "BIT25" || r.rate.guard === "SAFE")) || (r.level === "full" && (r.boot.safe || (r.boot.stage === STAGE_OK && r.ble.state !== "starting")));

function show(r, prev, say) {
  if (r.level === "rate") {
    const c = r.rate, hex = (v) => v.toString(16).toUpperCase().padStart(8, "0");
    say(`pedal      ${r.info.identity} ${r.info.version} on "${r.info.port}"`);
    if (!c.ok) { say(`clock      ${c.raw}`); return; }
    say(`rate       asked ${c.ask} Hz, runs at ${c.sr} Hz, guard ${c.guard}; ${c.windows ? `measured ${c.hz.toFixed(2)} Hz over ${(c.ticks / 24e6).toFixed(2)} s (window ${c.windows}: ${c.frames} frames, ${c.ticks} ticks)` : "no 10 s window finished yet"}`);
    say(`PLL0       CON0 ${hex(c.pll0[0])} CON1 ${hex(c.pll0[1])}: bit 25 (the 48 kHz family's source) ${c.pll0[1] & RATE_BIT25 ? "set" : "clear"}; CON1 before the I2S's rate ${hex(c.before.pll0)}`);
    say(`0x10014    ${hex(c.sys)}: bit 8 (the I2S from the 48 kHz family) ${c.sys & RATE_SYS48 ? "set" : "clear"}; before ${hex(c.before.sys)}`);
    say(`ALNK0 DIV  ${hex(c.div)} ([7:5] ${c.div >> 5 & 7}, [4:2] ${c.div >> 2 & 7}); before ${hex(c.before.div)}`);
    say(`PLL1       CON0 ${hex(c.pll1[0])} CON1 ${hex(c.pll1[1])}; HSB 0x10008 ${hex(c.hsb)}; MUX 0x1000C ${hex(c.mux)}`);
    return;
  }
  if (r.level !== "full") {
    say(r.level === "info" ? `pedal      ${r.info.identity} ${r.info.version} on "${r.info.port}": answers MIDI, no log channel`
      : r.level === "identity" ? `pedal      ${r.id.text} on "${r.port}": ${IS_ALT(r.product) ? `${r.product.name} ${r.product.version}, an alternative firmware` : "identity only"}` : r.level === "silent" ? `pedal      "${r.port}" is there, nothing answers` : "pedal      no MIDI port");
    return;
  }
  const { boot, lastBoot: l, ble } = r;
  say(`pedal      ${r.info.identity} ${r.info.version} on "${r.info.port}"`);
  say(`this boot  pedal clock ${(boot.clockMs / 1000).toFixed(1)} s (wraps every 179 s), stage ${boot.stageName}, ${boot.safe ? "SAFE MODE" : "normal"}, reset by ${boot.resetBy.join(" + ") || "?"}, failed boots counted ${boot.failedBoots}`);
  say(`last boot  ${l.failed ? `FAILED: ${lastBootWords(r)}; blocks ${l.blocks}, load ${l.load}%, peak ${l.peak}%, NaN ${l.nans}, CPU1 ${l.cpu1}, loops ${l.loops}` : "finished normally"}`);
  say(`bluetooth  ${ble.raw}`);
  if (r.link) say(`link       ${r.link}`);
  if (r.trace) say(`trace      ${r.trace}`);
  if (r.c1?.faults) say(`2nd core   retired after ${r.c1.faults} fault${r.c1.faults > 1 ? "s" : ""}: PC ${hex(r.c1.pc)}, RETS ${hex(r.c1.rets)}, SP ${hex(r.c1.sp)}, DBG ${hex(r.c1.dbg)}, core ${r.c1.core}'s registers r0..r15 ${r.c1.r.map(hex).join(" ")} (firmware/build-ble/symbols.txt names the addresses)`);
  else if (r.c1?.faults === null) say(`2nd core   ${r.c1.raw}`);
  if (ble.state !== "advertising") return;
  const before = prev?.level === "full" && prev.ble.state === "advertising" ? prev.ble : null;
  for (const k of ["i", "e", "r", "t", "s"]) say(`  ${k.padEnd(5)}${String(ble[k]).padEnd(10)}${(before ? `+${ble[k] - before[k]}` : "").padEnd(9)}${MEANING[k]}`);
  if (ble.vm) say(`  ${"V".padEnd(5)}${`${ble.vm.found.toString(16)} ${ble.vm.area.toString(16)} ${ble.vm.trim.toString(16)}`.toUpperCase().padEnd(19)}${MEANING.vm}`);
  for (const k of ["CON", "IEN", "IPND", "STAT", "IC45", "IC29", "BEN"]) say(`  ${k.padEnd(5)}${(ble[k] ?? 0).toString(16).toUpperCase().padEnd(19)}${MEANING[k]}`);
}

function compileScanner() {
  const bin = resolve(ROOT, "build/ble-scan"), src = resolve(ROOT, "tools/ble-scan.swift"), plist = `${bin}.plist`;
  if (existsSync(bin) && statSync(bin).mtimeMs > statSync(src).mtimeMs) return bin;
  mkdirSync(dirname(bin), { recursive: true });
  writeFileSync(plist, `<?xml version="1.0" encoding="UTF-8"?><plist version="1.0"><dict><key>CFBundleIdentifier</key><string>org.openpocket.ble-scan</string><key>NSBluetoothAlwaysUsageDescription</key><string>Listens for the OpenPocket test advertisement.</string></dict></plist>`);
  const r = spawnSync("swiftc", ["-O", src, "-o", bin, "-Xlinker", "-sectcreate", "-Xlinker", "__TEXT", "-Xlinker", "__info_plist", "-Xlinker", plist], { encoding: "utf8" });
  if (r.error || r.status !== 0) throw new Error(`swiftc failed: ${r.error?.message || r.stderr}`);
  return bin;
}

function scanPass(bin, seconds, uuid) {
  return new Promise((done) => {
    const child = spawn(bin, [String(seconds), ...(uuid ? [uuid] : [])], { stdio: ["ignore", "pipe", "ignore"] });
    const killer = setTimeout(() => child.kill(), (seconds + 15) * 1000);
    let out = "";
    child.stdout.on("data", (d) => { out += d; });
    child.on("close", () => {
      clearTimeout(killer);
      const lines = out.split("\n").filter(Boolean).map((l) => JSON.parse(l));
      done({ hits: lines.filter((l) => !l.done), end: lines.find((l) => l.done) });
    });
  });
}

// the service-UUID pass, then the open pass, or why they could not run
export async function macScan(seconds) {
  if (process.platform !== "darwin") return { ok: false, why: "the scanner is for macOS only" };
  let bin;
  try { bin = compileScanner(); } catch (e) { return { ok: false, why: e.message }; }
  const passes = [await scanPass(bin, seconds, BLE_MIDI), await scanPass(bin, seconds, null)];
  const end = passes.map((p) => p.end).find((e) => e && e.state !== 5) || passes[1].end;
  if (!end) return { ok: false, why: "the helper stopped without a result" };
  if (end.state !== 5) return { ok: false, why: `the Bluetooth adapter is not usable (state ${end.state}, authorization ${end.auth}; 5 and 3 are needed)` };
  const hits = passes.flatMap((p) => p.hits);
  const named = hits.find((h) => h.name) || hits[0];
  return { ok: true, seconds: seconds * 2, hits: hits.length, others: passes[1].end.others, name: named?.name ?? null, id: named?.id ?? null,
    rssi: hits.length ? Math.max(...hits.map((h) => h.rssi)) : null, connectable: named?.connectable ?? null, services: named?.services ?? [] };
}

function parse(argv) {
  const a = { follow: false, json: false, wait: 0, interval: 2, count: 2, scan: 0 };
  for (let i = 0; i < argv.length; i++) {
    const v = argv[i];
    if (v === "--follow") a.follow = true;
    else if (v === "--json") a.json = true;
    else if (["--wait", "--interval", "--count", "--scan"].includes(v)) {
      const n = Number(argv[++i]);
      if (!(n >= 0)) throw new Error(`${v} needs a number`);
      a[v.slice(2)] = n;
    } else throw new Error(`unknown argument ${v}`);
  }
  if (a.follow && a.scan) throw new Error("--scan needs an end: leave out --follow");
  return a;
}

const EXIT = { pass: 0, running: 0, fail: 1, pending: 3, unknown: 3 };

// main(argv, { access, say, scan, timing }): the exit code. access defaults to the real USB MIDI ports.
export async function main(argv, { access, say = console.log, scan = macScan, timing } = {}) {
  let args, node = null;
  try { args = parse(argv); } catch (e) { say(`${e.message}\n${USAGE}`); return 2; }
  const sleep = (s) => new Promise((r) => setTimeout(r, s * 1000));
  try {
    if (!access) {
      const midi = await import("@julusian/midi").then((m) => m.default || m, () => null);
      if (!midi) { say("the MIDI library is not installed: run `npm ci --prefix tools` once (docs/BUILDING.md)."); return 2; }
      node = (await import("./midi-node.mjs")).nodeMidiAccess(midi);
      access = node;
    }
    const readings = [];
    const end = Date.now() + args.wait * 1000;
    let r = await read(access, timing);
    while (!started(r) && Date.now() < end) { await sleep(Math.min(1, args.interval || 1)); r = await read(access, timing); }
    let verdict;
    for (let n = 0; ; n++) {
      readings.push(r);
      verdict = judge(readings);
      if (args.json) { if (!args.scan) say(JSON.stringify({ ...r, verdict })); } else { show(r, readings[readings.length - 2], say); say(`verdict    ${verdict.result.toUpperCase()}: ${verdict.reason}`); }
      if (!args.follow && n + 1 >= args.count) break;
      await sleep(args.interval);
      r = await read(access, timing);
    }
    if (args.scan) {
      if (!args.json) say(`scanning   ${args.scan} s on the BLE-MIDI service UUID, then ${args.scan} s on everything (never connects)`);
      const result = await scan(args.scan);
      readings.push(await read(access, timing));
      verdict = judge(readings, result);
      if (args.json) say(JSON.stringify({ ...readings[readings.length - 1], scan: result, verdict }));
      else { show(readings[readings.length - 1], readings[readings.length - 2], say); say(`verdict    ${verdict.result.toUpperCase()}: ${verdict.reason}`); }
    }
    return EXIT[verdict.result];
  } finally {
    if (node) node.close();
  }
}
