#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""OpenPocket offline installer: serves docs/ (installer, editor, packages) on this computer only, at
http://localhost:8765/ (Web MIDI works on localhost). Chrome or Edge. Ctrl+C stops it.
  tools/serve.py [install.html|editor.html] [firmware-dir]
The installer reads OpenPocket's packages and the catalog from firmware/, which is where the build puts them:
build/apps/gamut/. firmware-dir (for example build/ble) replaces it. The packages of an alternative firmware (an app on the base firmware, docs/ALT-FIRMWARE.md) are read from where the
build puts them: firmware/apps/NAME/ is build/apps/NAME/. The page offers the ones of its catalog
(firmware/release.json, tools/catalog.py) and any other one with install.html?app=NAME."""
import functools, http.server, os, sys, webbrowser

page = sys.argv[1] if len(sys.argv) > 1 else "install.html"
here = os.path.dirname(os.path.abspath(__file__))
root = os.path.abspath(os.path.join(here, "..", "docs"))
fwdir = os.path.abspath(os.path.join(here, "..", sys.argv[2] if len(sys.argv) > 2 else os.path.join("build", "apps", "gamut")))
appsdir = os.path.abspath(os.path.join(here, "..", "build", "apps"))

class Handler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map,
                      ".js": "text/javascript", ".mjs": "text/javascript", ".fwsc": "application/octet-stream"}
    def translate_path(self, path):
        p = super().translate_path(path)
        prefix = os.path.join(root, "firmware")
        apps = os.path.join(prefix, "apps")
        if p.startswith(apps + os.sep):
            return os.path.join(appsdir, os.path.relpath(p, apps))
        if p == prefix or p.startswith(prefix + os.sep):
            return os.path.join(fwdir, os.path.relpath(p, prefix))
        return p
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

for port in range(8765, 8785):
    try:
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), functools.partial(Handler, directory=root))
        break
    except OSError:
        continue
else:
    sys.exit("Could not open a local port (8765 to 8784).")
url = f"http://localhost:{port}/{page}"
print(f"\n  OpenPocket offline installer: {url}\n  Web editor: http://localhost:{port}/editor.html\n  (Chrome or Edge; Ctrl+C to stop)\n")
webbrowser.open(url)
try:
    srv.serve_forever()
except KeyboardInterrupt:
    pass
