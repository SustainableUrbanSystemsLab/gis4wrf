"""
Setup script for a coarse (30km) WRF simulation centered on Atlanta, GA.

This script:
1. Downloads pre-built WRF-CMake 4.0 binaries for Windows (serial by default, dmpar optional)
2. Downloads mandatory low-resolution geographic datasets
3. Creates WPS and WRF namelist files for a 24-hour test run

Usage:
    python setup_atlanta_sim.py
    python setup_atlanta_sim.py --build dmpar
    python setup_atlanta_sim.py --build dmpar --force-download

After running this script, you still need to:
- Download meteorological data (GFS) from NCAR RDA (requires free account)
- Run the WPS/WRF programs in sequence
"""

import os
import sys
import shutil
import tempfile
import json
import argparse
from datetime import datetime, timedelta
from pathlib import Path

# Add project to path
sys.path.insert(0, str(Path(__file__).parent))

from gis4wrf.core.downloaders.util import download_file_with_progress
from gis4wrf.core.downloaders.geo import download_and_extract_geo_dataset
from gis4wrf.core.downloaders.datasets import geo_datasets_mandatory_lores
from gis4wrf.core.constants import WRF_DIST, WPS_DIST

# === Configuration ===
# Atlanta, GA coordinates
CENTER_LAT = 33.749
CENTER_LON = -84.388

# 30km coarse resolution, single domain
DX = 30000  # meters
DY = 30000
E_WE = 40   # grid points west-east (40 * 30km = 1200km)
E_SN = 40   # grid points south-north

# Simulation period: 24-hour test
START = datetime(2024, 1, 15, 0, 0, 0)
END = START + timedelta(hours=24)

# Working directory
WORK_DIR = Path.home() / "Documents" / "gis4wrf"
DIST_DIR = WORK_DIR / "dist"
GEOG_DIR = WORK_DIR / "datasets" / "geog"
RUN_DIR = WORK_DIR / "projects" / "atlanta_test"
RUN_WPS_DIR = RUN_DIR / "run_wps"
RUN_WRF_DIR = RUN_DIR / "run_wrf"

def download_with_progress(url, dest_dir, name):
    """Download and extract a distribution."""
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    filename = url.split('/')[-1]
    tmp_dir = tempfile.mkdtemp()
    tmp_path = os.path.join(tmp_dir, filename)

    print(f"  Downloading {name} from {url}...")
    try:
        for progress in download_file_with_progress(url, tmp_path):
            pct = int(progress * 100)
            print(f"\r  [{pct:3d}%] Downloading {name}...", end="", flush=True)
        print(f"\r  [100%] Download complete. Extracting...")
        shutil.unpack_archive(tmp_path, str(dest_dir))
        print(f"  Extracted to {dest_dir}")
    finally:
        shutil.rmtree(tmp_dir)

def step1_download_binaries(build_type='serial', force_download=False):
    """Download WRF and WPS pre-built binaries."""
    print("\n=== Step 1: Download WRF/WPS binaries ===")
    print(f"  Build type: {build_type}")

    wrf_dir = DIST_DIR / "wrf"
    wps_dir = DIST_DIR / "wps"

    if force_download and wrf_dir.exists():
        shutil.rmtree(wrf_dir)
    if force_download and wps_dir.exists():
        shutil.rmtree(wps_dir)

    if wrf_dir.exists() and any(wrf_dir.rglob("real*")):
        print(f"  WRF already downloaded at {wrf_dir}")
    else:
        wrf_url = WRF_DIST['Windows'][build_type]
        download_with_progress(wrf_url, wrf_dir, "WRF")

    if wps_dir.exists() and any(wps_dir.rglob("geogrid*")):
        print(f"  WPS already downloaded at {wps_dir}")
    else:
        wps_url = WPS_DIST['Windows'][build_type]
        download_with_progress(wps_url, wps_dir, "WPS")

    # Find actual executable locations
    wrf_exe = list(wrf_dir.rglob("real.exe"))
    wps_exe = list(wps_dir.rglob("geogrid.exe"))

    if wrf_exe:
        print(f"  WRF executables found in: {wrf_exe[0].parent}")
    else:
        print("  WARNING: real.exe not found in WRF distribution!")

    if wps_exe:
        print(f"  WPS executables found in: {wps_exe[0].parent}")
    else:
        print("  WARNING: geogrid.exe not found in WPS distribution!")

    return wrf_dir, wps_dir

def step2_download_geo_data():
    """Download mandatory geographic datasets."""
    print("\n=== Step 2: Download geographic (static) data ===")
    print(f"  Datasets will be stored in: {GEOG_DIR}")
    GEOG_DIR.mkdir(parents=True, exist_ok=True)

    datasets = geo_datasets_mandatory_lores
    total = len(datasets)

    for i, dataset_name in enumerate(datasets, 1):
        dataset_path = GEOG_DIR / dataset_name
        if dataset_path.exists():
            print(f"  [{i}/{total}] {dataset_name} - already downloaded")
            continue

        print(f"  [{i}/{total}] Downloading {dataset_name}...")
        try:
            for progress in download_and_extract_geo_dataset(dataset_name, GEOG_DIR):
                pct = int(progress * 100)
                print(f"\r  [{i}/{total}] [{pct:3d}%] {dataset_name}...", end="", flush=True)
            print(f"\r  [{i}/{total}] {dataset_name} - done")
        except Exception as e:
            print(f"\r  [{i}/{total}] {dataset_name} - FAILED: {e}")
            print(f"           You may need to download manually from UCAR")

def step3_create_namelists():
    """Create WPS and WRF namelist files for Atlanta."""
    print("\n=== Step 3: Create project namelists ===")

    RUN_WPS_DIR.mkdir(parents=True, exist_ok=True)
    RUN_WRF_DIR.mkdir(parents=True, exist_ok=True)

    # WPS namelist
    wps_namelist = f"""&share
 wrf_core = 'ARW',
 max_dom = 1,
 start_date = '{START:%Y-%m-%d_%H:%M:%S}',
 end_date   = '{END:%Y-%m-%d_%H:%M:%S}',
 interval_seconds = 21600,
 io_form_geogrid = 2,
 nocolons = .true.,
/

&geogrid
 parent_id         = 1,
 parent_grid_ratio = 1,
 i_parent_start    = 1,
 j_parent_start    = 1,
 e_we              = {E_WE},
 e_sn              = {E_SN},
 geog_data_res     = 'lowres',
 dx = {DX},
 dy = {DY},
 map_proj = 'lambert',
 ref_lat   = {CENTER_LAT},
 ref_lon   = {CENTER_LON},
 truelat1  = 30.0,
 truelat2  = 60.0,
 stand_lon = {CENTER_LON},
 geog_data_path = '{str(GEOG_DIR).replace(chr(92), "/")}',
/

&ungrib
 out_format = 'WPS',
 prefix = 'FILE',
/

&metgrid
 fg_name = 'FILE',
 io_form_metgrid = 2,
/
"""

    # WRF namelist
    wrf_namelist = f"""&time_control
 run_days                 = 0,
 run_hours                = 24,
 run_minutes              = 0,
 run_seconds              = 0,
 start_year               = {START.year},
 start_month              = {START.month:02d},
 start_day                = {START.day:02d},
 start_hour               = {START.hour:02d},
 end_year                 = {END.year},
 end_month                = {END.month:02d},
 end_day                  = {END.day:02d},
 end_hour                 = {END.hour:02d},
 interval_seconds         = 21600,
 input_from_file          = .true.,
 history_interval         = 180,
 frames_per_outfile       = 1,
 restart                  = .false.,
 restart_interval         = 7200,
 io_form_history          = 2,
 io_form_restart          = 2,
 io_form_input            = 2,
 io_form_boundary         = 2,
/

&domains
 time_step                = 180,
 time_step_fract_num      = 0,
 time_step_fract_den      = 1,
 max_dom                  = 1,
 e_we                     = {E_WE},
 e_sn                     = {E_SN},
 e_vert                   = 33,
 p_top_requested          = 5000,
 num_metgrid_levels       = 34,
 num_metgrid_soil_levels  = 4,
 dx                       = {DX},
 dy                       = {DY},
/

&physics
 physics_suite            = 'CONUS',
 radt                     = 30,
 bldt                     = 0,
 cudt                     = 5,
 num_land_cat             = 21,
/

&fdda
/

&dynamics
 hybrid_opt               = 2,
 w_damping                = 0,
 diff_opt                 = 1,
 km_opt                   = 4,
 diff_6th_opt             = 0,
 diff_6th_factor          = 0.12,
 base_temp                = 290.,
 damp_opt                 = 3,
 zdamp                    = 5000.,
 dampcoef                 = 0.2,
 khdif                    = 0,
 kvdif                    = 0,
 non_hydrostatic          = .true.,
 moist_adv_opt            = 1,
 scalar_adv_opt           = 1,
/

&bdy_control
 spec_bdy_width           = 5,
 specified                = .true.,
/

&namelist_quilt
 nio_tasks_per_group      = 0,
 nio_groups               = 1,
/
"""

    wps_path = RUN_WPS_DIR / "namelist.wps"
    wrf_path = RUN_WRF_DIR / "namelist.input"

    wps_path.write_text(wps_namelist)
    print(f"  Created WPS namelist: {wps_path}")

    wrf_path.write_text(wrf_namelist)
    print(f"  Created WRF namelist: {wrf_path}")

def print_next_steps():
    """Print instructions for remaining manual steps."""
    print("\n" + "="*60)
    print("  SETUP COMPLETE - Next Steps")
    print("="*60)
    print(f"""
Your Atlanta WRF project is set up at:
  {RUN_DIR}

To run the full simulation, you need to:

1. DOWNLOAD METEOROLOGICAL DATA
   You need GFS data for the simulation period ({START:%Y-%m-%d} to {END:%Y-%m-%d}).

   Option A: Use the GIS4WRF plugin in QGIS to download GFS data
   Option B: Download manually from NCAR RDA:
             https://rda.ucar.edu/datasets/d084001/
             (requires free account)

   Download GFS 0.25-degree data for:
   - Start: {START:%Y-%m-%d %H:%M}
   - End:   {END:%Y-%m-%d %H:%M}
   - Interval: 6 hours

2. RUN WPS (in order):
   a. geogrid.exe  - processes geographic data
   b. ungrib.exe   - extracts met data from GRIB files
   c. metgrid.exe  - interpolates met data to WRF grid

3. RUN WRF:
   a. real.exe     - creates initial/boundary conditions
   b. wrf.exe      - runs the actual simulation

All executables are in:
  WPS: {DIST_DIR / 'wps'}
  WRF: {DIST_DIR / 'wrf'}

Working directories:
  WPS run: {RUN_WPS_DIR}
  WRF run: {RUN_WRF_DIR}
  Geographic data: {GEOG_DIR}
""")

def parse_args():
    parser = argparse.ArgumentParser(description='Set up Atlanta WRF test case')
    parser.add_argument(
        '--build',
        choices=['serial', 'dmpar'],
        default='serial',
        help='WRF/WPS build to download (dmpar supports MPI multi-CPU runs)',
    )
    parser.add_argument(
        '--force-download',
        action='store_true',
        help='Delete existing dist/wrf and dist/wps and re-download selected build',
    )
    return parser.parse_args()

if __name__ == '__main__':
    args = parse_args()

    print("="*60)
    print("  GIS4WRF Atlanta Simulation Setup")
    print(f"  Center: {CENTER_LAT}N, {abs(CENTER_LON)}W")
    print(f"  Resolution: {DX/1000:.0f}km, Grid: {E_WE}x{E_SN}")
    print(f"  Period: {START:%Y-%m-%d %H:%M} to {END:%Y-%m-%d %H:%M}")
    print(f"  Build: {args.build}")
    print(f"  Force download: {args.force_download}")
    print("="*60)

    step1_download_binaries(build_type=args.build, force_download=args.force_download)
    step2_download_geo_data()
    step3_create_namelists()
    print_next_steps()
