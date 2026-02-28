"""
Run the Atlanta WRF test case end-to-end with optional MPI for multi-CPU runs.

Examples:
    uv run python run_atlanta_sim.py
    uv run python run_atlanta_sim.py --nproc 8
    uv run python run_atlanta_sim.py --skip-wps --nproc 8
"""

from __future__ import annotations

import argparse
import itertools
import os
import shutil
import string
import subprocess
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


def generate_gribfile_extensions() -> Iterable[str]:
    letters = list(string.ascii_uppercase)
    for a, b, c in itertools.product(letters, repeat=3):
        yield a + b + c


def link_or_copy(src: Path, dst: Path) -> None:
    if dst.exists() or dst.is_symlink():
        dst.unlink()
    try:
        os.symlink(src, dst)
        return
    except OSError:
        pass
    try:
        os.link(src, dst)
        return
    except OSError:
        shutil.copy2(src, dst)


def run_step(
    name: str,
    cmd: Sequence[str],
    cwd: Path,
    log_path: Path,
    error_markers: Tuple[str, ...] = ("ERROR", "FATAL"),
    extra_env: Optional[Dict[str, str]] = None,
) -> None:
    print(f"\n=== {name} ===")
    print("Command:", " ".join(cmd))
    print("Working directory:", cwd)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    markers = tuple(m.upper() for m in error_markers)
    marker_found = False

    with log_path.open("w", encoding="utf-8", errors="replace") as log_file:
        env = os.environ.copy()
        if extra_env:
            env.update(extra_env)

        proc = subprocess.Popen(
            list(cmd),
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
        )

        if proc.stdout is None:
            proc.wait()
            raise RuntimeError(f"{name} failed to produce output stream")

        for line in proc.stdout:
            print(line, end="")
            log_file.write(line)
            upper = line.upper()
            if any(m in upper for m in markers):
                marker_found = True

        return_code = proc.wait()

    if return_code != 0:
        raise RuntimeError(f"{name} failed with exit code {return_code}. See {log_path}")
    if marker_found:
        raise RuntimeError(f"{name} logged an error marker. See {log_path}")

    print(f"{name} completed successfully.")


def copy_if_needed(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not src.exists():
        raise FileNotFoundError(f"Missing required file: {src}")
    if not dst.exists():
        shutil.copy2(src, dst)
        return

    src_size = src.stat().st_size
    dst_size = dst.stat().st_size
    if src_size != dst_size:
        shutil.copy2(src, dst)


def find_mpiexec(preferred: Path | None = None) -> Path:
    candidates: List[Path] = []

    if preferred is not None:
        candidates.append(preferred)

    msm_pi = os.environ.get("MSMPI_BIN")
    if msm_pi:
        candidates.append(Path(msm_pi) / "mpiexec.exe")

    path_hit = shutil.which("mpiexec")
    if path_hit:
        candidates.append(Path(path_hit))

    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        "mpiexec not found. Install Microsoft MPI (MS-MPI) and ensure mpiexec is on PATH."
    )


def clean_outputs(run_wps_dir: Path, run_wrf_dir: Path, clean_wps: bool, clean_wrf: bool) -> None:
    if clean_wps and run_wps_dir.exists():
        for pattern in ("geo_em.d0*.nc", "met_em.d0*.nc", "GRIBFILE.*", "FILE_*"):
            for path in run_wps_dir.glob(pattern):
                path.unlink(missing_ok=True)
        for path in (run_wps_dir / "geogrid.log", run_wps_dir / "ungrib.log", run_wps_dir / "metgrid.log"):
            path.unlink(missing_ok=True)

    if clean_wrf and run_wrf_dir.exists():
        for pattern in ("wrfout_d0*", "wrfrst_d0*", "wrfinput_d0*", "wrfbdy_d0*", "rsl.*"):
            for path in run_wrf_dir.glob(pattern):
                path.unlink(missing_ok=True)


def link_grib_files(grib_dir: Path, run_wps_dir: Path) -> None:
    if not grib_dir.exists():
        raise FileNotFoundError(f"GRIB input directory not found: {grib_dir}")

    files = sorted([p for p in grib_dir.iterdir() if p.is_file()])
    if not files:
        raise FileNotFoundError(f"No GRIB files found in: {grib_dir}")

    for path in run_wps_dir.glob("GRIBFILE.*"):
        path.unlink(missing_ok=True)

    for src, ext in zip(files, generate_gribfile_extensions()):
        dst = run_wps_dir / f"GRIBFILE.{ext}"
        link_or_copy(src, dst)

    print(f"Linked {len(files)} GRIB files into {run_wps_dir}")


def copy_met_em_files(run_wps_dir: Path, run_wrf_dir: Path) -> None:
    met_files = sorted(run_wps_dir.glob("met_em.d0*.nc"))
    if not met_files:
        raise FileNotFoundError(
            f"No met_em files found in {run_wps_dir}. Run WPS first (metgrid step)."
        )

    run_wrf_dir.mkdir(parents=True, exist_ok=True)
    for src in met_files:
        shutil.copy2(src, run_wrf_dir / src.name)

    print(f"Copied {len(met_files)} met_em files into {run_wrf_dir}")


def build_mpi_cmd(exe: Path, nproc: int, mpiexec: Path | None) -> List[str]:
    if nproc <= 1:
        return [str(exe)]
    if mpiexec is None:
        raise ValueError("mpiexec path is required for nproc > 1")
    return [str(mpiexec), "-n", str(nproc), str(exe)]


def ensure_runtime_files(dist_wps_dir: Path, run_wps_dir: Path, vtable_name: str) -> None:
    copy_if_needed(
        dist_wps_dir / "geogrid" / "GEOGRID.TBL.ARW",
        run_wps_dir / "geogrid" / "GEOGRID.TBL",
    )
    copy_if_needed(
        dist_wps_dir / "metgrid" / "METGRID.TBL.ARW",
        run_wps_dir / "metgrid" / "METGRID.TBL",
    )
    copy_if_needed(
        dist_wps_dir / "ungrib" / "Variable_Tables" / vtable_name,
        run_wps_dir / "Vtable",
    )


def ensure_wrf_runtime_files(dist_wrf_root: Path, run_wrf_dir: Path) -> None:
    src_dir = dist_wrf_root / "test" / "em_real"
    if not src_dir.exists():
        raise FileNotFoundError(f"WRF runtime source folder missing: {src_dir}")

    # WRF expects a large set of runtime tables/data files in the run directory.
    # Copy everything from em_real except namelist templates and executable wrappers.
    for src in src_dir.iterdir():
        if not src.is_file():
            continue
        name_lower = src.name.lower()
        if name_lower.startswith("namelist.input"):
            continue
        if name_lower.endswith(".exe") or name_lower.endswith(".bat"):
            continue
        copy_if_needed(src, run_wrf_dir / src.name)


def parse_args() -> argparse.Namespace:
    default_work_dir = Path.home() / "Documents" / "gis4wrf"

    parser = argparse.ArgumentParser(description="Run Atlanta WRF simulation")
    parser.add_argument("--work-dir", type=Path, default=default_work_dir)
    parser.add_argument("--project-name", default="atlanta_test")
    parser.add_argument("--skip-wps", action="store_true", help="Skip geogrid/ungrib/metgrid")
    parser.add_argument("--skip-wrf", action="store_true", help="Skip real/wrf")
    parser.add_argument(
        "--grib-dir",
        type=Path,
        default=None,
        help="Directory with GRIB files to link as GRIBFILE.* before ungrib",
    )
    parser.add_argument(
        "--nproc",
        type=int,
        default=1,
        help="MPI process count for geogrid/metgrid/real/wrf. Use >1 only with dmpar builds.",
    )
    parser.add_argument("--mpiexec", type=Path, default=None)
    parser.add_argument(
        "--omp-threads",
        type=int,
        default=1,
        help="OpenMP thread count (use this for multi-CPU with serial builds).",
    )
    parser.add_argument("--clean", action="store_true", help="Remove previous outputs before running")
    parser.add_argument("--vtable", default="Vtable.GFS")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.nproc < 1:
        raise ValueError("--nproc must be >= 1")
    if args.omp_threads < 1:
        raise ValueError("--omp-threads must be >= 1")
    if args.skip_wps and args.skip_wrf:
        print("Nothing to run (--skip-wps and --skip-wrf are both set).")
        return 0

    work_dir = args.work_dir.resolve()
    dist_wps_dir = work_dir / "dist" / "wps"
    dist_wrf_root = work_dir / "dist" / "wrf"
    dist_wrf_main_dir = dist_wrf_root / "main"
    run_dir = work_dir / "projects" / args.project_name
    run_wps_dir = run_dir / "run_wps"
    run_wrf_dir = run_dir / "run_wrf"

    geogrid_exe = dist_wps_dir / "geogrid.exe"
    ungrib_exe = dist_wps_dir / "ungrib.exe"
    metgrid_exe = dist_wps_dir / "metgrid.exe"
    real_exe = dist_wrf_main_dir / "real.exe"
    wrf_exe = dist_wrf_main_dir / "wrf.exe"

    for required in (geogrid_exe, ungrib_exe, metgrid_exe, real_exe, wrf_exe):
        if not required.exists():
            raise FileNotFoundError(f"Missing executable: {required}")

    mpiexec = None
    if args.nproc > 1:
        mpiexec = find_mpiexec(args.mpiexec)
        print(
            "MPI enabled with",
            args.nproc,
            "processes via",
            mpiexec,
            "(requires dmpar WRF/WPS binaries).",
        )

    extra_env: Dict[str, str] = {}
    if args.omp_threads > 1:
        extra_env["OMP_NUM_THREADS"] = str(args.omp_threads)
        extra_env["OMP_PROC_BIND"] = "true"
        extra_env["OMP_PLACES"] = "cores"
        print(f"OpenMP enabled with {args.omp_threads} threads.")

    if args.clean:
        clean_outputs(
            run_wps_dir=run_wps_dir,
            run_wrf_dir=run_wrf_dir,
            clean_wps=not args.skip_wps,
            clean_wrf=not args.skip_wrf,
        )

    run_wps_dir.mkdir(parents=True, exist_ok=True)
    run_wrf_dir.mkdir(parents=True, exist_ok=True)
    ensure_runtime_files(dist_wps_dir, run_wps_dir, args.vtable)

    if not args.skip_wps:
        if args.grib_dir is not None:
            link_grib_files(args.grib_dir, run_wps_dir)
        elif not any(run_wps_dir.glob("GRIBFILE.*")) and not any(run_wps_dir.glob("FILE_*")):
            raise FileNotFoundError(
                "No GRIBFILE.* or FILE_* files in run_wps. "
                "Provide --grib-dir or place linked GRIB files in run_wps."
            )

        geogrid_cmd = build_mpi_cmd(geogrid_exe, args.nproc, mpiexec)
        run_step("geogrid", geogrid_cmd, run_wps_dir, run_wps_dir / "geogrid.stdout.log", extra_env=extra_env)
        run_step("ungrib", [str(ungrib_exe)], run_wps_dir, run_wps_dir / "ungrib.stdout.log", extra_env=extra_env)
        metgrid_cmd = build_mpi_cmd(metgrid_exe, args.nproc, mpiexec)
        run_step("metgrid", metgrid_cmd, run_wps_dir, run_wps_dir / "metgrid.stdout.log", extra_env=extra_env)

    if not args.skip_wrf:
        ensure_wrf_runtime_files(dist_wrf_root, run_wrf_dir)
        copy_met_em_files(run_wps_dir, run_wrf_dir)

        real_cmd = build_mpi_cmd(real_exe, args.nproc, mpiexec)
        wrf_cmd = build_mpi_cmd(wrf_exe, args.nproc, mpiexec)

        run_step("real.exe", real_cmd, run_wrf_dir, run_wrf_dir / "real.stdout.log", extra_env=extra_env)
        run_step("wrf.exe", wrf_cmd, run_wrf_dir, run_wrf_dir / "wrf.stdout.log", extra_env=extra_env)

        wrfout_files = sorted(run_wrf_dir.glob("wrfout_d0*"))
        if not wrfout_files:
            raise RuntimeError("WRF finished without wrfout files.")
        print("\nWRF output files:", len(wrfout_files))
        print("Final wrfout:", wrfout_files[-1].name)

    print("\nAtlanta simulation run completed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
