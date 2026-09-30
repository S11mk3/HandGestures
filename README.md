# HandGestures

Control Windows with hand gestures through your webcam: switch and arrange windows,
play and pause media, scroll, and move the mouse pointer and click.

Hand tracking runs locally with [MediaPipe](https://ai.google.dev/edge/mediapipe/solutions/vision/hand_landmarker).
The camera image never leaves your PC and is never saved.

## Gestures

| Gesture | Action |
|---|---|
| Point with your index finger | Move the pointer, like a finger on a touchpad |
| While pointing, pinch thumb and index finger | Left click |
| While pointing, pinch twice quickly | Double click |
| Move two fingers up / down | Scroll |
| Swipe open palm left / right | Alt+Tab / Alt+Shift+Tab |
| Swipe open palm down | Minimize window |
| Swipe open palm up | Restore last minimized window |
| Hold a fist for 1 s | Play / pause media |
| Move two open palms apart | Maximize window |
| Move two open palms together | Restore down window |

The pointer moves by how far your fingertip moves, starting from wherever it is. To reposition
your hand without moving the pointer, stop pointing, move, and point again.

## Run

Needs Windows 10 or later, Python 3.10+ (tested with 3.13) and a webcam.

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python main.py
```

- `--dry-run`: log gestures without acting on them
- `--no-preview`: start with the camera preview hidden

The app lives in the system tray. Click the icon to pause, or right-click it for the menu.
The hand model is downloaded on the first run.

## Settings

Edit `config.json` (created on first run), then restart. Each setting is described in
[`handgestures/config.py`](handgestures/config.py). The ones you're most likely to change:

| Setting | Default | |
|---|---|---|
| `pointer_speed` | 1.0 | How far the pointer moves for a given finger movement |
| `pointer_smoothing` | 2.0 | Lower = steadier pointer, but more lag |
| `pinch_distance` | 0.3 | Raise it if pinches are missed, lower it if clicks happen by themselves |
| `camera_index` | 0 | Which webcam to use |

## Build the installer

Requires [Inno Setup 6](https://jrsoftware.org/isinfo.php) (`winget install JRSoftware.InnoSetup`).

```
powershell -ExecutionPolicy Bypass -File installer\build.ps1
```

Creates `dist\HandGestures-Setup-<version>.exe`. The installed app keeps its settings and log
in `%LOCALAPPDATA%\HandGestures`.

## Project layout

```
main.py                  starts the tray icon and the camera thread
handgestures/
  camera_loop.py         camera frame → hands → gestures → actions
  camera.py              reads the webcam, keeping only the newest frame
  hand_tracker.py        finds up to two hands in a frame (MediaPipe)
  hand_landmarks.py      the 21 points of a hand
  hand_poses.py          hand points → pose (open palm, fist, pointing, ...)
  gesture_detector.py    sends each frame to the one- or two-hand gestures
  one_hand_gestures.py   swipes, fist hold, scroll, pointing
  pointer_gestures.py    pointer position and pinch clicks
  two_hand_gestures.py   palms apart / together
  gestures.py            the list of gestures, and their cooldown
  actions.py             gestures → Windows actions
  preview_window.py      always-on-top camera preview
  tray_icon.py           tray icon and menu
  app_state.py           state shared by the tray and the camera thread
  config.py              settings and their defaults
  paths.py               where the settings, log and model are stored
installer/               Windows installer build
```
