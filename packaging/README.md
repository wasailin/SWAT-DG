# SWAT-DG Portable Packaging

Build self-contained Windows distributions for non-developer users.

## What This Produces

Two distribution options:

1. **Portable ZIP** -- Extract and run. No installation needed.
2. **Windows Installer** (optional) -- Traditional setup wizard via Inno Setup.

Both include an embedded Python 3.11 runtime with all dependencies pre-installed. End users do not need Python, pip, or any development tools.

## Package Contents

```
SWAT-DG/
    SWAT-DG.bat          # Double-click launcher
    python/                  # Embedded Python 3.11
        python.exe
        python311.dll
        Lib/site-packages/   # All dependencies
    app/
        swat_modern/         # Application code
        .streamlit/config.toml
    bin/                     # (optional) SWAT executable
    README.txt               # Quick-start for end users
```

## Prerequisites (For Building)

- Python 3.8+ (the build script runs on your dev machine's Python)
- Internet connection (downloads Python embeddable + pip packages)
- ~1.5 GB disk space for the build
- (Optional) [Inno Setup 6+](https://jrsoftware.org/isinfo.php) for building the Windows installer

## Building the Portable ZIP

```bash
python packaging/build_portable.py
```

Output: `packaging/SWAT-DG-v{version}-Windows.zip`

### Build Options

| Flag | Description |
|------|-------------|
| `--output-dir DIR` | Output directory (default: `packaging/`) |
| `--skip-deps` | Skip pip install (for faster rebuilds during development) |
| `--include-exe PATH` | Include a specific SWAT executable in the package |
| `--keep-build` | Keep the unzipped build directory (required for Inno Setup) |

### Examples

```bash
# Basic build
python packaging/build_portable.py

# Include a SWAT executable
python packaging/build_portable.py --include-exe C:/SWAT/swat_64rel.exe

# Build for Inno Setup (keeps the staging directory)
python packaging/build_portable.py --keep-build

# Quick rebuild without re-downloading dependencies
python packaging/build_portable.py --skip-deps
```

## Building the Windows Installer (Optional)

1. Build the portable package with `--keep-build`:
   ```bash
   python packaging/build_portable.py --keep-build
   ```

2. Install [Inno Setup 6](https://jrsoftware.org/isinfo.php) (free)

3. Compile the installer:
   ```bash
   iscc /DAppVersion=0.5.0 packaging/installer.iss
   ```

Output: `dist/SWAT-DG-v{version}-Setup.exe`

The installer creates Start Menu and (optional) Desktop shortcuts. No admin rights required.

## End-User Instructions

### ZIP Distribution

1. Download `SWAT-DG-v{version}-Windows.zip`
2. Extract to a folder (preferably a short path like `C:\SWAT-DG`)
3. Double-click `SWAT-DG.bat`
4. A browser window opens with the application
5. Keep the terminal window open while using the app
6. Press Ctrl+C in the terminal to stop

### Installer Distribution

1. Run `SWAT-DG-v{version}-Setup.exe`
2. Follow the setup wizard
3. Launch from the Start Menu or Desktop shortcut

## SWAT Executable Compatibility

SWAT-DG supports **SWAT2012 Rev. 681 and above**. A custom-compiled executable optimized for calibration speed is available on the [Releases](https://github.com/wasailin/SWAT-DG/releases) page. Alternatively, users can download a standard SWAT2012 executable from the [official SWAT website](https://swat.tamu.edu/) and place it in their project folder or the `bin/` directory of the portable package.

## Known Issues

- **Antivirus false positives**: Some antivirus software may flag `python.exe`. Add the SWAT-DG folder to your antivirus exclusions.
- **Windows path length**: Extract to a short path (e.g., `C:\SWAT-DG`). Deep paths like `C:\Users\...\Downloads\SWAT-DG-v0.5.0-Windows\SWAT-DG\` may exceed the 260-character Windows path limit.
- **Port 8501 in use**: If another application is using port 8501, close it or modify the port in `SWAT-DG.bat`.
- **GIS dependencies**: If `geopandas` or `rasterio` fail to install during the build, the Watershed Map page will not be available. All other features work normally.
