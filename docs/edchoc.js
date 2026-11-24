// SPDX-License-Identifier: GPL-3.0-only
// Gamut web editor: an M-VAVE Chocolate or Chocolate Plus, in the MIDI section. The page connects to it over Bluetooth
// itself (Web Bluetooth, docs/pxble.js), or takes it as a MIDI port when the computer paired it; shows the model's
// controls; and lets each one be taught (press it) and given something to do on the pedal. The mapping is kept in the
// browser, per model, and works while this page is open and connected to the pedal: the pedal stores none of it.
// The models and the mapping's rules: docs/pxchoc.js.

import { app, $, h, on, blk, typeOf, slotName, sleep } from "./edcore.js";
import { selectPreset } from "./edpresets.js";
import { fromController, claimFirst, controllerNames, setAirController, note, run, tgtName } from "./edmidi.js";
import { pick, listen } from "./pxble.js";
import { MODELS, modelById, modelFor, prefixes, msgSrc, sameSrc, srcText, defaultProfile, binding, controlFor, teach, assign, act,
  tgtKey, keyTgt, cleanConfig, tap, timeValue, B_DELAY } from "./pxchoc.js";

const KEY = "openpocket-chocolate-v1";
const RELEASE_MS = 900;               // while a switch is taught: how long its release is waited for after its press
const RETRY_MS = 2000;                // a Chocolate that went away: how long before the page looks for it again
let cfg = cleanConfig(null);          // { model, profiles }
const undo = [];                      // cfg before each change, as JSON, oldest first
// the Chocolate this page connected to itself. state: off | choosing | connecting | on | waiting (it went away)
const link = { state: "off", device: null, name: "", why: "" };
let port = "";                        // a Chocolate the computer paired itself: the name of its MIDI port
let teaching = null;                  // { queue: [control ids], done: [sources taught in this round], first: { src, timer } | null }
let said = "";                        // what happened last, said under the controls
let taps = [];
const lit = new Map();                // control id -> the timer that ends its light

const model = () => modelById(cfg.model);
const profile = () => cfg.profiles[cfg.model];
const ctl = (id) => model().controls.find((c) => c.id === id);
function load() { try { cfg = cleanConfig(JSON.parse(localStorage.getItem(KEY) || "null")); } catch (_) { } }
function save() { try { localStorage.setItem(KEY, JSON.stringify(cfg)); } catch (_) { } }
// a change of the mapping: kept at once, and Undo brings back what was there
function change(next, what) {
  undo.push(JSON.stringify(cfg));
  if (undo.length > 50) undo.shift();
  cfg = { ...cfg, profiles: { ...cfg.profiles, [cfg.model]: next } };
  said = what;
  save(); render();
}
function undoLast() {
  stopTeach();
  const prev = cleanConfig(JSON.parse(undo.pop()));
  cfg = { ...cfg, profiles: { ...cfg.profiles, [cfg.model]: prev.profiles[cfg.model] } };
  said = "Undone.";
  save(); render();
}
// the model a connected device says it is: its controls are the ones shown
function detect(name) {
  const m = modelFor(name);
  if (!m || m.id === cfg.model) return;
  stopTeach();
  cfg = { ...cfg, model: m.id };
  said = `This is a ${m.name}: its controls are shown.`;
  save();
}

// ---- names ----
function doesName(t) {
  if (!t) return "nothing";
  if (t.kind === "slot") return `preset ${slotName(t.slot)}${app.slots[t.slot] ? ` ${app.slots[t.slot].name}` : ""}`;
  return t.kind === "tap" ? "tap tempo" : tgtName(t);
}

// ---- what a control does ----
function tapTempo() {
  const r = tap(taps, performance.now());
  taps = r.taps;
  if (r.ms === null) return "tap tempo: tap again";
  const p = typeOf(app.st.preset, B_DELAY).params[0], v = timeValue(p && p.texts, r.ms);
  if (v < 0) return "tap tempo: this delay has no time to set";
  run({ do: "param", b: B_DELAY, k: 0, v });
  return `delay time ${p.texts[v]} (${Math.round(60000 / r.ms)} BPM)`;
}
function perform(a, tgt) {
  if (a.do === "tap") return tapTempo();
  if (a.do === "slot") { selectPreset(a.slot, { ask: false }); return doesName(tgt); }
  run(a);
  return `${tgtName(tgt)}${a.do === "param" ? ` ${a.v}` : a.do === "on" ? (a.v ? ": on" : ": off") : ""}`;
}
function light(id) {
  const el = document.querySelector(`.choc-ctl[data-c="${id}"]`);
  clearTimeout(lit.get(id));
  lit.set(id, setTimeout(() => { lit.delete(id); const now = document.querySelector(`.choc-ctl[data-c="${id}"]`); if (now) now.classList.remove("hit"); }, 350));
  if (el) el.classList.add("hit");
}
const isChocolate = (from) => (link.state === "on" && from === link.name) || !!modelFor(from);
// a message of a controller, before the learned controls see it: true when it was a Chocolate's and did its work here
function claim(from, m) {
  if (!isChocolate(from)) return false;
  if (teaching) { teachFeed(m); return true; }
  const mo = model(), p = profile(), id = controlFor(mo, p, m);
  if (!id) return false;
  light(id);
  const c = ctl(id), tgt = p[id].tgt;
  if (!tgt) return false;             // a control with nothing to do here can still be a learned control below
  const a = act(c, binding(mo, p, id), tgt, m, { on: (b) => app.st.preset.on[b], ntypes: (b) => blk(b).types.length });
  note(from, m, a ? `${c.label} → ${perform(a, tgt)}` : `${c.label}: the switch released, nothing to do`, a ? "hit" : "");
  return true;
}

// ---- teaching: the control that waits takes the next message as its own ----
function startTeach(ids) {
  stopTeach();
  teaching = { queue: [...ids], done: [], first: null };
  said = "";
  render();
}
function stopTeach() {
  if (teaching && teaching.first) clearTimeout(teaching.first.timer);
  teaching = null;
}
function nextTeach() {
  if (teaching.first) clearTimeout(teaching.first.timer);
  teaching.first = null;
  teaching.queue.shift();
  if (!teaching.queue.length) teaching = null;
}
function taught(src, press) {
  const c = ctl(teaching.queue[0]);
  teaching.done.push(src);
  nextTeach();
  change(teach(profile(), c.id, src, press), `${c.label} sends ${srcText(src)}.`);
}
function teachFeed(m) {
  const s = msgSrc(m), c = ctl(teaching.queue[0]), first = teaching.first;
  if (!s) return;
  if (first) {                        // its press was seen: a low value of the same control is its release
    if (sameSrc(first.src, s) && m.type === "cc" && m.value < 64) taught(first.src, "high");
    return;
  }
  if (m.type === "noteoff" || teaching.done.some((d) => sameSrc(d, s))) return;   // the release of the control before
  if (c.kind === "pedal") { if (m.type === "cc") taught(s, "high"); return; }
  if (m.type !== "cc" || m.value < 64) { taught(s, "any"); return; }
  // a switch that sends nothing more within the wait sends one message per press: each one is a press then
  teaching.first = { src: s, timer: setTimeout(() => taught(s, "any"), RELEASE_MS) };
  render();
}

// ---- the Bluetooth link ----
function setLink(state, why = "") {
  link.state = state; link.why = why;
  setAirController(state === "on" ? link.name : "");
  if (app.view === "midi") render();
}
async function open(device) {
  await listen(device, (bytes) => fromController(link.name, bytes));
  if (link.device !== device) { device.gatt.disconnect(); return; }   // stopped meanwhile
  detect(link.name);
  setLink("on");
}
// state "connecting": one try, and a failure is said. "waiting": a Chocolate that was connected and went away (asleep,
// switched off, out of reach) is looked for until it is back or Stop is pressed
async function reopen(device, state) {
  setLink(state);
  while (link.device === device) {
    try { await open(device); return; }
    catch (e) {
      if (link.device !== device) return;
      if (state === "waiting") { await sleep(RETRY_MS); continue; }
      link.device = null;
      setLink("off", `${link.name} did not connect (${e.message}). Is it switched on, and not connected to something else?`);
    }
  }
}
async function connect() {
  let device;
  setLink("choosing");
  try { device = await pick(navigator.bluetooth, prefixes()); }
  catch (e) { setLink("off", /cancel/i.test(e.message) ? "" : `Bluetooth did not start: ${e.message}`); return; }
  link.device = device;
  link.name = device.name || "Bluetooth controller";
  device.addEventListener("gattserverdisconnected", () => { if (link.device === device && link.state === "on") reopen(device, "waiting"); });
  reopen(device, "connecting");
}
function disconnect() {
  const d = link.device;
  link.device = null;
  setLink("off");
  if (d && d.gatt.connected) d.gatt.disconnect();
}
// a Chocolate among the MIDI ports (the computer paired it): no link of this page's own is needed
function ports() {
  const now = controllerNames().find((n) => modelFor(n) && !(link.state === "on" && n === link.name)) || "";
  if (now && now !== port) detect(now);
  port = now;
}

// ---- the card ----
function options(c) {
  const opt = (t, text) => h("option", { value: tgtKey(t), text });
  const p = app.st.preset;
  if (c.kind === "pedal") return [opt(null, "Nothing"), ...app.cat.blocks.map((B, b) =>
    h("optgroup", { label: B.label }, typeOf(p, b).params.map((x, k) => x && opt({ kind: "param", b, k }, `${B.label} · ${x.name}`))))];
  return [opt(null, "Nothing"),
    h("optgroup", { label: "Presets" }, opt({ kind: "preset", step: -1 }, "Previous preset"), opt({ kind: "preset", step: 1 }, "Next preset")),
    h("optgroup", { label: "Switch an effect" }, app.cat.blocks.map((B, b) => opt({ kind: "on", b }, `${B.label} on / off`))),
    h("optgroup", { label: "Tempo" }, opt({ kind: "tap" }, "Tap tempo (delay time)")),
    h("optgroup", { label: "Load a preset" }, app.slots.map((s) => opt({ kind: "slot", slot: s.slot }, `${slotName(s.slot)} ${s.name}`)))];
}
function tile(c) {
  const p = profile(), b = binding(model(), p, c.id), tgt = p[c.id].tgt, key = tgtKey(tgt), waiting = !!teaching && teaching.queue[0] === c.id;
  const sel = h("select", { id: `chocdo-${c.id}`, "aria-label": `What ${c.label} does`,
    onchange: () => { const t = keyTgt(sel.value); change(assign(profile(), c.id, t), `${c.label} does ${doesName(t)}.`); } }, options(c));
  sel.value = key;
  if (sel.value !== key) { sel.append(h("option", { value: key, text: doesName(tgt) })); sel.value = key; }   // (a setting this preset's type does not have)
  return h("div", { class: `choc-ctl ${c.kind}${waiting ? " learning" : ""}${lit.has(c.id) ? " hit" : ""}`, "data-c": c.id },
    h("div", { class: "choc-cap" }, h("b", { text: c.label }), c.hint && h("small", { text: c.hint })),
    sel,
    h("div", { class: "choc-src" },
      h("span", { id: `chocsrc-${c.id}`, text: !b.src ? "Not taught yet" : b.taught ? `Sends ${srcText(b.src)}` : `Should send ${srcText(b.src)}` }),
      h("button", { type: "button", class: "btn small", id: `chocteach-${c.id}`, "aria-pressed": waiting ? "true" : "false",
        title: c.kind === "pedal" ? "Click, then move the pedal: the page learns what it sends." : `Click, then press ${c.label} on the Chocolate: the page learns what it sends.`,
        onclick: () => (waiting ? (stopTeach(), render()) : startTeach([c.id])) }, waiting ? "Waiting…" : b.taught ? "Teach again" : "Teach")));
}
function linkRow() {
  const stop = (text) => h("button", { type: "button", class: "btn small", id: "chocdisc", text, onclick: disconnect });
  if (link.state === "on") return [h("span", { class: "chip ok", text: `Connected over Bluetooth: ${link.name}` }), stop("Disconnect")];
  if (link.state === "waiting") return [h("span", { class: "warn", text: `${link.name} went away. It is taken back as soon as it is in reach again.` }), stop("Stop")];
  if (link.state !== "off") return [h("span", { class: "dim", text: link.state === "choosing" ? "Choose the Chocolate in the browser's list…" : `Connecting to ${link.name}…` })];
  return [port && h("span", { class: "chip ok", text: `Connected through this computer: ${port}` }),
    navigator.bluetooth && !port && h("button", { type: "button", class: "btn primary", id: "chocconnect", text: "Connect over Bluetooth", onclick: connect })];
}
function helpText() {
  if (link.why) return link.why;
  if (link.state !== "off" || port) return "";
  if (!navigator.bluetooth) return "This browser cannot connect to Bluetooth devices itself: Chrome and Edge can, on a computer and on Android. You can still pair the Chocolate with this computer as a Bluetooth MIDI device (on a Mac: Audio MIDI Setup, Window, Show MIDI Studio, the Bluetooth button). It then shows under Controllers, and its controls work here in the same way.";
  return `Switch the Chocolate on, press Connect and choose it in the browser's list. ${model().reach}`;
}
function teachText() {
  if (!teaching) return said;
  const c = ctl(teaching.queue[0]), more = teaching.queue.length - 1;
  const rest = more ? ` Then ${more} more.` : "";
  if (teaching.first) return `${c.label}: ${srcText(teaching.first.src)}. Let go of the switch.`;
  return c.kind === "pedal" ? `Move the pedal on the Chocolate.${rest}` : `Press ${c.label} on the Chocolate, then let go.${rest}`;
}
function render() {
  const el = $("midichoc"), keep = el.contains(document.activeElement) ? document.activeElement.id : "";
  el.textContent = "";
  if (app.conn !== "ready" || !app.st) return;
  const mo = model(), why = helpText();
  const pickModel = h("select", { id: "chocmodel", "aria-label": "Which Chocolate",
    onchange: () => { stopTeach(); cfg = { ...cfg, model: pickModel.value }; said = ""; save(); render(); } },
    MODELS.map((m) => h("option", { value: m.id, text: m.name })));
  pickModel.value = mo.id;
  el.append(
    h("div", { class: "card-head" }, h("h2", { id: "midichoc-h", text: "Chocolate foot controller" }), h("span", { class: "grow" }),
      pickModel,
      h("button", { type: "button", class: "btn small", id: "chocundo", text: "Undo", disabled: !undo.length, onclick: undoLast }),
      h("button", { type: "button", class: "btn small", id: "chocreset", text: "Back to the defaults",
        onclick: () => { stopTeach(); change(defaultProfile(model()), `${model().name}: back to the defaults. Undo brings your mapping back.`); } })),
    h("div", { class: "learnbar", id: "choclink" }, linkRow()),
    why && h("p", { class: link.why ? "warn small" : "dim small", id: "chochelp", text: why }),
    h("div", { class: "choc", id: "choc" }, mo.controls.map(tile)),
    h("div", { class: "learnbar" },
      h("button", { type: "button", class: `btn small${teaching ? " learning" : ""}`, id: "chocteach", text: teaching ? "Stop teaching" : "Teach every control",
        onclick: () => (teaching ? (stopTeach(), render()) : startTeach(mo.controls.map((c) => c.id))) }),
      teaching && teaching.queue.length > 1 && h("button", { type: "button", class: "btn small", id: "chocskip", text: "Skip this one", onclick: () => { nextTeach(); render(); } })),
    h("p", { class: `learnstate${teaching ? " on" : ""}`, id: "chocstate", role: "status", text: teachText() }),
    h("p", { class: "dim small", text: `${mo.known} The mapping is kept in this browser as you change it, one for each model. The Chocolate drives the pedal through this page, so it works while the page is open and connected to the pedal.` }));
  if (keep && $(keep)) $(keep).focus();
}
// the names in the lists follow the preset; a list that is open is left alone
const picking = () => $("midichoc").contains(document.activeElement) && document.activeElement.tagName === "SELECT";

export function initChoc() {
  load();
  claimFirst(claim);
  // (edmidi.js heard of the ports first: it was started first)
  on("conn", () => { if (app.conn !== "ready") stopTeach(); ports(); render(); });
  on("ports", () => { ports(); if (app.view === "midi") render(); });
  on("state", () => { if (app.view === "midi" && !picking()) render(); });
  on("slots", () => { if (app.view === "midi" && !picking()) render(); });
  on("view", () => { if (app.view === "midi") render(); else stopTeach(); });
  addEventListener("keydown", (e) => { if (e.key === "Escape" && teaching) { stopTeach(); render(); } });
}
