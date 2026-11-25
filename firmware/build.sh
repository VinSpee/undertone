#!/bin/sh
# Build Gamut (firmware/apps/gamut/) -> build/apps/gamut/: openpocket.bin (app), PocketX_9NN.fwsc, BlackBox_9NN.fwsc
#   and manifest.json (packages for the web installer), release.json (the catalog)   (in the container: tools/op.mjs build)
# OP_BLE=1 sh firmware/build.sh builds the Bluetooth MIDI test image instead (docs/BLE-TEST.md): the same
#   firmware plus the JieLi controller and host (third_party/jieli-ble) -> firmware/openpocket-ble.bin and build/ble/*.fwsc.
#   Nothing of the normal build's outputs is touched.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
BSP="${BSP:-$HERE/bsp}"
TC="${JIELI_TOOLCHAIN:-$HOME/.jieli/toolchain}"
echo "Toolchain : $TC"
echo "BSP       : $BSP"
if [ ! -x "$TC/pi32v2/bin/clang" ]; then
  echo "ERROR: no JieLi toolchain in $TC"
  echo "  -> it is the one you already use to build CLIPPER."
  echo "  -> run again with:  JIELI_TOOLCHAIN=/path/to/toolchain sh firmware/build.sh"
  exit 1
fi
if [ ! -x "$TC/pi32v2/bin/ld" ]; then
  echo "ERROR: linker '$TC/pi32v2/bin/ld' missing (incomplete toolchain)."
  exit 1
fi
# the stack guard: on, except in the Bluetooth test image (its task stacks are outside the guard window); app.ld refuses the
# link if the guard is on and those stacks are outside. OP_GUARD_STACK=1 with OP_BLE=1 is how that check is shown to fire.
GUARD_STACK=1; [ -n "$OP_BLE" ] && GUARD_STACK="${OP_GUARD_STACK:-0}"
if [ -n "$OP_BLE" ]; then O="$HERE/build-ble"; APP="$HERE/openpocket-ble.bin"; PKG="$HERE/../build/ble"; BLEDEF="-DOP_BLE_TEST=1 -I$HERE/apps/gamut/ble"
else O="$HERE/../build/apps/gamut/obj"; APP="$HERE/../build/apps/gamut/openpocket.bin"; PKG="$HERE/../build/apps/gamut"; BLEDEF=""; fi
# An app on the base firmware (docs/BASE-FIRMWARE.md): OP_APP=<name> builds firmware/apps/<name>/ in place of OpenPocket,
#   into build/apps/<name>/ (the image, its packages). Its app.sh names its C file (APP_MAIN), its engine's when that is
#   a file of its own (APP_ENGINE), their options (APP_DEFS) and the functions that run from RAM beside the base's
#   (APP_RAM_DSP in the engine's file, APP_RAM_FW in the app's); its memory.ld holds its regions (app.ld).
#   Nothing of the OpenPocket build's outputs is touched.
MAIN="$HERE/apps/gamut/openpocket.c"; ENGINE="$HERE/apps/gamut/engine/px_dsp.c"; MEM="$HERE/apps/gamut"
if [ -n "$OP_APP" ]; then
  case "$OP_APP" in *[!a-z0-9-]*) echo "ERROR: OP_APP must be lowercase letters, digits and -"; exit 1;; esac
  [ -z "$OP_BLE$OP_CHANNEL" ] || { echo "ERROR: OP_APP builds an app as it is: not with OP_BLE or OP_CHANNEL"; exit 1; }
  MEM="$HERE/apps/$OP_APP"
  [ -f "$MEM/app.sh" ] || { echo "ERROR: no app.sh in $MEM"; exit 1; }
  APP_ENGINE=""; APP_DEFS=""; APP_RAM_DSP=""; APP_RAM_FW=""
  . "$MEM/app.sh"
  MAIN="$MEM/$APP_MAIN"; ENGINE="${APP_ENGINE:+$MEM/$APP_ENGINE}"
  O="$HERE/../build/apps/$OP_APP/obj"; APP="$HERE/../build/apps/$OP_APP/$OP_APP.bin"; PKG="$HERE/../build/apps/$OP_APP"
  echo "App: $OP_APP -> $APP, $PKG"
fi
MOBJ="$O/$(basename "$MAIN" .c).o"; EOBJ="${ENGINE:+$O/$(basename "$ENGINE" .c).o}"
rm -rf "$O"; mkdir -p "$O"
CC="$TC/pi32v2/bin/clang -target pi32v2"
$CC -c "$BSP/chip/crt0.S"    -o "$O/crt0.o"
$CC -c "$BSP/chip/fm1_vec.S" -o "$O/vec.o"
$CC -c "$BSP/chip/fm1_isr.S" -o "$O/isr.o"
# 2nd core (entry + stacks, Felucca): only if the main C file enables it (#define DSP_CPU1 1)
CPU1OBJ=""
if grep -q "^#define DSP_CPU1 1" "$MAIN"; then
  $CC -c "$BSP/chip/fm1_cpu1.S" -o "$O/cpu1.o"; CPU1OBJ="$O/cpu1.o"
fi
# A test channel build (OP_CHANNEL=midi-test): its own version number (OP_TEST_VERSION, default 37) and a boot-screen tag, its
# own files (build/apps/gamut/openpocket-midi-test.bin, build/apps/gamut/midi-test/). The release files are not touched.
CHAN="${OP_CHANNEL:-}"
ENGINE48=0                                            # 1: the engine built for 48 kHz (px_dsp.h PX_FS) and its memory
: > "$O/channel.h"
if [ -n "$CHAN" ]; then
  case "$CHAN" in *[!a-z0-9-]*|"") echo "ERROR: OP_CHANNEL must be lowercase letters, digits and -"; exit 1;; esac
  TESTVER="${OP_TEST_VERSION:-42}"
  printf '#define OP_VERSION_NUM "%s"\n#define OP_VERSION_TEXT "v%s"\n#define OP_TAG " %s"\n' "$TESTVER" "$TESTVER" "$(echo "$CHAN" | tr a-z- A-Z' ')" > "$O/channel.h"
  # the I2S clock's two test builds (firmware/base/rate.h, docs/RATE48-TEST.md): the report at 44.1 kHz, then 48 kHz guarded
  case "$CHAN" in
    rate-diag) echo '#define OP_RATE_DIAG 1' >> "$O/channel.h";;
    rate48) echo '#define OP_RATE48 1' >> "$O/channel.h"; ENGINE48=1;;
  esac
  APP="$HERE/../build/apps/gamut/openpocket-$CHAN.bin"; PKG="$HERE/../build/apps/gamut/$CHAN"
  rm -f "$APP"
  echo "Test channel: $CHAN, version $TESTVER -> $APP, $PKG"
fi
# AC791N hardware FPU (same options as the JieLi SDK for the WL82); the engine's rate is the I2S's (base/audio.h A_SR)
FP="-mcpu=r3 -mfprev1"
DSPDEF="-DPX_OVERSAMPLE=4"
[ "$ENGINE48" = 1 ] && DSPDEF="$DSPDEF -DPX_FS=48000"
[ -n "$OP_BLE" ] && DSPDEF="$DSPDEF -DPXN_LEAN=1 -DPXN_HOT_RAM=1 -DPX_RUNS=0"   # v40.2: the test image's flash is full (firmware/apps/gamut/engine/px_nam.c; v40.4: px_dsp.c PX_RUNS)
[ -n "$OP_APP" ] && DSPDEF="$APP_DEFS"
INC="-I$HERE -I$HERE/inc -I$HERE/apps/gamut/engine"
$CC $FP -Os -ffunction-sections -fno-builtin -Wall -Wno-unused-function $DSPDEF $BLEDEF -DOP_GUARD_STACK=$GUARD_STACK $INC \
    -I"$BSP/chip" -I"$BSP/boards/fm1" -include "$O/channel.h" -c "$MAIN" -o "$MOBJ"
[ -z "$ENGINE" ] || $CC $FP -O2 -ffunction-sections -fno-builtin $DSPDEF $INC -c "$ENGINE" -o "$EOBJ"
$CC $FP -O2 -fno-builtin -c "$HERE/px_math.c" -o "$O/px_math.o"
BLEOBJ=""; MAPOPT="-Map $O/openpocket.map"   # (the memory report below reads the regions from the map)
if [ -n "$OP_BLE" ]; then
  # JieLi's LE controller (LLVM bitcode, Apache-2.0, third_party/jieli-ble) -> pi32v2 objects, and our context switch
  mkdir -p "$O/jl"
  # the members folded (tools/jlfold.py, from ettorebox): the constants ble_cfg.c and ble_stubs.c define and the empty
  # print helpers become the members' own, so -Os drops the code they switch off and the log strings. As published, the
  # image no longer fits its flash window.
  cat "$HERE/apps/gamut/ble/ble_cfg.c" "$HERE/apps/gamut/ble/ble_stubs.c" > "$O/jlcfg.c"
  python3 "$HERE/../tools/jlfold.py" fold "$TC" "$O/jlcfg.c" "$O/jl" "$HERE"/../third_party/jieli-ble/*/*.bc
  # v40 made memcpy and memset RAM code, out of the call range of the library's code at the end of the flash: the
  # library calls flash copies instead (apps/gamut/ble/ble_libc.c)
  for o in "$O"/jl/*.o; do python3 "$HERE/../tools/elfsym.py" "$o" memcpy=ble_memcpy memset=ble_memset; done
  rm -f "$O/libjl.a"; "$TC/pi32v2/bin/ar" rcs "$O/libjl.a" "$O"/jl/*.o   # an archive: the linker takes only the objects the image calls
  $CC -c "$HERE/apps/gamut/ble/ble_ctx.S" -o "$O/ble_ctx.o"; $CC -c "$HERE/apps/gamut/ble/ble_isr.S" -o "$O/ble_isr.o"; BLEOBJ="$O/ble_ctx.o $O/ble_isr.o $O/libjl.a"
fi
# official JieLi I2S driver (LLVM bitcode from the AC79 SDK, Apache-2.0) -> pi32v2 object
$CC -Os -c -x ir "$HERE/sdk/iis.bc" -o "$O/iis.o"
# v40: the audio path runs from RAM, as the stock firmware's does (no flash fetches through the cache, which the two cores
# share): its functions' sections are renamed .ram_text.dsp.* (tools/ramcode.py; the code itself is unchanged), and the
# linker puts them in the RAM code window (firmware/app.ld). --plain: px_dsp.o's hand-written routines (NAM).
RAM_DSP="px_engine_process px_engine_part px_wet_run px_wet_swap dly_block rv_block rv_front clip_run os_up os_down
  ir_run fft64 rfft128 ps_voice_al ps_align bq_block bq_block2 drive_block nam_run px_nam_dual
  pxn_process pxn_block pxn_direct pxn_post_part pxn_rows pxn_rows_cpu pxn_gather pxn_range_cpu pxn_dual
  px_nam_lp_b px_nam_lp_queued px_nam_lp_split px_nam_lp_split_now pxn_lp_a pxn_lp_b pxn_lp_queued pxn_lp_split
  pxn_lp_split_now pxn_frame_ticks px_nam_lp_handed px_nam_lp_before pxn_lp_handed pxn_lp_before
  px_nam_lp_split_used px_nam_lp_force pxn_lp_split_used pxn_lp_force px_nam_lp_gave_up pxn_lp_gave_up
  ps_voice_run syn_organ_run pitch_run gate_run comp_run bq_chain tr_run dly_wrap"
# v40.2: the layer split's path (pxn_lp_*, lp_job, dsp_lp_run) in RAM; out of it, to make the room: the frame split's serving
# (now the fallback when the layer split cannot run), the vector unit's paths (never chosen: slower) and the C versions
# of the hand routines (used only if a hand one fails its start-up check: the network is then too slow anyway)
RAM_FW="a_enc a_dec a_block a_send a_collect a_commit dsp_block dsp_out dsp_load dsp_job post_job post_run dsp_pipe lp_job dsp_lp_run a_lp_post lp_split
  fm1_alnk0_irq tn_capture fm1_cpu1_run fm1_cpu1_wait fm1_cpu1_retire a_hrun a_hwait b_ticks memcpy memset"
# an app: its own lists, and the base's audio path (base/audio.h, px_aorder.h)
[ -n "$OP_APP" ] && { RAM_DSP="$APP_RAM_DSP"; RAM_FW="a_enc a_dec a_block a_send a_collect a_input a_output dsp_out a_knee dsp_load fm1_alnk0_irq tn_capture memcpy memset $APP_RAM_FW"; }
[ -z "$ENGINE" ] || python3 "$HERE/../tools/ramcode.py" "$EOBJ" --plain $RAM_DSP
python3 "$HERE/../tools/ramcode.py" "$MOBJ" $RAM_FW
# a direct call between the flash code and the RAM code is out of the CPU's call range: refuse it with its name
# (v40: the audio path's RAM code, .ram_text.dsp.*, is within range by its place, firmware/app.ld)
python3 "$HERE/../tools/check_calls.py" "$O/crt0.o" "$O/vec.o" "$O/isr.o" $CPU1OBJ "$MOBJ" $EOBJ "$O/px_math.o"
"$TC/pi32v2/bin/ld" --defsym "op_guard_stack=$GUARD_STACK" --defsym "op_engine48=$ENGINE48" -L "$MEM" -T "$HERE/app.ld" "$O/crt0.o" "$O/vec.o" "$O/isr.o" $CPU1OBJ "$MOBJ" $EOBJ "$O/px_math.o" "$O/iis.o" $BLEOBJ $MAPOPT -o "$O/openpocket.elf"
# symbol map: used to translate a crash address (PC) into a function name
"$TC/common/bin/objdump" -t "$O/openpocket.elf" 2>/dev/null | sort > "$O/symbols.txt" || true
"$TC/common/bin/objcopy" -O binary -j .text     "$O/openpocket.elf" "$O/text.bin"
"$TC/common/bin/objcopy" -O binary -j .data     "$O/openpocket.elf" "$O/data.bin"
"$TC/common/bin/objcopy" -O binary -j .ram_text "$O/openpocket.elf" "$O/rt.bin" 2>/dev/null || : > "$O/rt.bin"
python3 - "$TC" "$O" "$APP" "$OP_APP" <<'PY'
import re,subprocess,sys
tc,out,dest,app=sys.argv[1:]
syms=subprocess.run([f"{tc}/common/bin/objdump","-t",f"{out}/openpocket.elf"],capture_output=True,text=True,check=True).stdout
def sym(n):
    m=re.search(rf"^([0-9a-f]+) .*\s{n}$",syms,re.M); return int(m.group(1),16) if m else None
load=sym("_data_load"); rt_load=sym("_rt_load"); start=sym("_start")
be,cl,ch,nb=sym("_bss_end"),sym("_cram_lo"),sym("_cram_hi"),sym("_ble_stack_hi")
re_,hs,he=sym("_rt_end"),sym("_bss_hi_start"),sym("_bss_hi_end")
ls_,le=sym("_bss_lo_start"),sym("_bss_lo_end")
# the regions as the linker laid them out (app.ld, the app's memory.ld): name -> origin, length
mem=open(f"{out}/openpocket.map").read().split("Memory Configuration")[1].split("Linker script and memory map")[0]
mem={m[1]:(int(m[2],16),int(m[3],16)) for m in re.finditer(r"^(\w+)\s+0x([0-9a-f]+)\s+0x([0-9a-f]+)",mem,re.M)}
(r0,rl),(p0,pl),(t0,tl),(n0,nl)=mem["RAM"],mem["POOL"],mem["RAMTEXT"],mem["NOINIT"]
if ls_ is not None and le and le > ls_: print(f"low RAM   : {le-ls_} of {mem['LOWRAM'][1]} bytes (below the RAM)")
ps_,pe=sym("_pool_tail_start"),sym("_pool_tail_end")
if ps_ and pe: print(f"pool tail : {pe-ps_} bytes, {p0+pl-pe} left before the RAM code")
if re_ and he: print(f"hi RAM    : RAM code {re_-t0}, data {he-hs}, free {t0+tl-he} of {tl} bytes (the RAM code window)")
if be: print(f"RAM       : {be-r0} of {rl} bytes ({rl-(be-r0)} free)")
if nb and nb >= n0 and nb > sym("_ble_stack_lo"): print(f"NOINIT    : {nb-n0} of {nl} bytes up to the BLE task stacks' end")
cr=mem["CRAM"][1]
if cl is not None and ch is not None: print(f"cache RAM : {ch-cl} of {cr} bytes" + ("" if app else f" (the rest, {cr-(ch-cl)}, to the NAM network's vector unit)"))
assert start==0x02000120,hex(start or 0)
img=bytearray(open(f"{out}/text.bin","rb").read())
for at,part in sorted([(rt_load,open(f"{out}/rt.bin","rb").read()),(load,open(f"{out}/data.bin","rb").read())]):
    if part:
        assert at-0x02000120>=len(img),"sections overlap"
        img+=b"\xff"*(at-0x02000120-len(img))+part
img+=b"\xff"*(-len(img)%4)
open(dest,"wb").write(img); print(f"OK -> {app or 'openpocket'}.bin: {len(img)} bytes")
PY

# ---- update loader (loader/, felucca-bsp's, Pocket X layout) -> build/loader/ota.bin ----
L="$O/loader"; mkdir -p "$L"
$CC -c "$HERE/../loader/crt0_ldr.S" -o "$L/crt0_ldr.o"
$CC -Os -ffunction-sections -fno-builtin -Wall -Wno-unused-function -I"$HERE/inc" -I"$BSP/chip" -I"$BSP/boards/fm1" \
    -c "$HERE/../loader/loader.c" -o "$L/loader.o"
"$TC/pi32v2/bin/ld" --gc-sections -e _start -T "$HERE/../loader/loader.ld" "$L/crt0_ldr.o" "$L/loader.o" -o "$L/loader.elf"
"$TC/common/bin/objcopy" -O binary -j .text "$L/loader.elf" "$L/loader.bin"
# the loader rewrites the flash: nothing of it may live in XIP (0x02xxxxxx)
"$TC/common/bin/objdump" -h "$L/loader.elf" | python3 -c '
import sys
for ln in sys.stdin:
    p = ln.split()
    if len(p) > 4 and p[1].startswith(".") and int(p[2], 16) and int(p[3], 16) >= 0x02000000:
        sys.exit("ERROR: loader section " + p[1] + " outside RAM")'

python3 "$HERE/../tools/mkloader.py" "$L/loader.bin" "$L/ota.bin"

# ---- update packages for the web installer -> $PKG (PocketX_9NN.fwsc, BlackBox_9NN.fwsc, manifest.json) ----
VER=$(sed -n 's/^#define OP_VERSION_NUM "\([0-9]*\)".*/\1/p' "$MAIN")
[ -n "$CHAN" ] && VER="$TESTVER"
mkdir -p "$PKG"
# (an app's packages are named after it and its manifest says which product it is: --app; OpenPocket's are as ever)
python3 "$HERE/../tools/pxpkg.py" "$APP" "$L/ota.bin" "$PKG" --version "$VER" \
    --sdk-files "$HERE/sdk/packager" ${OP_APP:+--app "$OP_APP"}
# ---- the catalog of the firmwares that are built -> build/apps/gamut/release.json, for the installer's chooser ----
# (a test channel and the Bluetooth test image are not on it: the page reads their own manifest)
[ -n "$CHAN$OP_BLE" ] || python3 "$HERE/../tools/catalog.py"
