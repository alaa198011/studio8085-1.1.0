# Installing 8085 Studio 1.2.0

Downloads come from the CI artifacts / release page of the repository. Each platform artifact contains a `SHA256SUMS-*.txt` file; check it
before running anything. The builds are **not code-signed**.

## Windows installer

File: `8085Studio-Setup-1.2.0.exe` (checksum in `SHA256SUMS-windows.txt`).

1. **Verify the checksum** (PowerShell), in the folder of the download:
   ```powershell
   Get-FileHash .\8085Studio-Setup-1.2.0.exe -Algorithm SHA256
   ```
   The hash must equal the one in `SHA256SUMS-windows.txt` (the file lists it in lower case; PowerShell prints upper case).
2. Double-click the installer. Because it is unsigned, Windows SmartScreen may say "Windows protected your PC": click **More info**,
   then **Run anyway**.
   **Windows 11 with Smart App Control turned on** blocks unsigned programs completely ("An Application Control policy has blocked this
   file"), with no *Run anyway* option. This was observed on a test PC for this release. On such a PC use the Python wheel below
   (`pip install`), which runs through the signed Python interpreter, or build from source. Turning Smart App Control off is a
   system-wide security decision for the PC's owner and is not recommended just for this program.
3. By default it installs per user without administrator rights (the setup dialog lets you choose all users) into the *8085 Studio* folder
   under the Programs directory, adds a Start-menu entry and optionally a desktop shortcut.
4. Optional check: `8085Studio.exe --selftest` in the install folder prints `selftest ok` and exits with code 0.
5. **Uninstall:** *Settings > Apps > Installed apps > 8085 Studio > Uninstall* (or the uninstaller in the install folder).

## Linux tarball

File: `8085Studio-linux-x86_64.tar.gz` (checksum in `SHA256SUMS-linux.txt`).

```bash
sudo apt install libegl1 libgl1 libxkbcommon0 libfontconfig1 libdbus-1-3 libxcb-cursor0   # Debian/Ubuntu
sha256sum -c SHA256SUMS-linux.txt --ignore-missing       # run in the folder holding the download
tar -xzf 8085Studio-linux-x86_64.tar.gz
./8085Studio/8085Studio
```

`./8085Studio/8085Studio --selftest` prints `selftest ok` if the build works on your system. The Linux build has been verified in a
headless (offscreen) environment only; reports from real desktops are welcome. To remove it, delete the `8085Studio` folder.

## Python wheel / source distribution

Needs Python 3.9 or newer (a virtual environment is recommended). Files: `studio8085-1.2.0-py3-none-any.whl` and
`studio8085-1.2.0.tar.gz`, both listed in `SHA256SUMS-linux.txt`.

```bash
python -m venv .venv && . .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install studio8085-1.2.0-py3-none-any.whl           # or: pip install studio8085-1.2.0.tar.gz
studio8085
```

`studio8085` is the application launcher (`[project.gui-scripts]` in `pyproject.toml`; PySide6 is installed as a dependency). On Linux, if Qt
cannot load the "xcb" platform plugin, install `libxcb-cursor0`.

## Other ways

From a source checkout: `pip install .`, or the per-user scripts `packaging/linux/install.sh` and `packaging\windows\install_windows.bat`
(see the README).
