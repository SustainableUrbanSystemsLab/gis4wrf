#!/usr/bin/env bash
set -euo pipefail

# Run the 3 km Atlanta case fully inside WSL2 with Linux dmpar binaries.
# Outputs are written into the Windows project folder via /mnt/c.

NPROC="${NPROC:-24}"
MPI_ARGS="${MPI_ARGS:-}"
ALLOW_OVERSUBSCRIBE="${ALLOW_OVERSUBSCRIBE:-0}"
COPY_BACK="${COPY_BACK:-1}"
METGRID_NPROC="${METGRID_NPROC:-1}"
GEOGRID_NPROC="${GEOGRID_NPROC:-1}"
MPI_LAUNCHER="${MPI_LAUNCHER:-}"
REAL_NPROC="${REAL_NPROC:-1}"
WRF_NPROC="${WRF_NPROC:-}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WIN_ROOT="${WIN_ROOT:-}"
if [ -z "$WIN_ROOT" ]; then
  if [ -d "$SCRIPT_DIR/datasets" ]; then
    WIN_ROOT="$SCRIPT_DIR"
  else
    WIN_USER="$(cmd.exe /c echo %USERNAME% 2>/dev/null | tr -d '\r')"
    if [ -n "$WIN_USER" ] && [ -d "/mnt/c/Users/$WIN_USER/Documents/gis4wrf" ]; then
      WIN_ROOT="/mnt/c/Users/$WIN_USER/Documents/gis4wrf"
    elif [ -d "/mnt/c/Users/pkastner/Documents/gis4wrf" ]; then
      WIN_ROOT="/mnt/c/Users/pkastner/Documents/gis4wrf"
    else
      echo "WIN_ROOT not found. Set WIN_ROOT to your gis4wrf data folder."
      exit 1
    fi
  fi
fi
case "$WIN_ROOT" in
  [A-Za-z]:\\*)
    WIN_ROOT="$(wslpath -u "$WIN_ROOT")"
    ;;
esac
DIST_ROOT="$WIN_ROOT/dist_wsl"
WRF_DIST="$DIST_ROOT/wrf"
WPS_DIST="$DIST_ROOT/wps"
WSL_WORK="${WSL_WORK:-/home/$USER/gis4wrf_runs}"
PROJ="$WSL_WORK/atlanta_3km_wsl"
WPS_DIR="$PROJ/run_wps"
WRF_DIR="$PROJ/run_wrf"
GEOG_DIR="$WIN_ROOT/datasets/geog"
GRIB_DIR="$WIN_ROOT/datasets/gfs_20240115"
OUT_WIN="$WIN_ROOT/projects/atlanta_3km_wsl_out"

WRF_URL="https://github.com/WRF-CMake/WRF/releases/download/WRF-CMake-4.0/wrf-cmake-4.0-dmpar-basic-release-linux.tar.xz"
WPS_URL="https://github.com/WRF-CMake/WPS/releases/download/WPS-CMake-4.0/wps-cmake-4.0-dmpar-basic-release-linux.tar.xz"

log() { printf "\n== %s ==\n" "$*"; }

if [ -z "$MPI_LAUNCHER" ]; then
  if command -v mpiexec.mpich >/dev/null 2>&1; then
    MPI_LAUNCHER="mpiexec.mpich"
  elif command -v mpirun.mpich >/dev/null 2>&1; then
    MPI_LAUNCHER="mpirun.mpich"
  elif command -v mpiexec >/dev/null 2>&1; then
    MPI_LAUNCHER="mpiexec"
  elif command -v mpirun >/dev/null 2>&1; then
    MPI_LAUNCHER="mpirun"
  fi
fi
if [ -z "$MPI_LAUNCHER" ]; then
  echo "MPI launcher not found. Install MPICH or OpenMPI."
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found. Install python3 first."
  exit 1
fi
if ! command -v curl >/dev/null 2>&1; then
  echo "curl not found. Install curl first."
  exit 1
fi

avail="$(nproc --all 2>/dev/null || nproc 2>/dev/null || echo 1)"
if [ -z "$MPI_ARGS" ]; then
  MPI_ARGS="--use-hwthread-cpus"
fi
if [ "$NPROC" -gt "$avail" ]; then
  if [ "$ALLOW_OVERSUBSCRIBE" = "1" ]; then
    MPI_ARGS="--oversubscribe $MPI_ARGS"
  else
    echo "Requested NPROC=$NPROC but only $avail processing units available in WSL."
    echo "Reducing NPROC to $avail. Set ALLOW_OVERSUBSCRIBE=1 to force oversubscribe."
    NPROC="$avail"
  fi
fi

mkdir -p "$WRF_DIST" "$WPS_DIST" "$WPS_DIR/geogrid" "$WPS_DIR/metgrid" "$WRF_DIR"
mkdir -p "$WSL_WORK"

if [ ! -d "$GEOG_DIR" ]; then
  echo "Geog data not found: $GEOG_DIR"
  exit 1
fi
if [ ! -d "$GRIB_DIR" ]; then
  echo "GFS GRIB data not found: $GRIB_DIR"
  exit 1
fi

# HDF5 file locking on /mnt/c often fails under MPI; disable locking and keep outputs on ext4.
export HDF5_USE_FILE_LOCKING=FALSE

libmpi_file="$(ls -1 "$WRF_DIST/main/.libs/libmpi"*.so* 2>/dev/null | head -n 1 || true)"
if [ -n "$libmpi_file" ]; then
  if grep -a -q "MPICH Version" "$libmpi_file" 2>/dev/null; then
    mpi_flavor="MPICH"
  elif grep -a -q "Open MPI" "$libmpi_file" 2>/dev/null; then
    mpi_flavor="OPENMPI"
  else
    mpi_flavor="UNKNOWN"
  fi
  if "$MPI_LAUNCHER" --version 2>/dev/null | grep -qi "Open MPI" && [ "$mpi_flavor" = "MPICH" ]; then
    echo "WRF binaries are linked against MPICH, but OpenMPI launcher '$MPI_LAUNCHER' is in use."
    echo "Install MPICH in WSL and re-run:"
    echo "  sudo apt-get update"
    echo "  sudo apt-get install -y mpich"
    echo "Then re-run this script (it will auto-use mpiexec.mpich)."
    exit 1
  fi
fi

clean_wps() {
  rm -f "$WPS_DIR"/GRIBFILE.* "$WPS_DIR"/PFILE_* "$WPS_DIR"/FILE_* \
        "$WPS_DIR"/met_em.d01.* "$WPS_DIR"/geo_em.d01.nc \
        "$WPS_DIR"/GEOGRID* "$WPS_DIR"/metgrid.log* "$WPS_DIR"/ungrib.log \
        "$WPS_DIR"/rsl.* 2>/dev/null || true
}

clean_wrf() {
  rm -f "$WRF_DIR"/wrfinput_d01 "$WRF_DIR"/wrfbdy_d01 \
        "$WRF_DIR"/wrfrst_d01* "$WRF_DIR"/wrfout_d01* \
        "$WRF_DIR"/rsl.* "$WRF_DIR"/namelist.output 2>/dev/null || true
}

if [ ! -x "$WRF_DIST/main/real.exe" ] && [ ! -x "$WRF_DIST/main/real" ]; then
  log "Downloading WRF dmpar"
  tmp="$(mktemp -d)"
  curl -L -o "$tmp/wrf.tar.xz" "$WRF_URL"
  tar -xJf "$tmp/wrf.tar.xz" -C "$WRF_DIST" --strip-components=1
  rm -rf "$tmp"
fi

if [ ! -x "$WPS_DIST/geogrid.exe" ] && [ ! -x "$WPS_DIST/geogrid" ]; then
  log "Downloading WPS dmpar"
  tmp="$(mktemp -d)"
  curl -L -o "$tmp/wps.tar.xz" "$WPS_URL"
  tar -xJf "$tmp/wps.tar.xz" -C "$WPS_DIST" --strip-components=1
  rm -rf "$tmp"
fi

GEOGRID="$WPS_DIST/geogrid.exe"; [ -x "$GEOGRID" ] || GEOGRID="$WPS_DIST/geogrid"
UNGRIB="$WPS_DIST/ungrib.exe";   [ -x "$UNGRIB" ]   || UNGRIB="$WPS_DIST/ungrib"
METGRID="$WPS_DIST/metgrid.exe"; [ -x "$METGRID" ] || METGRID="$WPS_DIST/metgrid"
REAL="$WRF_DIST/main/real.exe";  [ -x "$REAL" ]     || REAL="$WRF_DIST/main/real"
WRF="$WRF_DIST/main/wrf.exe";    [ -x "$WRF" ]      || WRF="$WRF_DIST/main/wrf"

log "Writing namelist.wps"
cat > "$WPS_DIR/namelist.wps" <<'EOF'
&share
 wrf_core = 'ARW',
 max_dom = 1,
 start_date = '2024-01-15_00:00:00',
 end_date   = '2024-01-16_00:00:00',
 interval_seconds = 21600,
 io_form_geogrid = 2,
 nocolons = .true.,
/

&geogrid
 parent_id         = 1,
 parent_grid_ratio = 1,
 i_parent_start    = 1,
 j_parent_start    = 1,
 e_we              = 120,
 e_sn              = 120,
 geog_data_res     = 'lowres',
 dx = 3000,
 dy = 3000,
 map_proj = 'lambert',
 ref_lat   = 33.749,
 ref_lon   = -84.388,
 truelat1  = 30.0,
 truelat2  = 60.0,
 stand_lon = -84.388,
 geog_data_path = '__GEOG_DIR__',
/

&ungrib
 out_format = 'WPS',
 prefix = 'FILE',
/

&metgrid
 fg_name = 'FILE',
 io_form_metgrid = 2,
/
EOF
sed -i "s|__GEOG_DIR__|$GEOG_DIR|" "$WPS_DIR/namelist.wps"

log "Writing namelist.input"
cat > "$WRF_DIR/namelist.input" <<'EOF'
&time_control
 run_days                 = 0,
 run_hours                = 24,
 run_minutes              = 0,
 run_seconds              = 0,
 start_year               = 2024,
 start_month              = 01,
 start_day                = 15,
 start_hour               = 00,
 end_year                 = 2024,
 end_month                = 01,
 end_day                  = 16,
 end_hour                 = 00,
 interval_seconds         = 21600,
 input_from_file          = .true.,
 history_interval         = 60,
 frames_per_outfile       = 1,
 restart                  = .false.,
 restart_interval         = 7200,
 io_form_history          = 2,
 io_form_restart          = 2,
 io_form_input            = 2,
 io_form_boundary         = 2,
 nocolons                 = .true.,
/

&domains
 time_step                = 18,
 time_step_fract_num      = 0,
 time_step_fract_den      = 1,
 max_dom                  = 1,
 e_we                     = 120,
 e_sn                     = 120,
 e_vert                   = 33,
 p_top_requested          = 5000,
 num_metgrid_levels       = 34,
 num_metgrid_soil_levels  = 4,
 dx                       = 3000,
 dy                       = 3000,
/

&physics
 physics_suite            = 'CONUS',
 cu_physics               = 0,
 cudt                     = 0,
 radt                     = 5,
 bldt                     = 0,
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
 gwd_opt                  = 1,
/

&bdy_control
 spec_bdy_width           = 5,
 specified                = .true.,
/

&grib2
/

&namelist_quilt
 nio_tasks_per_group      = 0,
 nio_groups               = 1,
/
EOF

log "Copying WPS tables"
cp "$WPS_DIST/geogrid/GEOGRID.TBL.ARW" "$WPS_DIR/geogrid/GEOGRID.TBL"
cp "$WPS_DIST/metgrid/METGRID.TBL.ARW" "$WPS_DIR/metgrid/METGRID.TBL"
cp "$WPS_DIST/ungrib/Variable_Tables/Vtable.GFS" "$WPS_DIR/Vtable"

log "Linking GRIB files"
clean_wps
export WPS_DIR GRIB_DIR
python3 - <<'PY'
import os, pathlib, string, itertools, shutil
out = pathlib.Path(os.environ["WPS_DIR"])
inp = pathlib.Path(os.environ["GRIB_DIR"])
for p in out.glob("GRIBFILE.*"):
    p.unlink(missing_ok=True)
files = sorted([p for p in inp.iterdir() if p.is_file()])
letters = string.ascii_uppercase
exts = (a+b+c for a in letters for b in letters for c in letters)
for src, ext in zip(files, exts):
    target = out / f"GRIBFILE.{ext}"
    try:
        os.symlink(src, target)
    except Exception:
        shutil.copy2(src, target)
PY

log "Run WPS"
cd "$WPS_DIR"
if [ "$GEOGRID_NPROC" -le 1 ]; then
  echo "Running geogrid serial (GEOGRID_NPROC=$GEOGRID_NPROC) for HDF5 stability."
fi
"$MPI_LAUNCHER" $MPI_ARGS -n "$GEOGRID_NPROC" "$GEOGRID"
"$UNGRIB"
if [ "$METGRID_NPROC" -le 1 ]; then
  echo "Running metgrid serial (METGRID_NPROC=$METGRID_NPROC) for HDF5 stability."
fi
"$MPI_LAUNCHER" $MPI_ARGS -n "$METGRID_NPROC" "$METGRID"

log "Prepare WRF runtime files"
if command -v rsync >/dev/null 2>&1; then
  rsync -av --exclude 'namelist.input*' --exclude '*.exe' "$WRF_DIST/test/em_real/" "$WRF_DIR/" >/dev/null
else
  cp -a "$WRF_DIST/test/em_real/." "$WRF_DIR/"
  rm -f "$WRF_DIR/namelist.input" "$WRF_DIR/namelist.input.*"
fi
cp "$WPS_DIR"/met_em.d01.* "$WRF_DIR"/
clean_wrf

log "Run WRF"
cd "$WRF_DIR"
if [ -z "$WRF_NPROC" ]; then
  WRF_NPROC="$NPROC"
fi
"$MPI_LAUNCHER" $MPI_ARGS -n "$REAL_NPROC" "$REAL"
"$MPI_LAUNCHER" $MPI_ARGS -n "$WRF_NPROC" "$WRF"

log "Done"
echo "Outputs in: $WRF_DIR"

if [ "$COPY_BACK" = "1" ]; then
  log "Copying outputs back to Windows"
  mkdir -p "$OUT_WIN"
  if command -v rsync >/dev/null 2>&1; then
    rsync -av --exclude '*.exe' "$PROJ/" "$OUT_WIN/" >/dev/null
  else
    cp -a "$PROJ/." "$OUT_WIN/"
  fi
  echo "Windows outputs in: $OUT_WIN"
fi
