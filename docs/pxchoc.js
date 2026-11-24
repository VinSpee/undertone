// SPDX-License-Identifier: GPL-3.0-only
// Gamut web editor: the M-VAVE Chocolate foot controllers. What each model is (its name over Bluetooth, its controls,
// the messages its controls send where that is known, what each does on the pedal by default), and the mapping the
// player edits: per model and per control, the message the control sends and what it does. A control does not say
// which one it is: only its message tells, and that depends on how the Chocolate is set up, so a control is taught by
// pressing it. No DOM, no port here: docs/edchoc.js is the page, docs/pxble.js the radio.

import { action, NBLK, NPAR } from "./pxmidi.js";

export const B_DELAY = 9;             // the DELAY block, whose first setting is TIME (docs/EDITOR-PROTOCOL.md)

// ---- the models ----
// To add a model or correct one, edit its entry: nothing else in the editor names a model or a control.
//   match     the name the controller gives over Bluetooth, or its MIDI port's name when the computer paired it
//   names     the starts of the names it may give, for the browser's Bluetooth chooser
//   controls  { id, label, kind: "switch" | "pedal", hint }, in the order they are shown
//   sends     control id -> { src, press }: the message a control sends before it is taught, where one is known
//   does      control id -> what it does on the pedal until the player chooses (a target, below)
//   known     what was checked on a real one, said on the page
//   reach     what the controller needs before a computer finds it over Bluetooth, said on the page ("" = nothing known)
const sw = (id, label, hint = "") => ({ id, label, kind: "switch", hint });
const FOUR = [sw("A", "A"), sw("B", "B"), sw("C", "C"), sw("D", "D")];
const PAIRS = [sw("AB", "A + B", "both at once"), sw("CD", "C + D", "both at once")];
const PEDAL = { id: "EXP", label: "Pedal", kind: "pedal", hint: "an expression pedal in its jack" };
const cc = (n, press = "high") => ({ src: { type: "cc", ch: 0, n }, press });
const flip = (b) => ({ kind: "on", b, mode: "toggle" });
// DRIVE, MOD, DELAY and REVERB under A to D, as tools/chocolate/today.json; the pairs step through the presets
const DOES = { A: flip(4), B: flip(8), C: flip(9), D: flip(10), AB: { kind: "preset", step: -1 }, CD: { kind: "preset", step: 1 } };

export const MODELS = [
  { id: "plus", name: "Chocolate Plus", match: /foot\s*ctrl\s*plus|chocolate\s*plus/i, names: ["FootCtrlPlus", "Chocolate Plus"],
    controls: [...FOUR, ...PAIRS, PEDAL],
    sends: { A: cc(0) },                // as captured from one (firmware/apps/gamut/tests/midisim.c): CC 0 = 127 on channel 2
    does: DOES,
    known: "One real Chocolate Plus was read: its footswitch A sent CC 0. What the other controls send is not known, so teach each one.",
    reach: "Set its switch to O. On H it looks for a pedal by itself, and a computer does not find it." },
  { id: "chocolate", name: "Chocolate", match: /foot\s*ctrl|chocolate/i, names: ["FootCtrl", "Chocolate"],
    controls: [...FOUR, ...PAIRS, PEDAL],
    // its "Manufacturer control" mode as a player wrote it up (forum.mod.audio, 2021): A to D 127 down, 0 up; the pairs
    // send one 0 when pressed, and their release is the last switch's 0
    sends: { A: cc(20), B: cc(21), C: cc(22), D: cc(23), AB: cc(24, "any"), CD: cc(25, "any") },
    does: DOES,
    known: "No real Chocolate was read here. The messages shown come from a player's write-up of its Manufacturer control mode: teach a control that does not answer.",
    reach: "" },
];
export const modelById = (id) => MODELS.find((m) => m.id === id) || MODELS[0];
// the model a device of this name is, or null: the first match wins, so a name that says more comes first
export const modelFor = (name) => MODELS.find((m) => m.match.test(name || "")) || null;
export const prefixes = () => [...new Set(MODELS.flatMap((m) => m.names))];

// ---- messages ----
// A source: { type: "cc" | "pc" | "note", ch (1..16, 0 = any channel), n (the controller, program or note number) }.
// msg: what pxmidi.js decode() gives.
export function msgSrc(m) {
  if (m.type === "cc") return { type: "cc", ch: m.ch, n: m.cc };
  if (m.type === "pc") return { type: "pc", ch: m.ch, n: m.program };
  if (m.type === "note" || m.type === "noteoff") return { type: "note", ch: m.ch, n: m.note };
  return null;
}
export const sameSrc = (a, b) => a.type === b.type && a.n === b.n && (!a.ch || !b.ch || a.ch === b.ch);
export const srcText = (s) => `${s.type === "cc" ? "CC" : s.type === "pc" ? "Program" : "Note"} ${s.n}${s.ch ? ` · ch ${s.ch}` : ""}`;

// ---- a profile: control id -> { src (taught, or null), press, tgt (or null: nothing) } ----
// press says which of a switch's messages is a press: "high" (a value of 64 or more; the release sends less) or "any"
// (every message: a switch that sends one message per press, whatever its value). tgt is one of pxmidi.js's targets
// ({ kind: "on", b, mode: "toggle" }, { kind: "preset", step }, { kind: "param", b, k }), { kind: "slot", slot } to
// load one preset, or { kind: "tap" }: tap the tempo of the delay.
export function defaultProfile(model) {
  return Object.fromEntries(model.controls.map((c) => [c.id, { src: null, press: "high", tgt: model.does[c.id] ? { ...model.does[c.id] } : null }]));
}
// what a control sends: what it was taught, else the model's own message unless another control was taught that one
export function binding(model, profile, id) {
  const e = profile[id];
  if (e.src) return { src: e.src, press: e.press, taught: true };
  const d = model.sends[id];
  if (!d || model.controls.some((c) => profile[c.id].src && sameSrc(profile[c.id].src, d.src))) return { src: null, press: "high", taught: false };
  return { src: d.src, press: d.press, taught: false };
}
// the control a message comes from, or null
export function controlFor(model, profile, m) {
  const s = msgSrc(m);
  if (!s) return null;
  const c = model.controls.find((x) => { const b = binding(model, profile, x.id); return b.src && sameSrc(b.src, s); });
  return c ? c.id : null;
}
// a control taught: this message is its own, and no other control's any more
export function teach(profile, id, src, press) {
  const out = {};
  for (const [k, e] of Object.entries(profile)) out[k] = k === id ? { ...e, src, press } : e.src && sameSrc(e.src, src) ? { ...e, src: null, press: "high" } : e;
  return out;
}
export const assign = (profile, id, tgt) => ({ ...profile, [id]: { ...profile[id], tgt } });

const pressed = (bind, m) => m.type === "pc" || m.type === "note" || (m.type === "cc" && (bind.press === "any" || m.value >= 64));
// what a control's message does: one of pxmidi.js action()'s results, { do: "slot", slot }, { do: "tap" }, or null
// (the release of a switch, a control with nothing to do). ctx: { on(b), ntypes(b) }
export function act(control, bind, tgt, m, ctx) {
  if (!tgt) return null;
  if (control.kind === "pedal") return m.type === "cc" ? action({ tgt }, m.value, ctx) : null;
  if (!pressed(bind, m)) return null;
  if (tgt.kind === "slot") return { do: "slot", slot: tgt.slot };
  if (tgt.kind === "tap") return { do: "tap" };
  return action({ tgt }, 127, ctx);
}

// ---- a target as an option's value, and back ----
export function tgtKey(t) {
  if (!t) return "";
  return t.kind === "on" ? `on:${t.b}` : t.kind === "preset" ? `preset:${t.step}` : t.kind === "slot" ? `slot:${t.slot}` : t.kind === "param" ? `param:${t.b}:${t.k}` : t.kind;
}
export function keyTgt(key) {
  const [kind, a, b] = key.split(":");
  return kind === "on" ? flip(+a) : kind === "preset" ? { kind, step: +a } : kind === "slot" ? { kind, slot: +a } : kind === "param" ? { kind, b: +a, k: +b } : kind === "tap" ? { kind } : null;
}

// ---- what the browser kept (localStorage JSON) -> { model, profiles }; whatever is not well formed is the default ----
const int = (v, lo, hi) => Number.isInteger(v) && v >= lo && v <= hi;
function cleanTgt(control, t) {
  if (!t) return null;
  if (control.kind === "pedal") return t.kind === "param" && int(t.b, 0, NBLK - 1) && int(t.k, 0, NPAR - 1) ? { kind: "param", b: t.b, k: t.k } : null;
  if (t.kind === "on" && int(t.b, 0, NBLK - 1)) return flip(t.b);
  if (t.kind === "preset" && (t.step === 1 || t.step === -1)) return { kind: "preset", step: t.step };
  if (t.kind === "slot" && int(t.slot, 0, 126)) return { kind: "slot", slot: t.slot };
  return t.kind === "tap" ? { kind: "tap" } : null;
}
const cleanSrc = (s) => s && ["cc", "pc", "note"].includes(s.type) && int(s.ch, 0, 16) && int(s.n, 0, 127) ? { type: s.type, ch: s.ch, n: s.n } : null;
export function cleanConfig(j) {
  const profiles = {};
  for (const model of MODELS) {
    const kept = j && j.profiles && j.profiles[model.id], p = defaultProfile(model);
    if (kept && typeof kept === "object") for (const c of model.controls) {
      const e = kept[c.id];
      if (e && typeof e === "object") p[c.id] = { src: cleanSrc(e.src), press: e.press === "any" ? "any" : "high", tgt: cleanTgt(c, e.tgt) };
    }
    profiles[model.id] = p;
  }
  return { model: modelById(j && j.model).id, profiles };
}

// ---- tap tempo ----
export const TAP_MIN = 200, TAP_MAX = 2000;   // the quarter notes the pedal takes from MIDI clock as well (docs/MIDI.md)
// a tap at `now` (ms) after the earlier `taps` -> the taps that still count (the last four of a run) and the quarter
// note they give: the mean of their gaps, or null for a first tap or a bounce
export function tap(taps, now) {
  const run = taps.length && now - taps[taps.length - 1] <= TAP_MAX ? [...taps.slice(-3), now] : [now];
  const ms = run.length > 1 ? (run[run.length - 1] - run[0]) / (run.length - 1) : null;
  return { taps: run, ms: ms !== null && ms >= TAP_MIN ? ms : null };
}
// the value 0..100 whose text on the pedal ("450 MS") is the time nearest to ms, or -1 when the texts are not times
export function timeValue(texts, ms) {
  let best = -1, gap = Infinity;
  (texts || []).forEach((t, v) => {
    const got = /^(\d+) MS$/.exec(t || "");
    if (got && Math.abs(+got[1] - ms) < gap) { gap = Math.abs(+got[1] - ms); best = v; }
  });
  return best;
}
