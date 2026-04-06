"""
SWAT executable runner.

Handles execution of the SWAT Fortran executable.
"""

import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

from swat_modern.core.results import SimulationResult


class SWATRunner:
    """
    Executes SWAT simulations.

    Handles process management, timeout, and output capture.
    Supports cooperative cancellation via ``cancel_event``.

    Example:
        >>> runner = SWATRunner("swat2012.exe", "C:/project")
        >>> result = runner.run(timeout=3600)
    """

    def __init__(self, executable: Path, working_dir: Path):
        """
        Initialize runner.

        Args:
            executable: Path to SWAT executable
            working_dir: Working directory for simulation
        """
        self.executable = Path(executable)
        self.working_dir = Path(working_dir)

        if not self.executable.exists():
            raise FileNotFoundError(f"Executable not found: {self.executable}")

        if not self.working_dir.exists():
            raise FileNotFoundError(f"Working directory not found: {self.working_dir}")

    def run(
        self,
        timeout: Optional[int] = None,
        capture_output: bool = True,
        cancel_event: Optional[threading.Event] = None,
        cancel_file: Optional[str] = None,
    ) -> SimulationResult:
        """
        Run SWAT simulation.

        Args:
            timeout: Maximum time in seconds (None = no limit)
            capture_output: Whether to capture stdout/stderr
            cancel_event: If provided, the process is terminated when the
                event is set.  Used for cooperative cancellation from a
                background calibration thread (same process).
            cancel_file: If provided, the process is terminated when this
                file exists on disk.  Used for cross-process cancellation
                (e.g. ensemble workers in separate processes).

        Returns:
            SimulationResult with status and outputs
        """
        start_time = time.time()

        # Remove stale fin.fin so we can reliably detect whether THIS
        # run succeeds.  copytree may copy fin.fin from a previous run.
        fin_file = self.working_dir / "fin.fin"
        if fin_file.exists():
            fin_file.unlink()

        # Remove stale output files so a failed run cannot silently
        # return results from a previous simulation.
        for output_name in ("output.rch", "output.sub", "output.hru",
                            "output.rsv", "output.sed", "output.std"):
            stale = self.working_dir / output_name
            if stale.exists():
                stale.unlink()

        # Prepare command
        cmd = [str(self.executable)]

        # Set up process kwargs
        # Use DEVNULL instead of PIPE to avoid deadlock: if SWAT fills the
        # 64KB pipe buffer while the poll loop is sleeping, both processes
        # block forever.  Output is rarely needed — SWAT signals success
        # via fin.fin, and errors are detected from the return code.
        kwargs = {
            "cwd": str(self.working_dir),
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.PIPE if capture_output else subprocess.DEVNULL,
            "text": True,
        }

        cancelled = False

        try:
            process = subprocess.Popen(cmd, **kwargs)

            # Poll loop: wait for process to finish, checking cancel
            # every 0.25s so cancellation is responsive.
            # Two cancel mechanisms:
            #   cancel_event (threading.Event) — same-process threads
            #   cancel_file (path string) — cross-process workers
            _cancel_file_path = Path(cancel_file) if cancel_file else None
            if _cancel_file_path is not None:
                print(f"[runner] cancel_file active: {_cancel_file_path}")
            deadline = (start_time + timeout) if timeout is not None else None
            while process.poll() is None:
                _should_cancel = False
                if cancel_event is not None and cancel_event.is_set():
                    _should_cancel = True
                elif _cancel_file_path is not None and _cancel_file_path.exists():
                    _should_cancel = True
                if _should_cancel:
                    cancelled = True
                    print("[cancel] Terminating SWAT process...")
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                    break
                if deadline is not None and time.time() > deadline:
                    process.kill()
                    process.wait(timeout=5)
                    runtime = time.time() - start_time
                    return SimulationResult(
                        success=False,
                        runtime=runtime,
                        return_code=-1,
                        error_message=f"Simulation timed out after {timeout} seconds",
                        project_dir=self.working_dir,
                    )
                time.sleep(0.25)

            runtime = time.time() - start_time

            if cancelled:
                print(f"[cancel] SWAT process terminated ({runtime:.1f}s)")
                return SimulationResult(
                    success=False,
                    runtime=runtime,
                    return_code=process.returncode or -1,
                    error_message="Simulation cancelled by user",
                    project_dir=self.working_dir,
                )

            # Read remaining stderr (stdout goes to DEVNULL).
            stdout_data = ""
            stderr_data = ""
            if capture_output:
                try:
                    # stdout is DEVNULL so communicate() only drains stderr
                    _, stderr_data = process.communicate(timeout=5)
                    stderr_data = stderr_data or ""
                except Exception:
                    stderr_data = ""

            # Check for success: SWAT creates fin.fin on completion.
            # Do NOT trust returncode alone — the process can exit with
            # code 0 even after heap corruption or CRT abort dialogs.
            fin_file = self.working_dir / "fin.fin"
            success = fin_file.exists()

            # Determine error message if failed
            error_message = ""
            if not success:
                if stderr_data:
                    error_message = stderr_data[:500]
                else:
                    error_message = f"Process exited with code {process.returncode}"

            return SimulationResult(
                success=success,
                runtime=runtime,
                return_code=process.returncode,
                stdout=stdout_data or "",
                stderr=stderr_data or "",
                error_message=error_message,
                project_dir=self.working_dir,
            )

        except FileNotFoundError as e:
            runtime = time.time() - start_time
            return SimulationResult(
                success=False,
                runtime=runtime,
                return_code=-1,
                error_message=f"Executable not found: {e}",
                project_dir=self.working_dir,
            )

        except Exception as e:
            runtime = time.time() - start_time
            return SimulationResult(
                success=False,
                runtime=runtime,
                return_code=-1,
                error_message=str(e),
                project_dir=self.working_dir,
            )

    def check_executable(self) -> bool:
        """
        Check if executable can be run.

        Returns:
            True if executable appears valid
        """
        return self.executable.exists() and os.access(self.executable, os.X_OK)
