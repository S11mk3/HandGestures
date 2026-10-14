"""Copies the license files of every package the app bundles into <folder>/licenses/<package>/.

Apache-2.0 and the LGPL require shipping the license texts with the app; build.ps1 runs this
on dist\\Hard2Gesture after PyInstaller.  Usage: python tools/collect_licenses.py dist/Hard2Gesture
"""
import re
import shutil
import sys
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path

from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parent.parent
LICENSE_FILE = re.compile(r"(LICEN[CS]E|COPYING|NOTICE|AUTHORS)", re.IGNORECASE)


def runtime_packages() -> dict:
    """The packages in requirements.txt and everything they depend on, by name."""
    pending = [line.strip() for line in (ROOT / "requirements.txt").read_text().splitlines()
               if line.strip() and not line.startswith("#")]
    found = {}
    while pending:
        requirement = Requirement(pending.pop())
        if requirement.marker and not requirement.marker.evaluate({"extra": ""}):
            continue
        name = requirement.name.lower()
        if name in found:
            continue
        try:
            found[name] = distribution(name)
        except PackageNotFoundError:
            continue
        pending.extend(found[name].requires or [])
    return found


def main(target: Path):
    licenses = target / "licenses"
    shutil.rmtree(licenses, ignore_errors=True)
    packages = runtime_packages()
    packages["pyinstaller"] = distribution("pyinstaller")  # its bootloader starts the app
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if python_license.is_file():
        (licenses / "python").mkdir(parents=True)
        shutil.copyfile(python_license, licenses / "python" / "LICENSE.txt")
    # License texts packages don't ship themselves, e.g. Qt's LGPL (PySide6's wheels only carry a
    # reference to Qt's commercial license).
    shutil.copytree(ROOT / "installer" / "licenses", licenses, dirs_exist_ok=True)
    for name, dist in sorted(packages.items()):
        all_files = dist.files or []
        files = [file for file in all_files if LICENSE_FILE.search(file.name) and ".dist-info" in str(file)]
        files += [file for file in all_files if "licenses" in file.parts and file not in files]
        if not files:  # some packages keep it inside the package instead
            files = [file for file in all_files if LICENSE_FILE.search(file.name) and len(file.parts) <= 2]
        folder = licenses / f"{name}-{dist.version}"
        for file in files:
            source = Path(file.locate())
            if source.is_file():
                folder.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, folder / source.name)
        if not files:
            license_name = dist.metadata.get("License-Expression") or dist.metadata.get("License") or "see project"
            home = dist.metadata.get("Home-page") or next(iter(dist.metadata.get_all("Project-URL") or []), "")
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "LICENSE-REFERENCE.txt").write_text(
                f"{name} {dist.version} is licensed under: {license_name}\nProject: {home}\n", encoding="utf-8")
            print(f"note: {name} ships no license file; wrote a reference to its license ({license_name})")
    print(f"Copied licenses to {licenses}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
