# 3D Viewer

The standalone `index.html` is based on the uploaded
`3d_viewer_v26688_v5_ar_recovery_layers_hardware.html`. Its embedded JavaScript
libraries and STEP WebAssembly binary are retained. No application package
installation, backend, API keys, or build step is required.

## Development

Serve the checkout with Python 3:

```sh
cd /workspace/3d_viewer
python3 -m http.server 8000 --bind 127.0.0.1
```

For AR on a phone, deploy the page on HTTPS and open it directly in a compatible
browser. A desktop server's plain HTTP LAN address does not provide WebXR.

## AR behavior

- A layer's AR button exports only that layer. A group's button exports only the
  group's geometry. The final AR button in the Layers toolbar exports the union
  of the checked layers and groups, with each mesh included once.
- Layer exports use a separate graph, retaining transforms and skeleton bindings;
  exporting never changes the live model's visibility or materials.
- Before opening the device file manager, AR saves actual GLB data, object poses,
  the pending queue, and the open viewer models/groups in IndexedDB, then ends
  XR. Opening Files and restarting AR use fresh user gestures.
- The selected raw files are saved before conversion. After a tab reload, the
  page restores previous models and resumes an interrupted conversion. If the
  operating system killed the tab before the file-selection event was delivered,
  the previous scene is restored and the new file must be selected again.
- A new XR session has a new physical coordinate origin. Persistent anchors are
  restored when available; otherwise the user must align the previous scene.
- Native Scene Viewer / Quick Look receives the exported subset, rather than the
  full original model. Multi-object recovery requires WebXR.
- If recovery storage fails, the live XR scene stays open and Files is not opened.
  Backups remain local to this browser and origin; browser data eviction or
  clearing site data can remove them. `Discard AR backup` removes the backup;
  `Back to viewer` retains it. Explicitly exiting AR clears its checkpoint.

## Hardware settings

Settings → Hardware / GPU settings shows the renderer name exposed by active
WebGL contexts and the CPU information the browser allows. The preference
(default / high performance / low power) applies to newly created graphics
contexts. New AR and room renderers use it; the main viewer shares its context
and needs a reload after saving work. Browsers may ignore a power preference.
A website cannot enumerate every installed GPU, read the exact CPU model, force
an individual GPU, or switch WebGL/WebXR to CPU rendering.

## Regression tests

Tests require Python, Playwright (validated with 1.62.0), and Chromium. With those
installed:

```sh
python3 -m unittest discover -s tests -v
```

`CHROMIUM_PATH` overrides `/usr/bin/chromium`. `VIEWER_BROWSER_HOME` optionally
selects a browser home directory with the environment's trusted proxy CA. TLS
verification remains enabled. The application itself uses its embedded libraries.

The suite exercises real Chromium model loading and GLB exports, layer/group
selection, reload recovery, conversion recovery, native AR subset packaging,
hardware preferences, storage failure, and XR interruption/cancellation/exit.
WebXR sessions are simulated in lifecycle tests. Real camera tracking, physical
alignment, Android tab eviction, and iOS/Android native AR still require phone
validation.
