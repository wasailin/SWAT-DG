"""
Build a portable Windows distribution of SWAT-DG.

Creates a self-contained zip with embedded Python, all dependencies,
and a double-click .bat launcher. End users need zero setup.

Usage:
    python packaging/build_portable.py
    python packaging/build_portable.py --include-exe C:/path/to/swat.exe
    python packaging/build_portable.py --skip-deps --keep-build
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PYTHON_VERSION = "3.11.9"
PYTHON_URL = (
    f"https://www.python.org/ftp/python/{PYTHON_VERSION}/"
    f"python-{PYTHON_VERSION}-embed-amd64.zip"
)
GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"
TCLTK_MSI_URL = (
    f"https://www.python.org/ftp/python/{PYTHON_VERSION}/amd64/tcltk.msi"
)

# Python version tag for the ._pth file (e.g. "311" for 3.11.x)
_PY_TAG = PYTHON_VERSION.replace(".", "")[:3]  # "3119" -> "311"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_NAME = "SWAT-DG"

# Known locations to search for a SWAT executable
SWAT_EXE_SEARCH = [
    PROJECT_ROOT / "fortran" / "build" / "bin" / "swat2012.exe",
    PROJECT_ROOT / "fortran" / "build" / "bin" / "swat_64rel.exe",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def log(msg: str) -> None:
    print(f"  [build] {msg}")


def log_step(msg: str) -> None:
    print(f"\n{'='*60}\n  {msg}\n{'='*60}")


def get_version() -> str:
    """Read version from pyproject.toml (canonical source)."""
    pyproject = PROJECT_ROOT / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")

    # Try tomllib first (Python 3.11+)
    try:
        import tomllib

        data = tomllib.loads(text)
        version = data["project"]["version"]
    except (ImportError, ModuleNotFoundError):
        match = re.search(r'version\s*=\s*"([^"]+)"', text)
        if not match:
            sys.exit("ERROR: Could not parse version from pyproject.toml")
        version = match.group(1)

    # Cross-check with __init__.py
    init_file = PROJECT_ROOT / "src" / "swat_modern" / "__init__.py"
    if init_file.exists():
        init_text = init_file.read_text(encoding="utf-8")
        m = re.search(r'__version__\s*=\s*"([^"]+)"', init_text)
        if m and m.group(1) != version:
            log(
                f"WARNING: pyproject.toml version ({version}) differs from "
                f"__init__.py ({m.group(1)}). Using pyproject.toml."
            )

    return version


def get_dependencies() -> list[str]:
    """Parse [full] optional dependencies from pyproject.toml."""
    pyproject = PROJECT_ROOT / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")

    try:
        import tomllib

        data = tomllib.loads(text)
        core = data["project"].get("dependencies", [])
        full = data["project"].get("optional-dependencies", {}).get("full", [])
        # Merge, dedup by package name
        all_deps = list(core) + [d for d in full if d not in core]
        return all_deps
    except (ImportError, ModuleNotFoundError):
        pass

    # Regex fallback: extract the full = [...] block
    core_match = re.search(
        r"^dependencies\s*=\s*\[(.*?)\]", text, re.MULTILINE | re.DOTALL
    )
    full_match = re.search(r'full\s*=\s*\[(.*?)\]', text, re.DOTALL)

    deps = []
    for m in [core_match, full_match]:
        if m:
            deps.extend(
                s.strip().strip('"').strip("'")
                for s in m.group(1).split(",")
                if s.strip().strip('"').strip("'")
            )

    if not deps:
        sys.exit("ERROR: Could not parse dependencies from pyproject.toml")

    # Dedup preserving order
    seen = set()
    unique = []
    for d in deps:
        name = re.split(r"[><=!]", d)[0].strip().lower()
        if name not in seen:
            seen.add(name)
            unique.append(d)
    return unique


def download_file(url: str, dest: Path) -> None:
    """Download a file with progress indication."""
    log(f"Downloading {url}")
    dest.parent.mkdir(parents=True, exist_ok=True)

    req = urllib.request.Request(url, headers={"User-Agent": "SWAT-DG-Builder/1.0"})
    with urllib.request.urlopen(req) as resp:
        total = int(resp.headers.get("Content-Length", 0))
        downloaded = 0
        chunk_size = 256 * 1024

        with open(dest, "wb") as f:
            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if total:
                    pct = downloaded * 100 // total
                    print(f"\r  [build] Progress: {pct}% ({downloaded // 1024}KB)", end="")
        if total:
            print()

    log(f"Saved to {dest} ({dest.stat().st_size // 1024}KB)")


# ---------------------------------------------------------------------------
# Build steps
# ---------------------------------------------------------------------------


def setup_embedded_python(build_dir: Path) -> Path:
    """Download and extract Python embeddable package."""
    log_step("Step 1/8: Download embedded Python")

    python_dir = build_dir / "python"
    python_dir.mkdir(parents=True, exist_ok=True)

    zip_path = build_dir / "python-embed.zip"
    download_file(PYTHON_URL, zip_path)

    log("Extracting Python...")
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(python_dir)

    zip_path.unlink()
    log(f"Python {PYTHON_VERSION} extracted to {python_dir}")
    return python_dir


def patch_pth_file(python_dir: Path) -> None:
    """Patch the ._pth file to enable site-packages and app imports."""
    log_step("Step 2/8: Patch Python path configuration")

    pth_file = python_dir / f"python{_PY_TAG}._pth"
    if not pth_file.exists():
        # Try to find it
        candidates = list(python_dir.glob("python*._pth"))
        if candidates:
            pth_file = candidates[0]
        else:
            sys.exit(f"ERROR: Could not find ._pth file in {python_dir}")

    new_content = (
        f"python{_PY_TAG}.zip\n"
        ".\n"
        "Lib\n"
        "Lib\\site-packages\n"
        "..\\app\n"
        "import site\n"
    )

    pth_file.write_text(new_content, encoding="utf-8")
    log(f"Patched {pth_file.name}:")
    for line in new_content.strip().split("\n"):
        log(f"  {line}")


def bootstrap_pip(python_dir: Path) -> None:
    """Download and run get-pip.py in the embedded Python."""
    log_step("Step 3/8: Bootstrap pip")

    get_pip = python_dir / "get-pip.py"
    download_file(GET_PIP_URL, get_pip)

    python_exe = python_dir / "python.exe"
    log("Running get-pip.py...")
    result = subprocess.run(
        [str(python_exe), str(get_pip), "--no-warn-script-location"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr)
        sys.exit("ERROR: Failed to bootstrap pip")

    get_pip.unlink()
    log("pip installed successfully")


def bundle_tkinter(python_dir: Path) -> None:
    """Download tcltk.msi from python.org and extract tkinter into embedded Python.

    The embeddable Python package excludes tkinter. We grab the matching
    tcltk.msi (same Python version) and copy in:
      - DLLs/_tkinter.pyd, tcl86t.dll, tk86t.dll  -> python/
      - Lib/tkinter/                                -> python/Lib/tkinter/
      - tcl/tcl8.6/, tcl/tk8.6/                    -> python/tcl/
    """
    log_step("Step 3b/8: Bundle tkinter (Tcl/Tk)")

    import tempfile

    # Use a short temp path — msiexec /a is sensitive to long/special paths
    tmp_base = Path(tempfile.mkdtemp(prefix="swat_tcltk_"))
    msi_path = tmp_base / "tcltk.msi"
    extract_dir = tmp_base / "out"

    # Download
    download_file(TCLTK_MSI_URL, msi_path)

    # Extract via msiexec (admin-free, /a = administrative install)
    extract_dir.mkdir(parents=True, exist_ok=True)
    log("Extracting tcltk.msi...")
    result = subprocess.run(
        ["msiexec", "/a", str(msi_path), "/qn",
         f"TARGETDIR={extract_dir.resolve()}"],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        log(f"WARNING: msiexec returned {result.returncode}, tkinter may not be available")
        shutil.rmtree(tmp_base, ignore_errors=True)
        return

    # Copy DLLs (_tkinter.pyd, tcl86t.dll, tk86t.dll) into python/ root
    dlls_src = extract_dir / "DLLs"
    for fname in ("_tkinter.pyd", "tcl86t.dll", "tk86t.dll"):
        src = dlls_src / fname
        if src.exists():
            shutil.copy2(src, python_dir / fname)
            log(f"  Copied {fname}")

    # Copy Lib/tkinter/ package (skip tests to save space)
    tk_pkg_src = extract_dir / "Lib" / "tkinter"
    tk_pkg_dst = python_dir / "Lib" / "tkinter"
    if tk_pkg_src.exists():
        shutil.copytree(
            tk_pkg_src, tk_pkg_dst,
            ignore=shutil.ignore_patterns("test", "__pycache__"),
            dirs_exist_ok=True,
        )
        log(f"  Copied tkinter package ({sum(1 for _ in tk_pkg_dst.rglob('*.py'))} .py files)")

    # Copy tcl/tk data directories (required at runtime)
    tcl_src = extract_dir / "tcl"
    tcl_dst = python_dir / "tcl"
    tcl_dst.mkdir(parents=True, exist_ok=True)
    for subdir in ("tcl8.6", "tk8.6"):
        src = tcl_src / subdir
        dst = tcl_dst / subdir
        if src.exists():
            shutil.copytree(src, dst, dirs_exist_ok=True)
            log(f"  Copied tcl/{subdir}/")

    # Cleanup temp directory
    shutil.rmtree(tmp_base, ignore_errors=True)

    # Verify
    python_exe = python_dir / "python.exe"
    verify = subprocess.run(
        [str(python_exe), "-c", "import tkinter; print('tkinter OK')"],
        capture_output=True, text=True, timeout=10,
    )
    if verify.returncode == 0:
        log(f"  Verified: {verify.stdout.strip()}")
    else:
        log(f"  WARNING: tkinter import failed: {verify.stderr.strip()}")


def install_dependencies(python_dir: Path, deps: list[str]) -> None:
    """Install all project dependencies into the embedded Python."""
    log_step("Step 4/8: Install dependencies")

    python_exe = python_dir / "python.exe"
    log(f"Installing {len(deps)} packages...")
    for dep in deps:
        log(f"  - {dep}")

    result = subprocess.run(
        [
            str(python_exe),
            "-m",
            "pip",
            "install",
            "--no-warn-script-location",
            "--disable-pip-version-check",
        ]
        + deps,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print(result.stdout[-2000:] if len(result.stdout) > 2000 else result.stdout)
        print(result.stderr[-2000:] if len(result.stderr) > 2000 else result.stderr)

        # Check if it's just optional GIS deps that failed
        log("WARNING: Some packages failed to install. Retrying without GIS deps...")
        gis_packages = {"geopandas", "rasterio", "pyproj", "xarray"}
        reduced_deps = [
            d for d in deps if re.split(r"[><=!]", d)[0].strip().lower() not in gis_packages
        ]

        result2 = subprocess.run(
            [
                str(python_exe),
                "-m",
                "pip",
                "install",
                "--no-warn-script-location",
                "--disable-pip-version-check",
            ]
            + reduced_deps,
            capture_output=True,
            text=True,
        )
        if result2.returncode != 0:
            print(result2.stderr)
            sys.exit("ERROR: Failed to install dependencies")

        log("WARNING: GIS packages (geopandas, rasterio, pyproj, xarray) were skipped.")
        log("Watershed map features will not be available in this build.")
    else:
        log("All dependencies installed successfully")

    # Show installed package count
    result_list = subprocess.run(
        [str(python_exe), "-m", "pip", "list", "--format=columns"],
        capture_output=True,
        text=True,
    )
    pkg_count = len(result_list.stdout.strip().split("\n")) - 2  # minus header lines
    log(f"Total packages installed: {pkg_count}")


def copy_app_code(build_dir: Path) -> None:
    """Copy the swat_modern package into the build."""
    log_step("Step 5/8: Copy application code")

    src = PROJECT_ROOT / "src" / "swat_modern"
    dest = build_dir / "app" / "swat_modern"

    if dest.exists():
        shutil.rmtree(dest)

    shutil.copytree(
        src,
        dest,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache"),
    )
    log(f"Copied {src} -> {dest}")

    # Count files
    file_count = sum(1 for _ in dest.rglob("*") if _.is_file())
    log(f"Application files: {file_count}")


def write_streamlit_config(build_dir: Path) -> None:
    """Write .streamlit/config.toml for the portable build."""
    config_dir = build_dir / "app" / ".streamlit"
    config_dir.mkdir(parents=True, exist_ok=True)

    config = config_dir / "config.toml"
    config.write_text(
        '[server]\n'
        'headless = true\n'
        'runOnSave = true\n'
        '\n'
        '[browser]\n'
        'gatherUsageStats = false\n',
        encoding="utf-8",
    )
    log(f"Wrote {config}")


def write_bat_launcher(build_dir: Path) -> None:
    """Generate the .bat launcher script."""
    log_step("Step 6/8: Generate launcher")

    bat_content = r'''@echo off
setlocal enabledelayedexpansion
title SWAT-DG - Calibration Tool

:: Determine script directory (handles spaces in path)
set "SCRIPT_DIR=%~dp0"
set "PYTHON=%SCRIPT_DIR%python\python.exe"
set "APP=%SCRIPT_DIR%app\swat_modern\app\main.py"

:: Verify Python exists
if not exist "%PYTHON%" (
    echo.
    echo  ERROR: Embedded Python not found.
    echo  Expected: %PYTHON%
    echo.
    echo  The portable package may be corrupted.
    echo  Please re-extract from the original zip file.
    echo.
    pause
    exit /b 1
)

:: Verify app exists
if not exist "%APP%" (
    echo.
    echo  ERROR: Application files not found.
    echo  Expected: %APP%
    echo.
    echo  The portable package may be corrupted.
    echo  Please re-extract from the original zip file.
    echo.
    pause
    exit /b 1
)

:: Isolate from system Python
set "PYTHONNOUSERSITE=1"
set "PYTHONDONTWRITEBYTECODE=1"

:: Set working directory so Streamlit finds .streamlit/config.toml
cd /d "%SCRIPT_DIR%app"

echo.
echo  ================================================
echo    SWAT-DG - Calibration Tool
echo  ================================================
echo.
echo    Starting web application...
echo    A browser window will open automatically.
echo.
echo    Keep this window open while using the app.
echo    Press Ctrl+C to stop the server.
echo  ================================================
echo.

:: Open browser after a short delay (headless mode won't open it)
start "" cmd /c "timeout /t 3 /nobreak >nul & start http://localhost:8501"

:: Launch Streamlit
"%PYTHON%" -m streamlit run "%APP%" ^
    --server.port 8501 ^
    --server.headless true ^
    --browser.gatherUsageStats false

:: If Streamlit exited with an error
if errorlevel 1 (
    echo.
    echo  The application exited unexpectedly.
    echo  Check that the package was fully extracted
    echo  and that port 8501 is not already in use.
    echo.
    pause
)
'''

    bat_file = build_dir / "SWAT-DG.bat"
    bat_file.write_text(bat_content, encoding="utf-8")
    log(f"Wrote {bat_file}")


def write_readme(build_dir: Path, version: str) -> None:
    """Write an end-user README.txt."""
    readme = build_dir / "README.txt"
    readme.write_text(
        f"SWAT-DG v{version} - Portable Edition\n"
        f"{'=' * 45}\n"
        "\n"
        "QUICK START\n"
        "-----------\n"
        "1. Double-click  SWAT-DG.bat\n"
        "2. A browser window will open automatically\n"
        "3. Follow the on-screen steps to load your SWAT project\n"
        "4. Keep the black terminal window open while using the app\n"
        "5. Press Ctrl+C in the terminal to stop\n"
        "\n"
        "REQUIREMENTS\n"
        "------------\n"
        "- Windows 10 or later (64-bit)\n"
        "- A SWAT2012 project folder (TxtInOut with file.cio)\n"
        "- A SWAT executable (.exe) - the app will ask for its location\n"
        "\n"
        "TIPS\n"
        "----\n"
        "- Extract this folder to a SHORT path (e.g., C:\\SWAT-DG)\n"
        "  to avoid Windows path length issues.\n"
        "- If your antivirus flags python.exe, add this folder to\n"
        "  your antivirus exclusions. This is a false positive.\n"
        "- All processing runs locally. Your data never leaves your computer.\n"
        "\n"
        "SUPPORT\n"
        "-------\n"
        "GitHub: https://github.com/wasailin/SWAT-DG\n"
        "\n"
        "LICENSE: Apache-2.0\n",
        encoding="utf-8",
    )
    log(f"Wrote {readme}")


def find_and_copy_swat_exe(build_dir: Path, explicit_path: str | None = None) -> None:
    """Optionally include a SWAT executable in the build."""
    log_step("Step 7/8: SWAT executable (optional)")

    bin_dir = build_dir / "bin"

    if explicit_path:
        exe = Path(explicit_path)
        if exe.exists():
            bin_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(exe, bin_dir / exe.name)
            log(f"Included SWAT executable: {exe.name}")
            return
        else:
            log(f"WARNING: Specified executable not found: {explicit_path}")

    # Auto-search
    for candidate in SWAT_EXE_SEARCH:
        if candidate.exists():
            bin_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(candidate, bin_dir / candidate.name)
            log(f"Found and included: {candidate.name}")
            return

    log("No SWAT executable found. Users will need to provide their own.")


def create_zip(build_dir: Path, output_path: Path) -> None:
    """Create the final distribution zip."""
    log_step("Step 8/8: Create distribution zip")

    log(f"Compressing to {output_path}...")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Remove existing zip if present
    if output_path.exists():
        output_path.unlink()

    file_count = 0
    total_size = 0

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for root, dirs, files in os.walk(build_dir):
            # Skip __pycache__
            dirs[:] = [d for d in dirs if d != "__pycache__"]

            for fname in files:
                if fname.endswith(".pyc"):
                    continue

                full_path = Path(root) / fname
                # Archive path: SWAT-DG/relative/path
                arc_name = PACKAGE_NAME + "/" + str(full_path.relative_to(build_dir))
                arc_name = arc_name.replace("\\", "/")
                zf.write(full_path, arc_name)
                file_count += 1
                total_size += full_path.stat().st_size

    zip_size = output_path.stat().st_size
    log(f"Files: {file_count}")
    log(f"Uncompressed: {total_size // (1024 * 1024)} MB")
    log(f"Compressed:   {zip_size // (1024 * 1024)} MB")
    log(f"Output: {output_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Build a portable Windows distribution of SWAT-DG."
    )
    parser.add_argument(
        "--output-dir",
        default=str(Path(__file__).parent),
        help="Directory for the output zip (default: packaging/)",
    )
    parser.add_argument(
        "--skip-deps",
        action="store_true",
        help="Skip pip install (for faster rebuilds during development)",
    )
    parser.add_argument(
        "--include-exe",
        default=None,
        help="Path to a SWAT executable to include in the build",
    )
    parser.add_argument(
        "--keep-build",
        action="store_true",
        help="Keep the build directory after zipping (needed for Inno Setup)",
    )

    args = parser.parse_args()

    print()
    print("  SWAT-DG Portable Package Builder")
    print("  =====================================")
    print()

    # Read project metadata
    version = get_version()
    log(f"Version: {version}")

    deps = get_dependencies()
    log(f"Dependencies: {len(deps)} packages")

    # Set up build directory
    output_dir = Path(args.output_dir)
    build_dir = output_dir / "build" / PACKAGE_NAME
    if build_dir.exists():
        log(f"Cleaning previous build: {build_dir}")
        shutil.rmtree(build_dir)
    build_dir.mkdir(parents=True, exist_ok=True)

    # Execute build steps
    python_dir = setup_embedded_python(build_dir)
    patch_pth_file(python_dir)
    bootstrap_pip(python_dir)
    bundle_tkinter(python_dir)

    if not args.skip_deps:
        install_dependencies(python_dir, deps)
    else:
        log("Skipping dependency installation (--skip-deps)")

    copy_app_code(build_dir)
    write_streamlit_config(build_dir)
    write_bat_launcher(build_dir)
    write_readme(build_dir, version)
    find_and_copy_swat_exe(build_dir, args.include_exe)

    # Create zip
    zip_name = f"{PACKAGE_NAME}-v{version}-Windows.zip"
    zip_path = output_dir / zip_name
    create_zip(build_dir, zip_path)

    # Cleanup
    if not args.keep_build:
        log("Cleaning build directory...")
        shutil.rmtree(build_dir.parent)
    else:
        log(f"Build directory kept at: {build_dir}")

    # Done
    print()
    print("  =====================================")
    print(f"  BUILD COMPLETE")
    print(f"  Output: {zip_path}")
    print(f"  Size:   {zip_path.stat().st_size // (1024 * 1024)} MB")
    print("  =====================================")
    print()


if __name__ == "__main__":
    main()
