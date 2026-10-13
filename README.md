# HandGestures

Control Windows with hand gestures through your webcam: move the pointer and click, scroll,
switch and arrange windows, and control media playback, all without touching anything.

Hand tracking runs on your PC with [MediaPipe](https://ai.google.dev/edge/mediapipe/solutions/vision/hand_landmarker).
The camera image never leaves your computer and is never saved.

## Install

Download `HandGestures-Setup-<version>.exe` from the
[Releases](https://github.com/S11mk3/HandGestures/releases) page and run it. No administrator
rights are needed. Requires Windows 10 or 11 (64-bit) and a webcam.

## First start

1. **Calibration.** HandGestures checks your lighting, then asks you to hold up an open hand for a
   moment. This tunes gestures to your hand, your camera and your distance from it. It runs each
   time the app starts (you can turn that off in Settings) and takes about 5 seconds.
2. **Gesture guide.** The guide shows every gesture. It opens in practice mode: gestures light up
   when they're recognized, but nothing happens on your PC, so you can try them safely.
3. **The tray icon.** HandGestures lives in the system tray. Click the icon to pause or resume;
   right-click it for the camera preview, Settings, the guide and Quit.

## Gestures

| Gesture | Default action |
|---|---|
| ☝ Point with your index finger and move your hand | Move the pointer |
| 🤏 While pointing, pinch thumb and index finger | Click |
| 🤏🤏 Pinch twice quickly | Double click |
| ✌ Move two fingers up or down | Scroll |
| ✋ Swipe an open palm left / right | Switch to the next / previous window |
| ✋ Swipe an open palm down / up | Minimize / restore the window |
| ✊ Hold a still fist for a second | Play / pause media |
| 👐 Move two open palms apart / together | Maximize / restore down the window |

The swipes, the fist and the two-palm gestures can do other things too: show the desktop, change
tracks, mute, change the volume, go back or forward, or nothing at all. Choose in
**Settings → Gestures**.

The pointer moves like a finger on a touchpad: by how far your hand moves, faster when you move
quickly. To reposition your hand without moving the pointer, stop pointing, move, and point again.

## Tips for reliable tracking

- **Light:** face a window or lamp. Bright light *behind* you makes your hand a silhouette.
  Calibration tells you if it spots a lighting problem.
- **Distance:** about an arm's length from the camera works best, with your hand in view.
- **Steady gestures:** hold poses clearly. A swipe is a quick, deliberate sweep, not a drift.

## Settings

Right-click the tray icon and choose **Settings**. Changes apply immediately.

- **General:** start at sign-in, calibrate at every start, show the preview at start,
  battery saver.
- **Gestures:** what each gesture does, scroll speed, swipe length, fist hold time.
- **Pointer:** speed, acceleration, smoothing, and how firm a pinch must be to click.
- **Camera:** which webcam to use, recalibration, tracking details on the preview.

Settings, calibration and the log are kept in `%LOCALAPPDATA%\HandGestures`.

## Troubleshooting

| Problem | Try |
|---|---|
| "The camera picture is black" | Open the webcam's privacy shutter, or press the laptop's camera key. |
| "Can't use camera" | Close other apps using the camera (video calls), or pick another camera in Settings. |
| Gestures trigger by accident | Pause from the tray while you're not using it, or turn the gesture off in Settings. |
| The pointer is jittery | Raise **Smoothing** in Settings → Pointer, or add light and recalibrate. |
| Clicks don't register | Move **Pinch to click** toward *Light*. |
| Nothing happens in some apps | Windows blocks input to apps running as administrator unless HandGestures does too. |

The log (`handgestures.log`, in the folder above) records what was recognized and any errors.

## Privacy

HandGestures has no network features. The camera image is processed in memory, frame by frame,
and is never stored or sent anywhere.

---

## Development

Needs Python 3.11+ (tested with 3.13) on Windows.

```
python -m venv .venv
.venv\Scripts\pip install --no-cache-dir -r requirements-dev.txt
.venv\Scripts\python main.py
```

Options: `--dry-run` (log gestures without acting on them), `--no-preview`, `--no-calibration`,
`--verbose`. Running from source keeps settings and the log in the project folder. The hand model
is downloaded on the first run.

```
.venv\Scripts\python -m pytest     # tests
.venv\Scripts\python -m ruff check .   # lint
```

**Build the installer** (needs [Inno Setup 6](https://jrsoftware.org/isinfo.php):
`winget install JRSoftware.InnoSetup`):

```
powershell -ExecutionPolicy Bypass -File installer\build.ps1
```

This creates `dist\HandGestures-Setup-<version>.exe`. Pushing a `v*` tag builds it on GitHub
Actions and attaches it to a release.

### Project layout

```
main.py                    entry point (the installer bundles this)
handgestures/
  app.py                   starts the app: tray, windows, camera thread
  tracking_loop.py         camera frame → hands → gestures → actions; battery saver, reconnecting
  camera.py                reads the webcam, keeping only the newest frame
  image_tuning.py          judges the lighting, brightens dim pictures
  calibration.py           the light check and hand measurement at start
  hand_tracker.py          finds hands in a frame (MediaPipe)
  hand_landmarks.py        the 21 points of a hand
  hand_poses.py            finger bends → pose; the hand's size in the frame
  gesture_detector.py      sends each frame to the one- or two-hand gestures
  one_hand_gestures.py     swipes, fist hold, scroll, pointing
  pointer_gestures.py      pointer position and pinch clicks
  two_hand_gestures.py     palms apart / together
  cursor_motion.py         hand movement → cursor movement, with acceleration
  pointer_driver.py        moves the cursor smoothly on its own thread
  gestures.py              the gestures, and their cooldown
  bindings.py              the actions gestures can be bound to
  actions.py               performs actions in Windows
  windows_input.py         synthesized keyboard and mouse input
  config.py                settings, their validation, and live changes
  ui/                      tray icon, preview, calibration, settings and guide windows (Qt)
tests/                     unit tests, with synthetic hands
tools/                     icon and license helpers for the build
installer/                 PyInstaller spec, Inno Setup script, build script
```
