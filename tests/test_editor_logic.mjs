// SPDX-License-Identifier: GPL-3.0-only
// OpenPocket — the web editor's own logic, without a browser or a pedal: the Control Change map and the learned
// controls (docs/pxmidi.js) against docs/MIDI.md, the Chocolate foot controllers (docs/pxble.js: the Bluetooth MIDI
// packets, with the packets firmware/apps/gamut/tests/midisim.c gives the pedal's reader; docs/pxchoc.js: the models and
// the mapping), and the model library and slot arithmetic (docs/pxlib.js) against the engine's rule
// (firmware/apps/gamut/engine/px_dsp.c px_nam_model / px_nam_knob); TONE3000's same-tab bookkeeping (docs/pxt3k.js), in a
// stand-in page address and session storage. Run by tests/run_tests.sh.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { webcrypto } from "node:crypto";
import { ccParam, ccOn, ccToggle, ccType, ccTarget, toCc, fromCc, typeToCc, typeFromCc, decode, learn, resolve, action, cleanMappings, NBLK, NPAR } from "../docs/pxmidi.js";
import { parsePacket } from "../docs/pxble.js";
import { MODELS, modelById, modelFor, prefixes, msgSrc, srcText, defaultProfile, binding, controlFor, teach, assign, act, tgtKey, keyTgt, cleanConfig, tap, timeValue, TAP_MAX } from "../docs/pxchoc.js";
import { knobIndex, indexKnob, slotRef, presetSlot, retarget, usage, packedName, renamePacked, cleanSlotName, Library, pedalKey, planMove } from "../docs/pxlib.js";

const ROOT = fileURLToPath(new URL("..", import.meta.url));
const check = async (what, fn) => { await fn(); console.log(`${what.padEnd(76)} ok`); };

// ---- MIDI ----
await check("the Control Change map is the one docs/MIDI.md prints", () => {
  const md = readFileSync(`${ROOT}docs/MIDI.md`, "utf8");
  const rows = [...md.matchAll(/^\| (GATE|COMP|PITCH|SFX|DRIVE|AMP|CAB|EQ|MOD|DELAY|REVERB|SYN) \| (\d+) \| (\d+) \| (\d+) \| (\d+) \| (\d+) \| (\d+) \| (\d+) \|$/gm)];
  assert.equal(rows.length, NBLK);
  rows.forEach((r, b) => {
    assert.equal(ccOn(b), +r[2]); assert.equal(ccType(b), +r[3]);
    for (let k = 0; k < NPAR; k++) assert.equal(ccParam(b, k), +r[4 + k]);
  });
  assert.equal(ccToggle(5), 13);
});
await check("every number of the map is unique, and ccTarget is its inverse", () => {
  const seen = new Set([7]);
  for (let b = 0; b < NBLK; b++) {
    for (const [cc, t] of [[ccOn(b), { kind: "on", b }], [ccToggle(b), { kind: "toggle", b }], [ccType(b), { kind: "type", b }],
      ...Array.from({ length: NPAR }, (_, k) => [ccParam(b, k), { kind: "param", b, k }])]) {
      assert.ok(!seen.has(cc), `CC ${cc} twice`); seen.add(cc);
      assert.deepEqual(ccTarget(cc), t);
    }
  }
  assert.deepEqual(ccTarget(7), { kind: "master" });
  for (const free of [0, 6, 32, 38, 64, 98, 101, 120, 127]) assert.equal(ccTarget(free), null);
});
await check("values scale as the pedal's: 0..100 to 0..127 and back exactly", () => {
  for (let v = 0; v <= 100; v++) assert.equal(fromCc(toCc(v)), v);
  assert.equal(toCc(100), 127); assert.equal(fromCc(64), 50);
  for (const n of [1, 4, 9, 11]) for (let t = 0; t < n; t++) assert.equal(typeFromCc(typeToCc(t, n), n), t);
  assert.equal(typeFromCc(127, 9), 8);
});
await check("messages are decoded; SysEx and data bytes are not musical", () => {
  assert.deepEqual(decode([0xB2, 11, 99]), { type: "cc", ch: 3, cc: 11, value: 99 });
  assert.deepEqual(decode([0xC0, 51]), { type: "pc", ch: 1, program: 51 });
  assert.equal(decode([0xF8]).type, "clock");
  assert.equal(decode([0xF0, 0x7D, 0xF7]), null);
  assert.equal(decode([0x40, 0x10]), null);
  assert.equal(decode([]), null);
});
await check("a learned control: one control per target and one target per control, in its scope", () => {
  let m = learn([], { ch: 1, cc: 11 }, { kind: "param", b: 5, k: 1 }, null, "a");
  m = learn(m, { ch: 1, cc: 12 }, { kind: "param", b: 5, k: 1 }, null, "b");           // the target taught again
  assert.deepEqual(m.map((x) => x.id), ["b"]);
  m = learn(m, { ch: 1, cc: 12 }, { kind: "on", b: 9, mode: "toggle" }, null, "c");      // the control taught again
  assert.deepEqual(m.map((x) => x.id), ["c"]);
  m = learn(m, { ch: 1, cc: 12 }, { kind: "param", b: 10, k: 2 }, 4, "d");               // the same control, for preset 05 only
  assert.deepEqual(m.map((x) => x.id), ["c", "d"]);
  assert.deepEqual(resolve(m, { ch: 1, cc: 12 }, 4).map((x) => x.id), ["d"], "the preset's own wins in that preset");
  assert.deepEqual(resolve(m, { ch: 1, cc: 12 }, 3).map((x) => x.id), ["c"]);
  assert.deepEqual(resolve(m, { ch: 2, cc: 12 }, 3), [], "another channel is another control");
});
await check("what a learned control does: settings, switches (flip or follow), types, preset steps", () => {
  const ctx = { on: (b) => b === 9, ntypes: () => 8 };
  assert.deepEqual(action({ tgt: { kind: "param", b: 5, k: 1 } }, 127, ctx), { do: "param", b: 5, k: 1, v: 100 });
  assert.deepEqual(action({ tgt: { kind: "on", b: 9, mode: "toggle" } }, 127, ctx), { do: "on", b: 9, v: 0 });
  assert.equal(action({ tgt: { kind: "on", b: 9, mode: "toggle" } }, 0, ctx), null, "the release of a footswitch does nothing");
  assert.deepEqual(action({ tgt: { kind: "on", b: 9, mode: "follow" } }, 0, ctx), { do: "on", b: 9, v: 0 });
  assert.deepEqual(action({ tgt: { kind: "on", b: 2, mode: "follow" } }, 64, ctx), { do: "on", b: 2, v: 1 });
  assert.deepEqual(action({ tgt: { kind: "type", b: 9 } }, 127, ctx), { do: "type", b: 9, t: 7 });
  assert.deepEqual(action({ tgt: { kind: "preset", step: -1 } }, 100, ctx), { do: "preset", step: -1 });
  assert.equal(action({ tgt: { kind: "preset", step: 1 } }, 10, ctx), null);
});
await check("stored controls that are not well formed are dropped", () => {
  const good = { id: "a", src: { ch: 1, cc: 11 }, tgt: { kind: "param", b: 5, k: 1 }, slot: null };
  const list = [good, { src: { ch: 0, cc: 11 }, tgt: good.tgt, slot: null }, { src: good.src, tgt: { kind: "param", b: 12, k: 0 }, slot: null },
    { src: good.src, tgt: { kind: "on", b: 1 }, slot: null }, { src: good.src, tgt: { kind: "preset", step: 2 }, slot: null }, null, "x"];
  assert.deepEqual(cleanMappings(list), [good]);
  assert.deepEqual(cleanMappings("nonsense"), []);
});

// ---- a Chocolate ----
await check("Bluetooth MIDI packets are read as the pedal reads them (the packets of midisim.c)", () => {
  const s = { sysex: false }, read = (...p) => parsePacket(s, Uint8Array.from(p));
  assert.deepEqual(read(0x80, 0x8E, 0xB1, 0x00, 0x7F), [[0xB1, 0, 127]], "the Chocolate Plus, footswitch A, as captured");
  assert.deepEqual(decode(read(0x80, 0x8E, 0xB1, 0x00, 0x7F)[0]), { type: "cc", ch: 2, cc: 0, value: 127 });
  assert.deepEqual(read(0x80, 0x81, 0xC2, 0x05), [[0xC2, 5]], "Program Change has one data byte");
  assert.deepEqual(read(0x93, 0xA0, 0xB0, 24, 127, 0xA1, 0xC0, 3), [[0xB0, 24, 127], [0xC0, 3]], "two messages in one packet");
  assert.deepEqual(read(0x80, 0x80, 0xB0, 24, 127, 25, 0, 0x85, 26, 64), [[0xB0, 24, 127], [0xB0, 25, 0], [0xB0, 26, 64]], "running status, with and without a timestamp");
  assert.deepEqual(read(0x80, 0x80, 0xB0, 24, 127, 0x81, 0xF8, 0x82, 25, 1), [[0xB0, 24, 127], [0xF8], [0xB0, 25, 1]], "a clock between messages keeps the running status");
  assert.deepEqual(read(0x00, 0x80, 0xB0, 24, 127), [], "no header bit: not a packet");
  assert.deepEqual(read(0x80, 0x80, 0xB0, 24), [], "a message cut short is dropped");
  assert.deepEqual(read(0x80), []); assert.deepEqual(read(), []);
  assert.deepEqual(read(0x80, 24, 127), [], "running status does not reach over from the last packet");
  assert.deepEqual(read(0x80, 0x80, 0xF0, 1, 2, 3), []); assert.equal(s.sysex, true, "SysEx is skipped");
  assert.deepEqual(read(0x80, 4, 5, 0x81, 0xF7, 0x82, 0xB0, 24, 127), [[0xB0, 24, 127]], "a SysEx over two packets ends, and what follows counts");
  assert.equal(s.sysex, false);
  assert.deepEqual(read(0x80, 0x80, 0xF3, 7, 0x81, 0xB0, 24, 1), [[0xB0, 24, 1]], "system common messages are skipped with their data");
});
await check("the Chocolate models: known by name, and each one's data holds together", () => {
  assert.equal(modelFor("FootCtrlPlus").id, "plus");
  assert.equal(modelFor("FootCtrlPlus Bluetooth").id, "plus");
  assert.equal(modelFor("FootCtrl").id, "chocolate");
  assert.equal(modelFor("M-VAVE Chocolate Plus").id, "plus");
  assert.equal(modelFor("Foot Controller"), null, "another foot controller is not a Chocolate");
  assert.equal(modelFor(undefined), null);
  assert.equal(modelById("nonsense"), MODELS[0]);
  assert.equal(modelFor("Chocolate Plus").id, "plus", "the name its manual gives");
  assert.deepEqual(prefixes(), ["FootCtrlPlus", "Chocolate Plus", "FootCtrl", "Chocolate"]);
  for (const m of MODELS) {
    const ids = m.controls.map((c) => c.id);
    assert.equal(new Set(ids).size, ids.length, `${m.name}: a control id twice`);
    for (const n of m.names) assert.ok(modelFor(n) === m, `${m.name}: its own name ${n} is not known as it`);
    for (const id of [...Object.keys(m.sends), ...Object.keys(m.does)]) assert.ok(ids.includes(id), `${m.name}: ${id} is no control`);
    const sent = Object.values(m.sends).map((x) => srcText(x.src));
    assert.equal(new Set(sent).size, sent.length, `${m.name}: two controls send the same message`);
    // the defaults are what the browser may keep: cleaning them changes nothing
    assert.deepEqual(cleanConfig({ model: m.id, profiles: { [m.id]: defaultProfile(m) } }).profiles[m.id], defaultProfile(m));
    assert.ok(m.controls.some((c) => c.kind === "switch") && m.known);
  }
});
await check("a Chocolate's controls: the model's own messages, a control taught, and one message for one control", () => {
  const m = modelById("chocolate"), cc = (n, value, ch = 1) => ({ type: "cc", ch, cc: n, value });
  let p = defaultProfile(m);
  assert.equal(controlFor(m, p, cc(20, 127, 5)), "A", "the model's own message, on any channel");
  assert.equal(controlFor(m, p, cc(25, 0)), "CD");
  assert.equal(controlFor(m, p, cc(11, 64)), null);
  assert.equal(controlFor(m, p, { type: "clock" }), null);
  assert.deepEqual(binding(m, p, "EXP"), { src: null, press: "high", taught: false }, "nothing is known of the pedal");
  p = teach(p, "EXP", msgSrc(cc(11, 64)), "high");
  assert.equal(controlFor(m, p, cc(11, 3)), "EXP");
  assert.equal(controlFor(m, p, cc(11, 3, 2)), null, "a taught control is on its channel");
  p = teach(p, "B", msgSrc(cc(20, 127)), "any");                 // B sends what the model says A sends
  assert.equal(controlFor(m, p, cc(20, 127)), "B");
  assert.equal(binding(m, p, "A").src, null, "A's own message was taken: A has to be taught");
  p = teach(p, "C", msgSrc(cc(20, 127)), "high");                // and now C does
  assert.equal(controlFor(m, p, cc(20, 127)), "C");
  assert.equal(p.B.src, null);
  assert.deepEqual(msgSrc({ type: "pc", ch: 3, program: 7 }), { type: "pc", ch: 3, n: 7 });
  assert.equal(srcText(msgSrc({ type: "noteoff", ch: 1, note: 60, value: 0 })), "Note 60 · ch 1");
  assert.equal(srcText({ type: "cc", ch: 0, n: 20 }), "CC 20");
});
await check("what a Chocolate's control does: a press, not its release; one message a press; the pedal's sweep", () => {
  const m = modelById("chocolate"), ctx = { on: (b) => b === 9, ntypes: () => 8 }, sw = m.controls[0], exp = m.controls.find((c) => c.kind === "pedal");
  const cc = (value) => ({ type: "cc", ch: 1, cc: 20, value }), high = { press: "high" }, any = { press: "any" };
  assert.deepEqual(act(sw, high, m.does.A, cc(127), ctx), { do: "on", b: 4, v: 1 }, "A switches DRIVE");
  assert.deepEqual(act(sw, high, m.does.C, cc(127), ctx), { do: "on", b: 9, v: 0 }, "C switches DELAY, which is on");
  assert.equal(act(sw, high, m.does.A, cc(0), ctx), null, "the release does nothing");
  assert.deepEqual(act(sw, any, m.does.A, cc(0), ctx), { do: "on", b: 4, v: 1 }, "a switch that sends one message per press: a 0 is a press too");
  assert.deepEqual(act(sw, high, m.does.CD, cc(127), ctx), { do: "preset", step: 1 });
  const cd = m.controls.find((c) => c.id === "CD"), p0 = defaultProfile(m);
  assert.deepEqual(act(cd, binding(m, p0, "CD"), m.does.CD, { type: "cc", ch: 1, cc: 25, value: 0 }, ctx), { do: "preset", step: 1 }, "C + D sends one 0 when pressed: that is the press");
  assert.deepEqual(act(sw, high, { kind: "slot", slot: 7 }, { type: "pc", ch: 1, program: 3 }, ctx), { do: "slot", slot: 7 }, "a Program Change is a press");
  assert.deepEqual(act(sw, high, { kind: "tap" }, { type: "note", ch: 1, note: 60, value: 90 }, ctx), { do: "tap" });
  assert.equal(act(sw, high, { kind: "tap" }, { type: "noteoff", ch: 1, note: 60, value: 0 }, ctx), null);
  assert.equal(act(sw, high, null, cc(127), ctx), null, "nothing to do");
  assert.deepEqual(act(exp, high, { kind: "param", b: 5, k: 1 }, cc(32), ctx), { do: "param", b: 5, k: 1, v: 25 }, "the pedal sets a setting as the pedal scales it");
  let p = assign(defaultProfile(m), "A", { kind: "tap" });
  assert.deepEqual(p.A.tgt, { kind: "tap" }); assert.deepEqual(p.B.tgt, m.does.B);
  for (const t of [null, { kind: "on", b: 11, mode: "toggle" }, { kind: "preset", step: -1 }, { kind: "slot", slot: 51 }, { kind: "tap" }, { kind: "param", b: 9, k: 4 }]) assert.deepEqual(keyTgt(tgtKey(t)), t);
});
await check("a kept Chocolate mapping that is not well formed falls back to the defaults", () => {
  const m = modelById("plus"), d = defaultProfile(m);
  assert.deepEqual(cleanConfig(null), { model: MODELS[0].id, profiles: Object.fromEntries(MODELS.map((x) => [x.id, defaultProfile(x)])) });
  const c = cleanConfig({ model: "chocolate", profiles: { plus: {
    A: { src: { type: "cc", ch: 2, n: 0 }, press: "any", tgt: { kind: "slot", slot: 3 } },
    B: { src: { type: "sysex", ch: 1, n: 1 }, press: "odd", tgt: { kind: "on", b: 12 } },
    C: "x", EXP: { src: null, tgt: { kind: "tap" } }, Z: { tgt: { kind: "tap" } } } } });
  assert.equal(c.model, "chocolate");
  assert.deepEqual(c.profiles.plus.A, { src: { type: "cc", ch: 2, n: 0 }, press: "any", tgt: { kind: "slot", slot: 3 } });
  assert.deepEqual(c.profiles.plus.B, { src: null, press: "high", tgt: null }, "a source and a target that cannot be: none");
  assert.deepEqual(c.profiles.plus.C, d.C);
  assert.equal(c.profiles.plus.EXP.tgt, null, "a pedal sets a setting and nothing else");
  assert.equal(c.profiles.plus.Z, undefined);
  assert.deepEqual(c.profiles.chocolate, defaultProfile(modelById("chocolate")));
});
await check("tap tempo: the mean of the last taps, and the delay time the pedal has nearest to it", () => {
  let t = tap([], 1000);
  assert.deepEqual(t, { taps: [1000], ms: null }, "one tap is no tempo");
  t = tap(t.taps, 1500); assert.equal(t.ms, 500);
  t = tap(t.taps, 2020); assert.equal(t.ms, 510);
  t = tap(tap(t.taps, 2500).taps, 3000); assert.deepEqual(t.taps, [1500, 2020, 2500, 3000]);
  assert.equal(tap(t.taps, 3000 + TAP_MAX + 1).ms, null, "after a pause the count starts again");
  assert.equal(tap([1000], 1050).ms, null, "a bounce is no tempo");
  const texts = Array.from({ length: 101 }, (_, v) => `${Math.round(v <= 80 ? 20 + v * 12.25 : 1000 + (v - 80) * 50)} MS`);   // px_dsp.c dly_ms
  assert.equal(timeValue(texts, 500), 39); assert.equal(timeValue(texts, 2000), 100); assert.equal(timeValue(texts, 1), 0);
  assert.equal(timeValue(["A", "B"], 500), -1); assert.equal(timeValue(null, 500), -1);
});

// ---- slots ----
await check("MODEL and IR knobs: the engine's rule (v * n / 101), the knob at the middle of its span", () => {
  for (const n of [28, 8]) {
    for (let v = 0; v <= 100; v++) assert.equal(knobIndex(v, n), Math.floor(v * n / 101));
    for (let i = 0; i < n; i++) {
      const k = indexKnob(i, n);
      assert.equal(knobIndex(k, n), i);
      const span = Array.from({ length: 101 }, (_, v) => v).filter((v) => knobIndex(v, n) === i);
      assert.equal(k, (span[0] + span[span.length - 1]) >> 1);
    }
  }
  assert.equal(knobIndex(200, 28), 27); assert.equal(knobIndex(-3, 28), 0);
});
const cat = { blocks: [{ label: "GT", types: [{ name: "NOISE GATE" }] }, { label: "AMP", types: [{ name: "TWIN" }, { name: "NAM" }] }, { label: "CAB", types: [{ name: "4x12" }, { name: "USER IR" }] }] };
const preset = (ampType, model, cabType = 0, ir = 0) => ({ name: "P", on: [1, 1, 1], type: [0, ampType, cabType], p: [[0, 0, 0, 0, 0], [model, 50, 50, 50, 50], [ir, 0, 0, 0, 0]], order: [0, 1, 2] });
await check("which slot a preset plays, which presets play a slot, and a preset following its slot", () => {
  const nam = slotRef(cat, "nam", 12, 16), ir = slotRef(cat, "ir", 0, 8);
  assert.deepEqual([nam.b, nam.t, nam.n], [1, 1, 28]);
  assert.equal(slotRef({ blocks: [{ label: "AMP", types: [{ name: "TWIN" }] }] }, "nam", 12, 16), null, "a firmware without NAM");
  const u3 = preset(1, indexKnob(12 + 3, 28));
  assert.equal(presetSlot(u3, nam), 3);
  assert.equal(presetSlot(preset(1, indexKnob(4, 28)), nam), -8, "a factory model is no user slot");
  assert.equal(presetSlot(preset(0, indexKnob(15, 28)), nam), -1, "another amp type plays no model");
  assert.equal(presetSlot(preset(0, 0, 1, indexKnob(5, 8)), ir), 5);
  const bank = [{ saved: true, preset: u3 }, { saved: false, preset: u3 }, undefined, { saved: true, preset: preset(1, indexKnob(12, 28)) }, { saved: true, preset: u3 }];
  assert.deepEqual([...usage(bank, nam)], [[3, [0, 4]], [0, [3]]], "saved presets only; holes are skipped");
  const moved = retarget(u3, nam, new Map([[3, 0]]));
  assert.equal(presetSlot(moved, nam), 0);
  assert.equal(u3.p[1][0], indexKnob(15, 28), "the original is not touched");
  assert.equal(retarget(u3, nam, new Map([[5, 0]])), null);
});
await check("a stored file's name: read, cleaned, changed without touching its data", () => {
  const b = new Uint8Array(96); b.set([..."PLEXI LEAD"].map((c) => c.charCodeAt(0)), 8); b[70] = 9;
  assert.equal(packedName(b), "PLEXI LEAD");
  assert.equal(cleanSlotName("  my plexi é lead long "), "MY PLEXI ?");
  const r = renamePacked(b, "My Twin");
  assert.equal(packedName(r), "MY TWIN"); assert.equal(r[70], 9); assert.equal(r[18], 0);
  assert.equal(packedName(b), "PLEXI LEAD");
});
await check("the library (in memory here): no duplicate of the same data, links to the pedal's slots", async () => {
  const lib = await Library.open({});
  assert.equal(lib.persistent, false);
  const bytes = (seed) => { const b = new Uint8Array(96); b[64] = seed; return b; };
  const a = await lib.add({ kind: "nam", name: "ONE", bytes: bytes(1), source: { from: "file", file: "one.nam" } });
  const twin = await lib.add({ kind: "nam", name: "ONE AGAIN", bytes: bytes(1), source: { from: "file", file: "copy.nam" } });
  assert.equal(twin.id, a.id);
  const b = await lib.add({ kind: "nam", name: "TWO", bytes: bytes(2) });
  await lib.add({ kind: "ir", name: "CAB", bytes: bytes(3) });
  assert.deepEqual((await lib.all("nam")).map((e) => e.name), ["ONE", "TWO"]);
  lib.setLink("PocketX", "nam", 0, a.id); lib.setLink("PocketX", "nam", 2, b.id); lib.setLink("PocketX", "nam", 5, "gone");
  const held = await lib.onPedal("PocketX", "nam", [{ slot: 0, used: true, name: "ONE" }, { slot: 2, used: true, name: "RENAMED" }, { slot: 5, used: true, name: "X" }, { slot: 6, used: false, name: "" }]);
  assert.deepEqual([...held.keys()], [0], "a slot that no longer reads the entry's name is not that entry any more");
  assert.deepEqual(lib.links("PocketX", "nam"), { 0: a.id });
  assert.deepEqual(lib.links("BlackBox", "nam"), {});
  await lib.remove(a.id);
  assert.equal(await lib.get(a.id), null);
  assert.equal(pedalKey("PocketX_940"), "PocketX");
});
await check("moving a slot's file: to an empty slot, two changing places, and what cannot move", () => {
  const A = { id: "a" }, B = { id: "b" }, held = new Map([[0, A], [1, B]]), used = (s) => s === 0 || s === 1 || s === 2;
  let p = planMove(0, 4, held, used);
  assert.deepEqual(p.writes, [[4, A], [0, null]]); assert.deepEqual([...p.map], [[0, 4]]);
  p = planMove(0, 1, held, used);
  assert.deepEqual(p.writes, [[1, A], [0, B]]); assert.deepEqual([...p.map], [[0, 1], [1, 0]]);
  assert.ok(planMove(2, 4, held, used).error, "a file the library does not hold cannot move");
  assert.ok(planMove(0, 2, held, used).error, "nor change places with one it does not hold");
  assert.deepEqual(planMove(0, 0, held, used).writes, []);
});
// ---- TONE3000 (docs/pxt3k.js): what the editor's tab keeps for t3k.html when no second window opens ----
{
  if (!globalThis.crypto) globalThis.crypto = webcrypto;
  const store = new Map();
  globalThis.sessionStorage = { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => { store.set(k, String(v)); }, removeItem: (k) => { store.delete(k); } };
  const at = (href) => { const u = new URL(href); globalThis.location = { href: u.href, origin: u.origin, pathname: u.pathname, assigned: null, assign(x) { this.assigned = x; } }; };
  const EDITOR = "https://isod89.github.io/openpocket/editor.html#models";
  at(EDITOR);
  const t = await import("../docs/pxt3k.js");
  const KEY = t.T3K_CLIENT_ID;
  const ask = (o) => sessionStorage.setItem("openpocket-t3k", JSON.stringify({ state: "S1", verifier: "V1", client: KEY, back: EDITOR, at: Date.now(), ...o }));
  await check("TONE3000 in this tab: the Select page with the project's key, the S256 of the verifier kept", async () => {
    await t.t3kSelectHere(EDITOR);
    const u = new URL(location.assigned), p = JSON.parse(sessionStorage.getItem("openpocket-t3k"));
    assert.equal(u.origin + u.pathname, "https://www.tone3000.com/api/v1/oauth/authorize");
    assert.equal(u.searchParams.get("client_id"), KEY);
    assert.equal(u.searchParams.get("redirect_uri"), "https://isod89.github.io/openpocket/t3k.html", "the same redirect as the pop-up's");
    assert.equal(u.searchParams.get("prompt"), "select_tone");
    assert.equal(u.searchParams.get("state"), p.state);
    assert.equal(u.searchParams.get("code_challenge_method"), "S256");
    const s256 = Buffer.from(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(p.verifier))).toString("base64url");
    assert.equal(u.searchParams.get("code_challenge"), s256);
    assert.equal(p.client, KEY);
    assert.equal(p.back, EDITOR);
  });
  await check("t3k.html in that tab: the answer checked against the request, which is used once", () => {
    const p = JSON.parse(sessionStorage.getItem("openpocket-t3k"));
    at("https://isod89.github.io/openpocket/t3k.html");
    assert.deepEqual(t.t3kHere({ code: "C", state: p.state, tone_id: "42" }), { code: "C", tone_id: "42", verifier: p.verifier, client: KEY, back: EDITOR });
    assert.equal(sessionStorage.getItem("openpocket-t3k"), null);
    assert.equal(t.t3kHere({ code: "C", state: p.state, tone_id: "42" }), null, "no request: the page was opened some other way");
  });
  await check("t3k.html: a wrong state, an old request, a cancel, no tone: nothing signed in, back to the editor", () => {
    ask(); assert.match(t.t3kHere({ code: "C", state: "S2", tone_id: "42" }).error, /did not send/);
    assert.equal(sessionStorage.getItem("openpocket-t3k"), null, "a wrong state uses the request up too");
    ask({ at: Date.now() - 31 * 60000 }); assert.match(t.t3kHere({ code: "C", state: "S1", tone_id: "42" }).error, /old one/);
    ask(); assert.equal(t.t3kHere({ state: "S1", error: "access_denied" }).error, "cancelled");
    ask(); assert.equal(t.t3kHere({ code: "C", state: "S1", canceled: "true" }).error, "cancelled");
    ask(); assert.equal(t.t3kHere({ state: "S1" }).error, "no tone was chosen");
    ask(); assert.equal(t.t3kHere({ state: "S1", error: "server_error" }).error, "TONE3000: server_error");
    ask({ back: "https://example.com/x" }); assert.equal(t.t3kHere({ code: "C", state: "S1", tone_id: "1" }).back, EDITOR, "back only to this site");
    ask({ verifier: 7 }); assert.equal(t.t3kHere({ code: "C", state: "S1", tone_id: "1" }), null, "a damaged request is no request");
  });
  await check("t3k.html's note to the editor: read once", () => {
    t.t3kNote({ captures: [{ name: "PLEXI", bytes: "AA==", detail: "", source: { from: "tone3000" } }] });
    assert.equal(t.t3kNoteRead().captures[0].name, "PLEXI");
    assert.equal(t.t3kNoteRead(), null);
  });
}
console.log("editor logic test passed");
