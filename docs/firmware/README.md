This folder is the installer's `firmware/` on a site. The build does not write here: `build.bat` (or
`firmware/build.sh`) puts OpenPocket's `PocketX_9NN.fwsc`, `BlackBox_9NN.fwsc`, `manifest.json` and `release.json`, the
catalog of the firmwares the page offers (`tools/catalog.py`), in `build/apps/gamut/`, and each alternative firmware's
packages in `build/apps/<name>/`. The local servers (`tools/serve.py`, `INSTALL-OFFLINE.bat`, `tools/sim.mjs`) serve
`build/apps/gamut/` as `firmware/` and `build/apps/<name>/` as `firmware/apps/<name>/`; a release puts the same files at the
same paths on the site.

A test build (for example `node tools/op.mjs package-test`) goes to a subfolder, `build/apps/gamut/midi-test/`, with its own
`manifest.json`. The installer page offers it only through `install.html?channel=midi-test`, with a banner; the normal page and
the files above are never changed by it.
