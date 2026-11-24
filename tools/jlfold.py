#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
# JieLi's Bluetooth LE controller library specialised at build time, for the Bluetooth test image (firmware/build.sh,
# OP_BLE). Ported from ettorebox's tools/jlfold.py (Roberto Antonacci, commit 375a253; NOTICE.md).
#
# The library's members (JieLi's LLVM bitcode, third_party/jieli-ble) read their configuration from other files: the
# log switches (log_tag_const_*), config_asser (audio_probe.h), and the controller's const settings
# (firmware/apps/gamut/ble/ble_cfg.c, ble_stubs.c). To the compiler those are external, so it keeps every branch they
# guard and every log string. Folding them: in a text copy of a member's IR, each such external constant becomes an
# internal one with the value the image links anyway (only `const` objects, only when the IR reads them at the width
# the C file defines), and the print helpers the firmware defines empty (printf, log_print: audio_probe.h; puts,
# put_buf, printf_buf: ble/ble_libc.c) become internal and empty, so -Os drops what they guard and their strings. The
# vendor's files are never changed.
#
#   jlfold.py fold TC CFG.c OUTDIR MEMBER.bc...
#     each member through text IR, folded, compiled with -Os into OUTDIR/<archive>_<member>.o, the names build.sh's
#     plain compile gives (build.sh then renames their memcpy / memset and makes libjl.a of them, as before). A failure
#     stops the build.
import os
import re
import subprocess
import sys

# the names ble_cfg.c's initialisers use (the SDK's values)
ENUMS = {"BT_MODULE_CLASSIC": 1, "BT_MODULE_LE": 2, "BT_BTSTACK_CLASSIC": 1, "BT_BTSTACK_LE": 4, "BT_NORMAL": 1,
         "LE_MASTER": 1, "LE_SLAVE": 2, "LE_ADV": 4, "LE_SCAN": 8, "LE_INIT": 16, "BIT": (lambda n: 1 << n)}
CTYPE = {"int": "i32", "unsigned": "i32", "uint32_t": "i32", "int32_t": "i32", "uint16_t": "i16", "int16_t": "i16",
         "uint8_t": "i8", "int8_t": "i8", "char": "i8", "unsigned char": "i8"}

GLOBAL = re.compile(r"^@([\w.$]+) = external((?: (?:hidden|protected|local_unnamed_addr|unnamed_addr))*) constant "
                    r"(i8|i16|i32|i64)(?=[ ,\n])", re.M)
PRINTS = ("printf", "log_print", "puts", "put_buf", "printf_buf")
PRINT = re.compile(r"^declare ((?:[a-z_]+ )*)(void|i32) @(" + "|".join(PRINTS) + r")\((.*)\)[^()\n]*$", re.M)


def cfg_values(path):
    """{name: (IR type, value)}: the const objects the file defines, its log switches, and config_asser."""
    src = re.sub(r"/\*.*?\*/", " ", open(path).read(), flags=re.S)
    v = {}
    for m in re.finditer(r"^[ \t]*const[ \t]+(unsigned[ \t]+char|\w+)[ \t]+(\w+)[ \t]*=[ \t]*([^;,{]+);", src, re.M):
        ty = CTYPE.get(re.sub(r"\s+", " ", m.group(1)))
        if not ty:
            continue
        expr = re.sub(r"\b(0x[0-9a-fA-F]+|\d+)[uUlL]+\b", r"\1", m.group(3).strip())
        v[m.group(2)] = (ty, int(eval(expr, {"__builtins__": {}}, dict(ENUMS))))   # (this repository's own file)
    for m in re.finditer(r"\bTAG\((log_tag_const_\w+)\)", src):
        v[m.group(1)] = ("i8", 0)                   # ble_stubs.c: #define TAG(n) const char n = 0;
    v["config_asser"] = ("i32", 0)                  # audio_probe.h: const uint32_t config_asser = 0
    return v


def fold(ll, vals):
    """The member's IR text with the constants folded and the print helpers emptied: (text, folded, skipped, emptied)."""
    folded, skipped, emptied = [0], [], [0]

    def g(m):
        name, ty = m.group(1), m.group(3)
        if name not in vals:
            return m.group(0)
        want, val = vals[name]
        if want != ty:                              # read at another width than defined: left to the linker
            skipped.append(f"{name} ({ty}, defined {want})")
            return m.group(0)
        folded[0] += 1
        return f"@{name} = internal constant {ty} {val}"

    def p(m):
        emptied[0] += 1
        attrs, ret, name, params = m.groups()
        val = "void" if ret == "void" else "i32 0"
        return f"define internal {attrs}{ret} @{name}({params}) {{\n  ret {val}\n}}"

    ll = PRINT.sub(p, GLOBAL.sub(g, ll))
    return ll, folded[0], skipped, emptied[0]


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(" ".join(os.path.basename(c) for c in cmd[:3]) + ": " + (r.stderr or r.stdout).strip()[-600:])
    return r


def text_ir(clang, b, ll, emit, say):
    """Member b's text IR into ll, as the bitcode holds it, no pass run on it. emit: the options found on the first
    member (None: find them, the first the toolchain's clang accepts). Returns the options used."""
    if emit is not None:
        run(clang + ["-S", "-emit-llvm", "-x", "ir", b, "-o", ll] + emit)
        return emit
    for flags in (["-Xclang", "-disable-llvm-passes"], ["-Xclang", "-disable-llvm-optzns"], []):
        try:
            run(clang + ["-S", "-emit-llvm", "-x", "ir", b, "-o", ll] + flags)
        except RuntimeError as e:
            say(f"text IR with {' '.join(flags) or 'no option'}: refused ({str(e)[-160:]})")
            continue
        say("text IR emitted with " + (" ".join(flags) if flags else "no option (clang's -O0 passes ran on it)"))
        return flags
    raise RuntimeError("no way to emit the text IR")


def fold_lib(argv):
    """jlfold.py fold: the image's library, folded. Exit 1 on any failure."""
    tc, cfg, out = argv[:3]
    members = argv[3:]
    clang = [f"{tc}/pi32v2/bin/clang", "-target", "pi32v2"]
    say = lambda s: print("jlfold: " + s, flush=True)
    try:
        if not members:
            raise RuntimeError("no members")
        vals = cfg_values(cfg)
        os.makedirs(out, exist_ok=True)
        emit, nfold, nprint, skipped = None, 0, 0, set()
        for b in members:
            name = os.path.basename(os.path.dirname(b)) + "_" + os.path.basename(b)[:-3]
            ll = os.path.join(out, name + ".ll")
            emit = text_ir(clang, b, ll, emit, say)
            t, nf, sk, npr = fold(open(ll).read(), vals)
            open(ll, "w").write(t)
            run(clang + ["-Os", "-c", "-x", "ir", ll, "-o", os.path.join(out, name + ".o")])
            os.remove(ll)
            nfold += nf
            nprint += npr
            skipped.update(sk)
        say(f"the library folded: {len(members)} members, {len(vals)} constants known, {nfold} folded, "
            f"{nprint} print helpers emptied" + (f"; left to the linker: {', '.join(sorted(skipped))}" if skipped else ""))
    except Exception as e:
        print(f"jlfold: the folded library failed: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 5 and sys.argv[1] == "fold":
        sys.exit(fold_lib(sys.argv[2:]))
    raise SystemExit("usage: jlfold.py fold TC CFG.c OUTDIR MEMBER.bc...")
