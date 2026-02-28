# Atlanta Case Runbook

This runbook explains how to set up, run, and plot the Atlanta WRF example case using `uv`.

## Quick Start

```powershell
uv sync --group dev
uv run python setup_atlanta_sim.py
uv run python run_atlanta_sim.py --skip-wps --clean
uv run python plot_atlanta_results.py
```

Gallery output:

- `C:\Users\<you>\Documents\gis4wrf\projects\atlanta_test\plots_all_fields\index.html`

<details open>
<summary><strong>Case Summary</strong></summary>

- Domain center: Atlanta, GA (`33.749`, `-84.388`)
- Horizontal resolution: `30 km`
- Grid size: `40 x 40`
- Simulation period: `2024-01-15 00:00:00` to `2024-01-16 00:00:00` (UTC)
- Static data preset: `geog_data_res = 'lowres'`

</details>

<details open>
<summary><strong>Prerequisites</strong></summary>

- Windows with Python 3.9+ (this repo uses `uv`)
- `uv` installed
- Enough free disk space for WRF/WPS distributions, geog data, and outputs
- For multi-CPU runs: Microsoft MPI (`mpiexec`)

</details>

<details>
<summary><strong>1) Setup Files and Data</strong></summary>

Create Atlanta case files:

```powershell
uv run python setup_atlanta_sim.py
```

Creates/updates:

- `C:\Users\<you>\Documents\gis4wrf\dist\wrf`
- `C:\Users\<you>\Documents\gis4wrf\dist\wps`
- `C:\Users\<you>\Documents\gis4wrf\datasets\geog`
- `C:\Users\<you>\Documents\gis4wrf\projects\atlanta_test\run_wps\namelist.wps`
- `C:\Users\<you>\Documents\gis4wrf\projects\atlanta_test\run_wrf\namelist.input`

Optional MPI-enabled binaries (`dmpar`):

```powershell
uv run python setup_atlanta_sim.py --build dmpar --force-download
```

</details>

<details>
<summary><strong>2) Meteorological Inputs (GRIB / FILE_*)</strong></summary>

If you run full WPS (`geogrid/ungrib/metgrid`), you need meteorological input files.

The runner accepts:

- GRIB links/files in `run_wps` as `GRIBFILE.*`
- Ungrib output already in `run_wps` as `FILE_*`

If GRIB files are in a folder, pass it with `--grib-dir`; the script creates `GRIBFILE.*` links.

</details>

<details>
<summary><strong>3) Run the Simulation</strong></summary>

Serial run:

```powershell
uv run python run_atlanta_sim.py
```

Re-run only WRF (skip WPS):

```powershell
uv run python run_atlanta_sim.py --skip-wps --clean
```

MPI multi-CPU run (requires `dmpar` binaries):

```powershell
uv run python run_atlanta_sim.py --nproc 8
```

Notes:

- `--nproc > 1` requires MPI and `dmpar` WRF/WPS binaries.
- If `serial` binaries are installed, use `--nproc 1`.

</details>

<details>
<summary><strong>4) Plot All Fields</strong></summary>

```powershell
uv run python plot_atlanta_results.py
```

Outputs:

- `...\plots_all_fields\index.html`
- `...\plots_all_fields\maps\*.png`
- `...\plots_all_fields\series\*.png`

By default, map plots include a basic Atlanta landmark background overlay.
This includes metro city dots + labels and an approximate Metro Atlanta boundary outline.
Disable it with:

```powershell
uv run python plot_atlanta_results.py --no-landmarks
```

</details>

<details>
<summary><strong>5) Verify Success</strong></summary>

WPS success markers:

- `run_wps\geogrid.log` contains `Successful completion of program geogrid.exe`
- `run_wps\ungrib.log` contains `Successful completion of program ungrib.exe`
- `run_wps\metgrid.log` contains `Successful completion of program metgrid.exe`

WRF success markers:

- `run_wrf\real.stdout.log` contains `SUCCESS COMPLETE REAL_EM INIT`
- `run_wrf\wrf.stdout.log` contains `SUCCESS COMPLETE WRF`

Expected outputs:

- `run_wrf\wrfout_d01_2024-01-15_00_00_00` ... `run_wrf\wrfout_d01_2024-01-16_00_00_00`

</details>

<details>
<summary><strong>Command Reference</strong></summary>

Setup options:

```powershell
uv run python setup_atlanta_sim.py --help
```

Run options:

```powershell
uv run python run_atlanta_sim.py --help
```

Plot options:

```powershell
uv run python plot_atlanta_results.py --help
```

</details>
