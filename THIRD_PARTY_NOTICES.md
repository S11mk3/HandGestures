# Third-party notices

Hard2Gesture is built on the open-source components below. Each remains under its own license.
The installed app includes every component's full license text in its `licenses` folder
(next to `Hard2Gesture.exe`).

| Component | Used for | License |
|---|---|---|
| [MediaPipe](https://github.com/google-ai-edge/mediapipe) and its hand landmarker model | Finding hands and their landmarks | Apache-2.0 |
| [OpenCV](https://opencv.org) (opencv-contrib-python) | Reading the webcam, image processing | Apache-2.0 |
| [Qt](https://www.qt.io) via [PySide6](https://doc.qt.io/qtforpython/) and shiboken6 | Windows, tray icon | LGPL-3.0 |
| [NumPy](https://numpy.org) | Image arrays | BSD-3-Clause (and others, see its license file) |
| [pywin32](https://github.com/mhammond/pywin32) | Windows APIs | PSF |
| [pygrabber](https://github.com/andreaschiavinato/python_grabber), [comtypes](https://github.com/enthought/comtypes) | Camera names | MIT |
| [Python](https://www.python.org) | Runtime | PSF License |
| [PyInstaller](https://pyinstaller.org) bootloader | Starting the app | GPL-2.0 with an exception that allows bundling apps under any license |

MediaPipe also loads these, which are therefore bundled: matplotlib (PSF-based), sounddevice (MIT),
absl-py (Apache-2.0), flatbuffers (Apache-2.0), Pillow (MIT-CMU), contourpy (BSD-3-Clause),
cycler (BSD), fonttools (MIT), kiwisolver (BSD), pyparsing (MIT), python-dateutil (BSD/Apache-2.0),
packaging (Apache-2.0/BSD-2-Clause), six (MIT), certifi (MPL-2.0), cffi (MIT-0), pycparser (BSD-3-Clause).

## Qt and the LGPL

Hard2Gesture uses Qt under the GNU Lesser General Public License version 3. Qt's libraries
(`Qt6*.dll`, and the PySide6 and shiboken6 modules) are separate files in the app's `_internal`
folder, loaded at run time, so you can replace them with your own builds of the same versions.
Qt's source code is available at <https://download.qt.io/official_releases/qt/> and PySide6's at
<https://code.qt.io/cgit/pyside/pyside-setup.git/>. The license texts are in the `licenses` folder.
