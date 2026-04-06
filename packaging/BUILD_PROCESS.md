# SWAT-DG Portable Package Build Process

This document describes the exact steps to rebuild the portable Windows .zip
distribution for users who do not have Python installed.

## Prerequisites

- Python 3.8+ on the build machine (the dev environment `.venv` works fine)
- Internet connection (downloads embedded Python + pip packages)
- ~1.5 GB free disk space

## Build Command

From the project root:

```bash
python packaging/build_portable.py
```

### Common Variants

```bash
# Include a SWAT executable in the package
python packaging/build_portable.py --include-exe C:/path/to/swat_64rel.exe

# Keep the staging directory (for Inno Setup installer or inspection)
python packaging/build_portable.py --keep-build

# Fast rebuild: skip pip install (reuses existing build/SWAT-DG/python)
python packaging/build_portable.py --skip-deps

# All options combined
python packaging/build_portable.py --keep-build --include-exe C:/path/to/swat.exe
```

## What the Script Does (8 Steps)

1. **Download embedded Python 3.11.9** (amd64) from python.org
2. **Patch `python311._pth`** to enable site-packages and `../app` imports
3. **Bootstrap pip** via `get-pip.py`
4. **Bundle tkinter** (Tcl/Tk) from the matching MSI
5. **Install all dependencies** from `pyproject.toml` `[full]` extras (17 packages, ~69 total with transitive deps). Falls back to skipping GIS packages if they fail.
6. **Copy application code** (`src/swat_modern/`) into `build/SWAT-DG/app/`
7. **Generate launcher** (`SWAT-DG.bat`) and `README.txt`
8. **Create zip** (`SWAT-DG-v{version}-Windows.zip`) in `packaging/`

## Output

- **File**: `packaging/SWAT-DG-v{version}-Windows.zip` (typically ~211 MB)
- **Version** is read from `pyproject.toml` (`project.version`)

## Build Duration

Approximately 5-10 minutes depending on internet speed (most time is spent downloading and installing pip packages).

## Updating the Version

Edit `pyproject.toml` line `version = "X.Y.Z"` before building. The script reads the version automatically.

## Optional: Windows Installer (.exe)

After building with `--keep-build`:

```bash
iscc /DAppVersion=0.5.0 packaging/installer.iss
```

Requires [Inno Setup 6+](https://jrsoftware.org/isinfo.php). Output: `dist/SWAT-DG-v{version}-Setup.exe`.

## Troubleshooting

| Issue | Fix |
|-------|-----|
| GIS packages fail to install | Build continues without them; Watershed Map page unavailable |
| Antivirus blocks python.exe | Add `packaging/build/` to exclusions |
| Path too long errors | Extract/build from a short path like `C:\SWAT-DG` |
| Port 8501 in use | Close other Streamlit instances or edit the port in `SWAT-DG.bat` |
