# Neural amp models (NAM A2) on the pedal (v37)

The AMP block plays a [Neural Amp Modeler](https://www.neuralampmodeler.com/) network (v37). Its one type is **NAM**:
the amps built from circuit stages that came before it were removed in store format 6
([SOUNDS-AND-CONTROLS.md](SOUNDS-AND-CONTROLS.md) says what happens to the presets that used them). It plays the
networks of NAM's **A2** architecture, at its 3-channel size, **A2-Lite**. That is the size the pedal's CPU can run.

## The knobs

| Knob | What it does |
| --- | --- |
| MODEL | which network: the 12 factory models, then the 16 user slots (`U1 EMPTY` ... until you load one) |
| GAIN | the level into the network, ±12 dB around the level of the captures (noon) |
| BASS, MID, TREBLE | an EQ after the network: ±10 dB at 120 Hz, ±8 dB at 800 Hz, ±10 dB above 2.5 kHz |

Four factory models (the TM26 and JRT ones) are amps without a cabinet: keep a CAB after the AMP and load a cabinet IR
into it (the editor's **Models** section; the factory presets play slot IR1, which holds the factory IR until you load
one there). The other eight are captures of an amp and its cabinet together, which need no CAB: switch the block off,
as the factory presets that use them do. Every model plays at the same loudness (-20 LUFS on the reference clip
`docs/nam_di.wav`), so switching models keeps the volume.

## Factory models

Twelve NAM A2 captures published on [TONE3000](https://www.tone3000.com/), shipped inside the firmware with their
authors' written permission. The pedal plays each one's A2-Lite part as it is: nothing is retrained. They were made at
48 kHz. `tools/nam_factory.txt` names each capture file with its SHA-256, and `tools/mk_nam_factory.py` writes them into
`firmware/apps/gamut/engine/px_nam_factory.h` the way the editor imports a capture: scaled into the pedal's fixed-point
range where needed (the output stays exactly the same), and levelled.

ESR is how far the A2-Lite part the pedal plays is from the capture's own A2-Full network, on the DI clip at 48 kHz
(`tests/rate48/amps.py`): 0.01 is very close, and below about 0.05 the two are hard to tell apart.

| MODEL | Amp, setting | Cabinet | Capture (author) | ESR |
| --- | --- | --- | --- | --- |
| SUPER 65 | Fender Super Reverb 1965, edge of breakup | in the capture | FNDR BFSR VB Edge WRM2 CAB FREE (amalgamaudio) | 0.034 |
| AC30 TB | Vox AC30 Top Boost 1964, edge of breakup | in the capture | VX TB30 BR Edge0 BAL2 CAB FREE (amalgamaudio) | 0.028 |
| TM26 GRN | Bogner TM 26, Green channel: clean | CAB block | Bogner Green 1 TM 26 (torcuato) | 0.005 |
| TM26 PLX | Bogner TM 26, Plexi Red: low gain | CAB block | Bogner Plexi Red 1 TM 26 (torcuato) | 0.005 |
| TM26 BLU | Bogner TM 26, Blue: crunch | CAB block | Bogner Blue 1 TM 26 (torcuato) | 0.014 |
| TM26 RED | Bogner TM 26, Red: lead | CAB block | Bogner Red 1 TM 26 (torcuato) | 0.021 |
| SLO 100 | Soldano SLO-100, lead | in the capture | Soldano high gain, "SLO-100 Classic" (subterraneans) | 0.008 |
| SLO RIFF | Soldano SLO-100, rhythm | in the capture | Soldano Riff Machine (subterraneans) | 0.036 |
| DT MIDS | Orange Dual Terror, unboosted, mids | in the capture | unboosted dual terror (mids) full rig (chuggernautxanner) | 0.011 |
| DT SCOOP | Orange Dual Terror, boosted, scooped | in the capture | boosted dual terror (scoop) full rig (chuggernautxanner) | 0.022 |
| JRT GN 5 | Orange Jim Root Terror, gain 5 | CAB block | CavLabs #4 - Gain 5 (caveraolabs) | 0.045 |
| JRT GN 7 | Orange Jim Root Terror, gain 7 | CAB block | CavLabs #4 - Gain 7 (caveraolabs) | 0.043 |

The factory presets use them. Until this set, the factory models were twelve networks trained at 44.1 kHz on community
captures (TWIN, AC15, SUPER 59, SHIRL CL, JCM900, SHIRLEY, JCM2000, MARK IV, JVM OD2, PRO MOD, 5150, 6505 RED). A saved
preset keeps its MODEL number, so a preset you saved with one of them now plays the model in the same place of the
list above, and may need its knobs and its CAB block set again.

### Credits

The authors of the TONE3000 captures the factory models are, who gave written permission for them to ship inside the
firmware. The editor lists the same credits in its pedal panel (the connection button, top right), from
`CAPTURE_CREDITS` in `docs/pxnam.js`.

| Author | Pack | Terms |
| --- | --- | --- |
| subterraneans | [Soldano SLO-100](https://www.tone3000.com/tones/soldano-slo-100-106781) | captured with permission, available on TONE3000 |
| chuggernautxanner | [Orange Dual Terror full rig](https://www.tone3000.com/tones/orange-dual-terror-full-rig-boostedunboosted-81959) | captured with permission, available on TONE3000 |
| torcuato | [Bogner TM 26](https://www.tone3000.com/tones/bogner-tm-26-no-cab-109210) | captured with permission, available on TONE3000 |
| amalgamaudio | [Fender Super Reverb 1965 edge of breakup A2](https://www.tone3000.com/tones/fender-super-reverb-1965-edge-of-breakup-a2-88775) | captured with permission, available on TONE3000 |
| amalgamaudio | [Vox AC30 1964 edge of breakup A2](https://www.tone3000.com/tones/1964-vox-ac30-top-boost-super-twin-edge-of-breakup-a2-82521) | captured with permission, available on TONE3000 |
| caveraolabs | [CavLabs #4 Orange Jim Root Terror](https://www.tone3000.com/tones/cavlabs-4-orange-jim-root-terror-24650) | captured with permission, available on TONE3000 |

## Your own models (TONE3000 and others)

1. Get a capture in the **A2** format: on [TONE3000](https://www.tone3000.com/) and in NAM's own trainer, A2 files
   are offered beside the older formats. The pedal reads the A2-Lite part of an A2 file. The older A1 files
   ("standard", "lite", "feather", "nano") do not run on the pedal and are refused with that reason.
2. Open the web editor (`editor.html`), connect the pedal, and in **Models** press **Add .nam files** (several at once,
   or drop them on the panel). The editor checks each file, measures its level and sends it to the next free slot
   (about 2 seconds each; the sound mutes a moment while the flash is written). A file the pedal cannot play is listed
   with the reason. A capture whose values inside the network would pass the pedal's fixed-point range (±2,048) at
   GAIN +12 dB is scaled inside on the way: its output stays exactly the same (`fitRange` in `docs/pxnam.js`). An empty slot's own button loads a file into that slot.
3. In a preset, choose the capture in the AMP block's **MODEL** (your captures are listed by slot).

Or press **Browse TONE3000** in the same section: TONE3000's own tone browser opens in a pop-up (sign in there; it shows
A2 captures only), and the chosen tone comes back with its creator, its description and its A2 models; **Get** puts one
into the slot chosen beside it. While signed in, the editor also lists your TONE3000 favorites and downloads, and the
trending and latest tones. This uses TONE3000's public API ([tone3000.com/api](https://www.tone3000.com/api)), its
"Select" flow and the lists a free application may read (not its search, which stays in TONE3000's own browser):
OAuth 2.0 with PKCE and OpenPocket's publishable key (`T3K_CLIENT_ID` in `docs/pxt3k.js`), the sign-in coming back
through `docs/t3k.html`. The access token lives in the page only while it is open. It needs that key and
`https://isod89.github.io/openpocket/t3k.html` registered as a redirect URI in TONE3000's settings.

A browser that opens no second window (an in-app browser such as MIDIWeb, the Web MIDI browser an iPhone needs for
Bluetooth MIDI) takes TONE3000 in the editor's own tab instead, after saying so. The code verifier, the state and the
address to come back to wait in that tab's session storage; `t3k.html` checks the state, signs in, gets the tone's A2
captures (the one there is, or the ones chosen there) ready for the pedal, and goes back to the editor, which puts them
in the library. Connect the pedal and send them from there. The token stays in `t3k.html`'s memory and ends with it, and
the redirect URI is the same `t3k.html`, so the same registration serves both ways.

**The library.** The pedal stores a capture but cannot send it back. So the editor keeps every capture you add in the
browser (IndexedDB, on that computer only), with where it came from. That is what lets it rename a capture, move it to
another slot or swap two (the presets that use them are rewritten to follow), and keep more captures than the pedal has
slots: **Remove from the pedal** leaves the capture in the library, **Send to the pedal** brings it back. A capture
loaded from another browser shows as "not in this browser's library": load its file again to rename or move it.
Each slot shows how many saved presets use it, and removing a capture names them first.

The 16 user slots are in the pedal's flash at 0xC0000..0xE0000, outside the area a firmware update rewrites: your
models stay through updates.

Most captures are made at 48 kHz, the rate the pedal runs at, so they play as they were captured; the factory models
are 48 kHz captures too. A capture made at 44.1 kHz plays with its tone about 1.5 semitones higher (the amp's filters
sit 9% higher), and the editor says so when it loads one. A pedal whose 48 kHz clock was refused runs at 44.1 kHz
([RATE48-TEST.md](RATE48-TEST.md)): there the 48 kHz captures sit 1.5 semitones lower.

## How it runs

- `firmware/apps/gamut/engine/px_nam.c`: the network in fixed point (activations with 20 fraction bits, weights with 24, 64-bit sums),
  checked against a float reference (`tools/nam_a2.py`) for every factory model by `firmware/apps/gamut/tests/test_nam.py`: about 99 dB
  signal to error.
- Blocks of 32 frames, layer by layer. On the CPU, each output channel of a layer is computed for 4 frames at a time
  straight from the layer's history ring (`rdot`): for each kernel tap, the 4 frames' 3 channels sit side by side in
  the ring (12 words), so a weight is read once for 4 frames and no input is copied (where a tap's 4 frames wrap
  round the ring, those 12 words are copied first). Then LeakyReLU, the head sum and the residual (`post`). On the
  pedal these are hand-written (pi32v2 assembly: multiply-adds paired with loads, 3 words moved by one instruction,
  no branch per sample), because this CPU has no data cache in front of its RAM and a taken branch costs about 8
  cycles. At start-up they are run against the C versions on a test pattern, and the C versions are used if they
  differ by a single bit. On this CPU a multiply-add paired with the load of the value it needs next waits for it
  (3.2 cycles, against 2.2 without the wait), so the routines for 6, 15 and 16 taps (`rdq`, written by
  `tools/gen_rdq.py`) are unrolled with each value loaded 2 to 4 steps before its use. The start-up timing compares
  them with the first `rdot` and with gathering each frame's inputs into one row first (then the hardware-loop dot
  routine), and keeps the fastest.
- The dot products can also run on the chip's vector unit (in its FFT block: one command computes a row of weights
  against many X rows, beside the CPU; each frame's inputs to the layer are then gathered into one X row). The block
  is cut in two halves, and half B of a layer never needs the next layer's half A: so while the unit computes one
  half, the CPU gathers or posts the other, and may compute the last 4 or 8 frames of a half itself. The unit costs
  about 4.8 cycles a multiply-add on the pedal, about as much as the CPU. Its inputs (the X rows and a copy of the
  weights, 13 KB) sit in seven of the data-cache ways turned into RAM at boot (`firmware/px_cacheram.h`, melodee's
  routine; the data cache only serves the flash), so that it does not read the RAM the CPUs work in; the start-up
  check runs the unit there too, and the ordinary RAM is used if it differs.
- Two cores: frame t of a layer needs only frames t and earlier of the layer before. So CPU1 takes the first 12 or 16
  frames of each 32-frame block through all 23 layers without ever waiting, and CPU0 the rest, waiting before each
  layer until CPU1 has posted the one before (one counter). With a NAM amp in two-core mode the audio block runs on
  CPU0 (in the audio interrupt) as a pipeline (`dsp_pipe` in `firmware/apps/gamut/px_audio.h`, `px_engine_part`): CPU1 first runs
  the effects after the amp on the previous block's network output while CPU0 runs the effects before the amp on this
  block, then both run the network (one block, 2.7 ms, more latency; `firmware/apps/gamut/tests/engine/pipe_test.c` checks it gives the
  one-core output one block later). In the pipeline the roles are the other way round (`pxn_serve`): CPU1 comes to
  the network after its effects, so it takes the last frames of each 32-frame block and waits per layer for CPU0,
  which takes the first frames and never waits, and up to 12 more of them in the first blocks by how late CPU1 came
  in the blocks before. Without a NAM amp the whole block runs on CPU1 as before.
- v40.2: in the pipeline the two cores split the network by layers instead of by frames (`pxn_lp_*`,
  `dsp_lp_run`). CPU0 runs the input and layers 0..s of each 32-frame block and hands it over; CPU1 runs layers s+1..22,
  the head and the output, after the effects after the amp, and goes on after the interrupt until this block's network
  blocks are done (the next interrupt collects it). Every layer runs on whole blocks, so neither core waits for the
  other at every layer, and the head no longer runs on CPU0 alone. A layer of a block runs only after the same layer of
  the block before, and layer s's output goes to a hand-over buffer that CPU1 copies into layer s+1's ring, so s can move
  from one block to the next: it follows the difference between the two cores' times. The output is the one-core output
  bit for bit (`firmware/apps/gamut/tests/engine/lp_test.c`: every model, the split moved at random, the second core's work at random
  moments; the pipeline on every NAM preset; on the pedal a development build checks it with both cores at boot). The
  load shown is the busier core's. The hand-over queue (6 KB) sits in the cache RAM after the vector unit's buffers.
- v40.4: CPU1 works on through the interrupts (`lp_job` is one worker for as long as the layer split is on). Before, its
  job ended with the block's last network block, which CPU0 hands over at the end of its own share: CPU1 idled at the
  start of each block, the next interrupt waited for it, and the two cores' work had to fit one after the other in a
  block (the effects before the amp, CPU0's layers, then one network block on CPU1). A chain could use only about 88 %
  of each core, and after a change of type, order or model, when the interrupt runs block after block to catch up
  with the time it was held off, that wait counted as load and engaged the safety bypass on chains that fit. Now each
  interrupt asks the worker for the effects after the amp; it finishes the network blocks handed over before the
  request first (the effects play their output), runs the effects, and returns to the network. The interrupt waits
  only for the output it sends. The network blocks handed over late in a block are finished during the next one, so
  each core's work may fill its block. The split is set in one step from the two cores' other work as timed (the
  effects before the amp on CPU0, the effects after it and the lanes on CPU1) and the network's parts
  (`pxn_lp_share`); in the first two blocks after a change, before CPU1's work is timed, CPU0 takes as many layers
  as fit in 80 % of its block. CPU1 takes layers over at once; CPU0 takes more only as CPU1 has finished them for the
  blocks before (`pxn_lp_a`), or waits for it once when told to (`pxn_lp_force`: a rise of two layers or more). The
  output does not depend on any of it (`firmware/apps/gamut/tests/engine/lp_test.c`).
- v40.5: CPU0's waits for CPU1 end after a limit. CPU1's worker is one job for as long as the split runs, so the
  limit of `fm1_cpu1_wait` (8 ms, then CPU1 is retired as LATE and CPU0 goes on alone) did not apply to the interrupt's
  waits for it: in `a_lp_post` (its output), in `pxn_lp_a` (the queue full) and in a forced rise (`pxn_lp_wait`). A CPU1
  that stopped without a fault would have held the audio interrupt until the watchdog reset the pedal. These waits now
  end after the same 8 ms (`pxn_lp_clock`, set after the start-up check; none on the PC): `pxn_lp_a` returns without
  handing the block over, CPU1 is retired (LATE), and the next collect goes to one core with the engine reset, as for a
  CPU1 that faults. `firmware/apps/gamut/tests/engine/lp_stuck.c` checks the network's side with a second core that never moves.
- v40.5: `post5` (`tools/gen_rdq.py --post5`) does `post4`'s work two frames a turn for every layer with an output: the
  residual's 9 weights are read once for the two frames, and every load and store is written with an instruction that
  computes (free with a multiply or multiply-add; with a 1-cycle instruction it costs only its own time), each value
  loaded 2 instructions or more before its use. No word outside the job is read. An odd first frame and the last layer
  go to `post4`. A turn takes 109 cycles against 159 for two of `post4`'s frames. `firmware/apps/gamut/tests/test_post5.py` runs the
  assembly text itself through a model of its instructions against the C post, on the PC; the pedal checks it at
  start-up like the others and times it.
- v40.5: `rdm6`, `rdm15` and `post5` run from the flash, the other routines from RAM as before. On this chip code in RAM
  is fetched at about 1.5 cycles a word and code in the instruction cache at 1 cycle a word; these three are rows of
  6-byte instructions that work for 2 cycles each, so from RAM they waited for their own instructions. They are 6.6 KB
  and run all the time, so they stay in the cache. The network takes 6 % less time for it. The Bluetooth test image
  keeps them in RAM (`PXN_HOT_RAM`): its radio code runs from the flash all the time, and that was not measured.
- Each layer's history ring has its first 3 frames mirrored after its end, so 4 frames can be read straight from any
  position: the tap pointers just move on by 4 frames per group. On the pedal a layer's whole block of groups runs in one call
  (`pxn_rdl6/15/16_asm`, generated by `tools/gen_rdq.py --rdl`), its tap table on the stack.
- v40.2: on the pedal a multiply-add costs 2 cycles, and so does a load, unless it is paired with the multiply-add (then
  it is free); an ALU instruction costs 1 (measured). `rdl` reads 5 values for 4 multiply-adds (one weight, 4 frames).
  `rdm` (`tools/gen_rdq.py --rdm`) does a 3-row layer's rows 0 and 1 two frames at a time (2 weights, 2 frames: every load
  paired) and row 2 as `rdl`; `post4` reads the layer's input straight from its ring in a loop with no counter in memory,
  the residual's weights on the stack so that their loads pair, and LeakyReLU as `smax(z, (z * 42949673) >> 32)`, the
  same value for every z (checked over all 2^32). Both are checked against C at start-up like the others and timed against
  them; the start-up check, the timing and the dispatch also run on the PC (`firmware/apps/gamut/tests/engine/hand_test.c`) with C stand-ins
  that read exactly what the hand code reads, under the address sanitizer, so that a check that would fault on the pedal
  (a boot loop) fails there first. `pxn_equiv` runs the whole network with the routines in use against C.
- At start-up the pedal times the ways to run it (CPU alone; the unit one command after the other; the unit and the
  CPU at once, the CPU taking 0, 4 or 8 frames; two cores, with or without the unit) on the first factory model and
  keeps the fastest (`pxn_tune`). The PC test runs every mode with a simulated unit that finishes its commands late,
  at random, and a simulated second core that moves on only while the first waits for it: the output must be exactly
  the CPU's.
- 1,730 multiply-adds per sample in 23 layers; the history buffers take 83 KB of RAM, a model 7.5 KB.
- The load shows at the bottom right of the screen (`C1 nn%`).

## Training (`tools/train_a2.py`)

`train_a2.py --capture CAPTURE.nam --di DI.wav --val DI2.wav --out MODEL.nam --name NAME` trains an A2-Lite network
(JAX) on a capture: the DI goes through the capture (resampled to its rate and back), the A2-Lite learns the result at
44.1 kHz. Loss: pre-emphasised ESR plus a multi-resolution spectral term. It made the factory models before the
TONE3000 captures; the factory set is no longer trained.

Credits: the factory captures' authors are listed above; the DI guitar is from
[Alec-Wright/Automated-GuitarAmpModelling](https://github.com/Alec-Wright/Automated-GuitarAmpModelling) (GNU GPL v3).
The A2 architecture is Steven Atkinson's (Neural Amp Modeler, MIT); the pedal's code is written for Gamut from the
published architecture.
