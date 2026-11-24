// SPDX-License-Identifier: GPL-3.0-only
// Gamut web editor: MIDI over Bluetooth Low Energy, for a controller this page connects to itself (Web Bluetooth). The
// packet reader is the pedal's own (firmware/apps/gamut/px_ble_midi.h), and tests/test_editor_logic.mjs gives both the
// same packets. Here the page is the central: it reads what the controller notifies. No DOM here.

export const MIDI_SERVICE = "03b80e5a-ede8-4b33-a751-6ce34ec4c700";
export const MIDI_CHAR = "7772e5db-3868-4112-a1a9-f2669d106bf3";

// how many data bytes follow a status
const dataLen = (st) => st >= 0xF0 ? (st === 0xF2 ? 2 : st === 0xF1 || st === 0xF3 ? 1 : 0) : (st & 0xE0) === 0xC0 ? 1 : 2;

// one notification -> the MIDI messages in it, each as a MIDI port delivers one. A packet is a header, then for each
// message a timestamp byte and the message; both have bit 7 set. Running status counts, with and without a timestamp.
// SysEx and system common messages are skipped; `s` ({ sysex }) is kept between packets, as SysEx can run over several.
export function parsePacket(s, p) {
  const out = [];
  let i = 1, run = 0;
  if (p.length < 2 || !(p[0] & 0x80)) return out;      // no header: not a BLE MIDI packet
  while (i < p.length) {
    let b = p[i];
    if (s.sysex && !(b & 0x80)) { i++; continue; }
    if (b & 0x80) {                                    // a timestamp, so a status or running-status data follows
      if (++i >= p.length) break;
      b = p[i];
      if (b & 0x80) {
        i++;
        if (b >= 0xF8) { out.push([b]); continue; }    // realtime: running status survives it
        if (s.sysex && b !== 0xF7) s.sysex = false;
        run = 0;
        if (b === 0xF0) s.sysex = true;
        else if (b === 0xF7) s.sysex = false;
        else if (b >= 0xF1) i += dataLen(b);
        else run = b;
        if (!run) continue;
      } else if (s.sysex) continue;
    }
    if (!run) { i++; continue; }                       // data with no status to belong to
    const need = dataLen(run);
    if (i + need > p.length) break;                    // cut short: dropped
    const d1 = p[i], d2 = need > 1 ? p[i + 1] : 0;
    if ((d1 | d2) & 0x80) { run = 0; continue; }       // a status inside a message: drop it and read that byte again
    out.push(need > 1 ? [run, d1, d2] : [run, d1]);
    i += need;
  }
  return out;
}

// the browser's own chooser: every Bluetooth MIDI device in reach, and devices named `prefixes`, for a controller that
// does not put the MIDI service in its advertisement. It needs a click, and the user picks; nothing is scanned unseen.
export const pick = (bluetooth, prefixes) => bluetooth.requestDevice({
  filters: [{ services: [MIDI_SERVICE] }, ...prefixes.map((namePrefix) => ({ namePrefix }))], optionalServices: [MIDI_SERVICE] });

// connect to a picked device and pass on each MIDI message it notifies: onMessage([status, data...]). Called again
// for a device that went away and is back: the handler is set, not added, so a message is never passed on twice.
export async function listen(device, onMessage) {
  const server = await device.gatt.connect();
  const ch = await (await server.getPrimaryService(MIDI_SERVICE)).getCharacteristic(MIDI_CHAR);
  const s = { sysex: false };
  ch.oncharacteristicvaluechanged = (e) => {
    const v = e.target.value;
    for (const m of parsePacket(s, new Uint8Array(v.buffer, v.byteOffset, v.byteLength))) onMessage(m);
  };
  await ch.startNotifications();
}
