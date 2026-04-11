# SWAT-DG v0.6.0 — Release Notes

**Release date:** 2026-04-12
**Previous release:** [v0.5.0](./SWAT-DG-v0.5.0-Windows.zip) (2026-04-08)

This release is a stability and correctness update focused on the calibration
pipeline. It fixes two bugs that could silently produce wrong results (sediment
routing parameters written to the wrong file; yearly/monthly outputs misread as
daily), makes the diagnostic calibrator less likely to stop early on
hard-to-fit constituents, hardens the parsers against real-world legacy input
files, and makes cancel and progress-bar updates actually work for parallel
calibration runs.

---

## Highlights

- **Correct sediment routing parameter targeting.** `PRF`, `SPCON`, and `SPEXP`
  were previously written to `basins.bsn`, where SWAT's `rtsed.f` never reads
  them per reach. They are now written to the `.rte` files, which is the
  location `readrte.f` actually loads. Sediment calibration runs before v0.6.0
  were effectively not adjusting these three parameters at all.
- **Yearly output timestep (`IPRINT=2`) is now fully supported** end-to-end, in
  addition to the existing daily and monthly timesteps. The calibrator, the
  result browser, and the observation-data merging logic all respect the
  active `IPRINT` setting explicitly rather than guessing from row values.
- **Diagnostic-guided calibration early stopping is gentler.** Phases for
  sediment, nitrogen, and phosphorus used to terminate before incremental
  progress had a chance to accumulate. The KGE improvement threshold was
  tightened from 0.01 to 0.001, it is only applied past 50 % of the iteration
  budget, and PBIAS is now allowed to degrade up to 10 pp relative to the
  phase baseline before a phase is cut off.
- **Legacy project compatibility.** Parameter loading now falls back to a
  tabular-format parser for older ArcSWAT / QSWAT `.sol` files, and
  observation CSVs exported from Windows Excel with a UTF-8 BOM header load
  cleanly instead of crashing the WQ loader.
- **Cancel and progress now work in parallel mode.** Clicking Cancel during
  a parallel SPOTPY run used to do nothing until every worker finished,
  and the progress bar stayed frozen at 0 because the in-memory callback
  could not cross process boundaries. Both are now driven by file-based
  signalling that every worker process reads on each simulation.

---

## Bug fixes

### Sediment routing parameters targeted the wrong file
`PRF`, `SPCON`, `SPEXP` were flagged as `.bsn` parameters in both
`calibration/parameters.py` and `io/generators/parameter_modifier.py`. In
SWAT rev 681 these are read per-reach by `readrte.f` into arrays indexed by
reach number and used in `rtsed.f`. Writing them into `basins.bsn` left the
per-reach arrays untouched, so sediment calibrations moved these sliders
with no effect on the simulation. They now write to the `.rte` files.

### Output parser confused yearly/monthly rows with daily rows
`ResultBrowser` previously guessed the timestep of `output.rch` by inspecting
row values, which misfired on yearly runs where SWAT injects aggregated
summary rows. The parser now takes `IPRINT` as an explicit input and strips
out summary rows based on the declared timestep. Date reconstruction was
rewritten to follow `IPRINT` directly instead of heuristics.

### Diagnostic calibrator terminated phases prematurely
Early stopping in `DiagnosticCalibrator` used a 0.01 KGE improvement window
applied from iteration 0. For low-signal constituents like sediment loads,
useful per-iteration improvements are routinely smaller than that, so
phases would exit after just a handful of trials. The threshold is now
0.001, gated behind 50 % of the iteration budget, and PBIAS is allowed to
drift up to 10 pp off the phase baseline (bounded by an absolute cap) so
that a phase that improves a specific constituent at the cost of a tolerable
volume-balance regression does not get cut short.

### HRU parameter updates were incomplete in some ensemble recipes
Several multi-constituent paths were not routing deferred WQ dataframes
through the full HRU-parameter update path, so a subset of per-HRU values
could be left at their backup state. The ensemble recipe plumbing in
`6_Calibration.py` was rewritten to dispatch the constituent-aware path
consistently.

### Empty observation windows crashed the diagnostic engine
When the sim/obs overlap after windowing was empty (common during
validation-period checks), `diagnostics.py` would raise. It now returns a
NaN-filled diagnostic report so the calling pipeline can short-circuit
gracefully instead of aborting the run.

### Calibration runner left stale validation data in aggregated results
Validation-period subsets were not being handled during result aggregation,
which could blend training and validation metrics in the results table.
`calibration_runner.py` now aggregates validation subsets separately.

### Cancel and progress-bar broken under SPOTPY parallel mode
SPOTPY's `parallel="mpc"` pickles `SWATModelSetup` to worker processes
via `__getstate__`, which nulls `progress_callback` and
`_cancel_event` because their closures reference main-process state
that can't cross process boundaries. The practical effects were:

- Clicking **Cancel** in the Calibration page only stopped the main
  thread; the pool of SWAT workers kept running to completion (up to
  several minutes), and in ensemble runs the next phase could even
  start before the flag was noticed.
- The **progress bar** stayed at 0 / frozen for the entire run in
  parallel mode — workers incremented their own local counters but had
  no way to report them back.
- `DiagnosticCalibrator`, `SequentialDiagnosticCalibrator`, and
  `EnsembleDiagnosticCalibrator` each had partial, inconsistent
  workarounds that did not compose.

The fix is a file-based signalling layer that every calibrator now
shares:

- A single shared **cancel-flag file** is created by
  `calibration_runner` before any calibrator starts, its path is
  registered on `CalibrationState`, and the path is threaded through
  `Calibrator`, `PhasedCalibrator`, `SequentialCalibrator`,
  `DiagnosticCalibrator`, `EnsembleDiagnosticCalibrator`, and
  `SequentialDiagnosticCalibrator` as a new `cancel_file=` kwarg.
  When the user clicks Cancel, `state.request_cancel()` touches the
  file; every worker process checks it at the top of `simulation()`
  and exits cleanly within one SWAT run.
- A shared **progress-counter directory** (`progress_counter_dir=`)
  in which each worker writes `{pid}.count`. A daemon thread in the
  main process aggregates the per-PID counts every 1.5 s and pushes
  them to `state.simulation_count`, which drives the UI fragment.
  This works uniformly across LHS, MC, SCE-UA, DREAM, and ROPE, and is
  harmless in sequential mode because the in-memory callback also
  fires and the counter is monotonic.
- The Calibration page's Cancel button now cleans up the temporary
  cancel-flag markers on completion so repeated runs in the same
  session don't leak temp directories.

### DREAM algorithm crashed immediately on default settings
`nChains` defaulted to a value below SPOTPY's internal `2 * delta + 1`
minimum (where `delta = 3`), so launching DREAM raised before the
first simulation. The default is now `nChains = 7`, which satisfies
the constraint.

---

## New features

### Yearly output timestep support
- `ResultBrowser` parses `IPRINT=2` yearly `output.rch` files, including the
  SWAT trailer rows that must be skipped.
- `SWATModelSetup` aggregates yearly data and performs mass-to-rate
  conversion when the calibration target is a rate rather than a total.
- `OutputSettings.print_code` documentation corrected (`0=monthly, 1=daily,
  2=yearly`) and the code is threaded through the sequential, phased, and
  diagnostic calibration pipelines.
- `MultiConstituentSetup` in the Calibration page natively respects `IPRINT`
  and switches between sums and means depending on the comparison mode.

### Legacy `.sol` file parsing
`parameter_modifier.py` gained a fallback parser for the older tabular
`.sol` layout produced by ArcSWAT and some QSWAT projects. Modern
key-value `.sol` files continue to use the primary parser, so existing
projects are unaffected.

### UTF-8 BOM tolerance for observation loaders
`wq_observation_loader.py` now opens CSVs with `utf-8-sig`, which
transparently strips the BOM that Windows Excel inserts when users "Save
As" CSV. The first column header previously came through as `\ufeffDATE`
and silently broke the date parser.

### Pre-calibration WQ validation
The Calibration page now refuses to launch a WQ calibration run if the
observation dataframe is empty or missing the active constituent, with a
clear message instead of a deep stack trace from SPOTPY.

---

## Minor / housekeeping

- Streamlit dataframe width property migrated from the deprecated
  `use_container_width=True` to `width="stretch"` in the calibration UI.
- Build timestamp is now written automatically in `head_version.py`.
- Debug prints cleaned up from the calibration and ensemble worker modules.
- Parameter locations in `parameters.py` now carry inline comments pointing
  back to the specific Fortran source file (e.g. `readrte.f`) that reads
  them, so future contributors do not have to re-derive this.

---

## Known limitations (unchanged from v0.5.0)

- GIS packages (`geopandas`, `rasterio`, `pyproj`) may fail to install on
  some machines; the build script falls back to skipping them and the
  Watershed Map page becomes unavailable.
- Antivirus may quarantine the bundled `python.exe`. Add
  `packaging/build/` to exclusions if this happens.
- The portable package requires extraction to a short path
  (e.g. `C:\SWAT-DG`) to avoid Windows `MAX_PATH` issues.

---

## Upgrade notes

This is a drop-in replacement for v0.5.0. No project-file migrations are
needed. If you had a sediment calibration in progress on v0.5.0, **re-run
it on v0.6.0** — the `PRF` / `SPCON` / `SPEXP` values produced by v0.5.0
sediment calibrations were not actually applied to the simulation, so the
"calibrated" values from v0.5.0 should be regarded as unconverged.
