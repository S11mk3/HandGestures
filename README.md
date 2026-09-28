# HandGestures

Control Windows with hand gestures through your webcam.
Needs Windows 10 or later and Python 3.10+ (tested with 3.13).

| Gesture | Action |
|---|---|
| Swipe open palm down | Minimize window |
| Swipe open palm up | Restore last minimized window |
| Swipe open palm left / right | Alt+Tab / Alt+Shift+Tab |
| Hold a fist for 1 s | Play / pause media |
| Move two fingers up / down | Scroll |
| Move two open palms apart | Maximize window |
| Move two open palms together | Restore down window |

## Run

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python main.py
```

- `--dry-run`: log gestures without acting on them
- `--no-preview`: start with the camera preview hidden
- `--record`: record your hand movements (see below)

The app lives in the system tray. Click the icon to pause, or right-click it for the menu.

## Settings

Edit `config.json` (created on first run), then restart. Each setting is described in `handgestures/config.py`.

## Record gestures

Recordings hold only hand positions, no camera image. They're saved in `recordings\`.

```
.venv\Scripts\python -m tools.record_gestures                  # guided: prompts each gesture, ~3 min
.venv\Scripts\python main.py --record                          # everyday use
.venv\Scripts\python -m tools.replay_recording recordings\<file>.jsonl
```

Replay shows what the detector finds in a recording. Add `--set name=value` to try a different setting.

## Test

```
.venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\python -m pytest tests
```

## Build the installer

Requires [Inno Setup 6](https://jrsoftware.org/isinfo.php) (`winget install JRSoftware.InnoSetup`).

```
powershell -ExecutionPolicy Bypass -File installer\build.ps1
```

Creates `dist\HandGestures-Setup-<version>.exe`. The installed app keeps its settings and log in `%LOCALAPPDATA%\HandGestures`.

## Project layout

```
main.py                  starts the tray icon and the camera thread
handgestures/
  camera_loop.py         camera frame → hands → gestures → actions
  camera.py              reads the webcam, keeping only the newest frame
  hand_tracker.py        finds up to two hands in a frame (MediaPipe)
  hand_landmarks.py      the 21 points of a hand
  hand_poses.py          hand points → pose (open palm, fist, ...)
  gesture_detector.py    sends each frame to the one- or two-hand gestures
  one_hand_gestures.py   swipes, fist hold, scroll
  two_hand_gestures.py   palms apart / together
  gestures.py            the list of gestures, and their cooldown
  actions.py             gestures → Windows actions
  recorder.py            records hand movements to a file
  preview_window.py      always-on-top camera preview
  tray_icon.py           tray icon and menu
  app_state.py           state shared by the tray and the camera thread
  config.py              settings and their defaults
  paths.py               where the settings, log and model are stored
tools/                   guided recording and replay
installer/               Windows installer build
tests/
```
