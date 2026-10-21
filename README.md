# 3D Viewer

The standalone `index.html` is based on the uploaded
`3d_viewer_AR_v5.html`. Its embedded JavaScript
libraries and STEP WebAssembly binary are retained. No application package
installation, backend, API keys, or build step is required. Hand recognition loads
MediaPipe and its model over HTTPS on first use; it is not bundled offline.

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
- Opening the AR Add menu automatically checkpoints the scene in the background.
  Browse becomes available after the backup succeeds, with no backup confirmation
  or second "Scene saved" dialog. The browser's native picker is opened from that
  user gesture. Raw selected files are persisted before conversion.
- Before entering AR with a file-manager model or selected viewer layers, one
  dialog asks whether to use a table. Its Objects gallery uses the same definitions,
  preview icons, height, width, Auto sizing and Remove base controls as Objects.
  The table and centered model are exported together before XR, so recovery keeps
  the chosen table too. Existing complete models from other views are added as-is.
- A final table-choice gesture starts supported WebXR directly when browser
  activation remains valid. If model preparation outlasts that activation, one
  Continue action is required by the browser. Native AR also needs its own gesture.
- A new XR session has a new physical coordinate origin. Valid persistent anchors
  restore previous objects at their tracked positions. Models remain hidden until
  an anchor supplies an actual pose; failed/missing poses fall back after 8 seconds.
  Without usable anchors, the previous models are placed again, one at a time,
  before the newly selected model becomes ready for placement. New models are
  never automatically placed next to old ones.
- After a tab reload, previous models and interrupted conversion are restored.
  If the OS killed the tab before the file-selection event was delivered, the
  previous scene is restored and the new file must be selected again.
- Native Scene Viewer / Quick Look receives the exported subset, rather than the
  full original model. Multi-object recovery requires WebXR.
- If recovery storage fails, the live XR scene stays open and Files is not opened.
  Backups remain local to this browser and origin; browser data eviction or
  clearing site data can remove them. `Discard AR backup` removes the backup;
  `Back to viewer` retains it. Explicitly exiting AR clears its checkpoint.

## Hand controls

The AR session requests optional `camera-access` on its first start. The hand
button checks the feature granted by the browser, then loads MediaPipe Tasks
Vision 0.10.14 and the official Hand Landmarker model. No second camera stream is
opened alongside XR. Inference runs locally on the XR camera image in VIDEO mode.

The frame copy restores WebGL framebuffer, viewport, texture, VAO, program,
blend/depth/scissor/cull/stencil, color-mask and pixel-pack state. It corrects the
camera's bottom-up pixels; the preview's rotation/mirror is inverted when mapping
landmarks into the actual XR projection. Tap the preview to adjust orientation.

A stable thumb/index pinch can grab a nearby visible, unlocked placed object.
The object follows the hand; opening the pinch or losing the hand returns it to
its saved floor pose. Open-palm control also requires proximity. Temporary hand
poses are not written into recovery checkpoints, and tracking/session loss
restores the held object. Unsupported camera access is reported in the UI, with
touch controls left available.

MediaPipe assets are served from `cdn.jsdelivr.net`; its model is served from
`storage.googleapis.com`. Both must be reachable by the phone. This environment
could verify CDN access, but its proxy denied the model hostname; real model
loading and physical camera accuracy were not verified here. Camera-based hands
require a browser/device granting WebXR Raw Camera Access. Native Quick Look and
Scene Viewer do not expose this page's custom hand controls.

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
Additional checks cover table geometry/centering, direct entry from preflight,
sequential and persistent-anchor recovery, mobile toolbar layout, hand proximity/
pinch/release, hand-button permissions, and actual WebGL camera-copy state/pixels.
WebXR sessions and detector landmarks are simulated in lifecycle tests; the
MediaPipe model itself is not exercised by those tests. Real camera tracking, physical
alignment, Android tab eviction, and iOS/Android native AR still require phone
validation.
