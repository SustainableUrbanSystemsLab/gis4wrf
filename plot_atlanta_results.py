"""
Plot all numeric WRF output fields for the Atlanta case.

By default this scans:
    ~/Documents/gis4wrf/projects/atlanta_test/run_wrf/wrfout_d01_*

Outputs are written to:
    ~/Documents/gis4wrf/projects/atlanta_test/plots_all_fields

Usage:
    uv run python plot_atlanta_results.py
    uv run python plot_atlanta_results.py --max-vars 20
"""

from __future__ import annotations

import argparse
import html
from datetime import datetime
import math
import re
import sys
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import BoundaryNorm, Normalize, TwoSlopeNorm
from netCDF4 import Dataset, chartostring


SPATIAL_COORDS: Dict[Tuple[str, str], Tuple[str, str]] = {
    ("south_north", "west_east"): ("XLAT", "XLONG"),
    ("south_north", "west_east_stag"): ("XLAT_U", "XLONG_U"),
    ("south_north_stag", "west_east"): ("XLAT_V", "XLONG_V"),
}

ATLANTA_CITIES: Sequence[Tuple[str, float, float]] = (
    ("Atlanta", 33.7490, -84.3880),
    ("ATL Airport", 33.6407, -84.4277),
    ("Sandy Springs", 33.9304, -84.3733),
    ("Marietta", 33.9526, -84.5499),
    ("Roswell", 34.0232, -84.3616),
    ("Decatur", 33.7748, -84.2963),
    ("Smyrna", 33.8839, -84.5144),
    ("Stone Mountain", 33.8053, -84.1477),
)

CITY_LABEL_OFFSETS = {
    "Atlanta": (+0.12, +0.10),
    "ATL Airport": (+0.12, -0.10),
    "Sandy Springs": (+0.12, +0.12),
    "Marietta": (-0.34, +0.08),
    "Roswell": (+0.12, +0.18),
    "Decatur": (+0.12, +0.02),
    "Smyrna": (-0.28, -0.02),
    "Stone Mountain": (+0.12, +0.02),
}

CITY_LABELS = {
    "Atlanta",
    "ATL Airport",
    "Marietta",
    "Stone Mountain",
    "Roswell",
}


@dataclass
class PlotEntry:
    var_name: str
    kind: str
    long_name: str
    units: str
    relative_path: str


def configure_style() -> None:
    plt.style.use("seaborn-v0_8-whitegrid")
    plt.rcParams.update(
        {
            "axes.titlesize": 10,
            "axes.labelsize": 9,
            "xtick.labelsize": 8,
            "ytick.labelsize": 8,
            "figure.titlesize": 13,
            "savefig.facecolor": "white",
        }
    )


def sanitize_filename(name: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_")
    return safe or "variable"


def decode_time_label(ds: Dataset) -> str:
    if "Times" not in ds.variables:
        return Path(ds.filepath()).name
    times = chartostring(ds.variables["Times"][:])
    if np.ndim(times) == 0:
        return str(times)
    return str(times[0])


def is_numeric_variable(var) -> bool:
    dtype = np.dtype(var.dtype)
    return np.issubdtype(dtype, np.number)


def find_spatial_pair(dimensions: Sequence[str]) -> Optional[Tuple[str, str]]:
    dims = list(dimensions)
    if "Time" in dims:
        dims.remove("Time")
    for pair in SPATIAL_COORDS:
        if pair[0] in dims and pair[1] in dims:
            return pair
    return None


def masked_data(var, data: np.ndarray) -> np.ma.MaskedArray:
    arr = np.ma.masked_invalid(np.asarray(data, dtype=np.float64))
    for attr in ("_FillValue", "missing_value"):
        if not hasattr(var, attr):
            continue
        values = np.atleast_1d(np.asarray(getattr(var, attr), dtype=np.float64))
        for value in values:
            arr = np.ma.masked_where(np.isclose(arr, value, equal_nan=True), arr)
    return arr


def robust_limits(values: Sequence[np.ma.MaskedArray]) -> Optional[Tuple[float, float]]:
    packed: List[np.ndarray] = []
    for array in values:
        if np.ma.isMaskedArray(array):
            finite = array.compressed()
        else:
            finite = np.asarray(array).ravel()
            finite = finite[np.isfinite(finite)]
        if finite.size:
            packed.append(finite.astype(np.float64))
    if not packed:
        return None
    merged = np.concatenate(packed)
    vmin, vmax = np.percentile(merged, [2, 98])
    if not np.isfinite(vmin) or not np.isfinite(vmax):
        return None
    if vmin == vmax:
        vmin = float(np.min(merged))
        vmax = float(np.max(merged))
    if vmin == vmax:
        vmin -= 1.0
        vmax += 1.0
    return float(vmin), float(vmax)


def norm_and_cmap(values: Sequence[np.ma.MaskedArray], vmin: float, vmax: float):
    merged_chunks: List[np.ndarray] = []
    for array in values:
        if np.ma.isMaskedArray(array):
            finite = array.compressed()
        else:
            finite = np.asarray(array).ravel()
            finite = finite[np.isfinite(finite)]
        if finite.size:
            merged_chunks.append(finite)

    if not merged_chunks:
        return Normalize(vmin=vmin, vmax=vmax), plt.get_cmap("viridis")

    merged = np.concatenate(merged_chunks)
    sample = merged if merged.size <= 20000 else merged[np.random.default_rng(42).choice(merged.size, 20000, replace=False)]
    rounded = np.round(sample)
    integer_like = np.allclose(sample, rounded, atol=1e-6)

    if integer_like:
        unique = np.unique(rounded.astype(int))
        if 2 <= unique.size <= 20:
            low = unique.min() - 0.5
            high = unique.max() + 0.5
            bounds = np.arange(low, high + 1.0, 1.0)
            bin_count = len(bounds) - 1
            cmap = plt.get_cmap("tab20", max(bin_count, 3))
            return BoundaryNorm(bounds, cmap.N, clip=True), cmap

    if vmin < 0 < vmax:
        return TwoSlopeNorm(vmin=vmin, vcenter=0.0, vmax=vmax), plt.get_cmap("RdBu_r")
    return Normalize(vmin=vmin, vmax=vmax), plt.get_cmap("viridis")


def get_attrs(var) -> Tuple[str, str]:
    long_name = str(getattr(var, "description", "") or getattr(var, "long_name", "") or "")
    units = str(getattr(var, "units", "") or "")
    return long_name, units


def add_atlanta_landmark_background(ax, lat_grid: np.ndarray, lon_grid: np.ndarray) -> None:
    lat_min = float(np.nanmin(lat_grid))
    lat_max = float(np.nanmax(lat_grid))
    lon_min = float(np.nanmin(lon_grid))
    lon_max = float(np.nanmax(lon_grid))
    lat_pad = max(0.05, 0.03 * (lat_max - lat_min))
    lon_pad = max(0.05, 0.03 * (lon_max - lon_min))

    visible: List[Tuple[str, float, float]] = []
    for name, lat, lon in ATLANTA_CITIES:
        if lat_min - lat_pad <= lat <= lat_max + lat_pad and lon_min - lon_pad <= lon <= lon_max + lon_pad:
            visible.append((name, lat, lon))
    if not visible:
        return

    # Subtle map-like context background so landmarks are visible on every variable layer.
    ax.set_facecolor("#f5f8fb")
    ax.scatter(
        [p[2] for p in visible],
        [p[1] for p in visible],
        s=22,
        c="#f97316",
        edgecolors="white",
        linewidths=0.6,
        alpha=0.9,
        zorder=7,
    )

    for name, lat, lon in visible:
        if name not in CITY_LABELS:
            continue
        off_x, off_y = CITY_LABEL_OFFSETS.get(name, (0.10, 0.06))
        ax.text(
            lon + off_x,
            lat + off_y,
            name,
            fontsize=6.5,
            color="#111827",
            zorder=8,
            bbox=dict(boxstyle="round,pad=0.14", facecolor="white", edgecolor="none", alpha=0.55),
        )

    # Approximate metro-area outline around city cluster.
    city_lats = np.array([lat for _, lat, _ in visible], dtype=np.float64)
    city_lons = np.array([lon for _, _, lon in visible], dtype=np.float64)
    center_lat = float(np.mean(city_lats))
    center_lon = float(np.mean(city_lons))
    radius_lat = max(0.45, float(np.max(city_lats) - np.min(city_lats)) * 1.60)
    radius_lon = max(0.55, float(np.max(city_lons) - np.min(city_lons)) * 1.60)
    theta = np.linspace(0.0, 2.0 * np.pi, 260)
    metro_lon = center_lon + radius_lon * np.cos(theta)
    metro_lat = center_lat + radius_lat * np.sin(theta)
    ax.plot(metro_lon, metro_lat, color="white", linewidth=2.0, alpha=0.35, zorder=5)
    ax.plot(metro_lon, metro_lat, color="#1f2937", linewidth=0.9, linestyle=(0, (4, 3)), alpha=0.9, zorder=6)
    ax.text(
        0.01,
        0.92,
        "Metro boundary (approx.)",
        transform=ax.transAxes,
        fontsize=6.3,
        color="#1f2937",
        zorder=8,
        bbox=dict(boxstyle="round,pad=0.14", facecolor="white", edgecolor="none", alpha=0.6),
    )

    ax.text(
        0.01,
        0.99,
        "Metro Atlanta cities",
        transform=ax.transAxes,
        va="top",
        ha="left",
        fontsize=7,
        color="#1f2937",
        bbox=dict(boxstyle="round,pad=0.16", facecolor="white", edgecolor="none", alpha=0.6),
    )


def extract_spatial_slice(ds: Dataset, var_name: str, level_index: int):
    var = ds.variables[var_name]
    dims = list(var.dimensions)
    data = np.asarray(var[:], dtype=np.float64)

    if "Time" in dims:
        t_axis = dims.index("Time")
        data = np.take(data, 0, axis=t_axis)
        dims.pop(t_axis)

    pair = find_spatial_pair(var.dimensions)
    if pair is None:
        raise ValueError("not spatial")

    reduced_labels: List[str] = []
    axis = 0
    while axis < len(dims):
        dim = dims[axis]
        if dim in pair:
            axis += 1
            continue
        size = data.shape[axis]
        idx = min(level_index, size - 1)
        data = np.take(data, idx, axis=axis)
        dims.pop(axis)
        reduced_labels.append(f"{dim}={idx}")

    if dims != list(pair):
        order = [dims.index(pair[0]), dims.index(pair[1])]
        data = np.transpose(data, axes=order)
        dims = [pair[0], pair[1]]

    lat_name, lon_name = SPATIAL_COORDS[pair]
    lat_var = ds.variables[lat_name]
    lon_var = ds.variables[lon_name]

    lat = np.asarray(lat_var[0] if "Time" in lat_var.dimensions else lat_var[:], dtype=np.float64)
    lon = np.asarray(lon_var[0] if "Time" in lon_var.dimensions else lon_var[:], dtype=np.float64)

    ny = min(data.shape[0], lat.shape[0], lon.shape[0])
    nx = min(data.shape[1], lat.shape[1], lon.shape[1])
    data = data[:ny, :nx]
    lat = lat[:ny, :nx]
    lon = lon[:ny, :nx]

    return masked_data(var, data), lat, lon, ", ".join(reduced_labels)


def extract_nonspatial_vector(ds: Dataset, var_name: str):
    var = ds.variables[var_name]
    dims = list(var.dimensions)
    data = np.asarray(var[:], dtype=np.float64)

    if "Time" in dims:
        t_axis = dims.index("Time")
        data = np.take(data, 0, axis=t_axis)
        dims.pop(t_axis)

    # Keep one dimension for plotting. Collapse higher dimensions by taking index 0.
    while data.ndim > 1:
        data = np.take(data, 0, axis=1)
        if len(dims) > 1:
            dims.pop(1)

    return masked_data(var, data), dims


def plot_spatial_variable(
    var_name: str,
    wrf_files: Sequence[Path],
    out_dir: Path,
    level_index: int,
    dpi: int,
    add_landmarks: bool,
) -> Optional[PlotEntry]:
    fields: List[np.ma.MaskedArray] = []
    lats: List[np.ndarray] = []
    lons: List[np.ndarray] = []
    labels: List[str] = []
    level_note = ""
    long_name = ""
    units = ""

    for path in wrf_files:
        with Dataset(path) as ds:
            var = ds.variables[var_name]
            data, lat, lon, reduced = extract_spatial_slice(ds, var_name, level_index)
            fields.append(data)
            lats.append(lat)
            lons.append(lon)
            labels.append(decode_time_label(ds))
            if not long_name and not units:
                long_name, units = get_attrs(var)
            if reduced:
                level_note = reduced

    limits = robust_limits(fields)
    if limits is None:
        return None
    vmin, vmax = limits
    norm, cmap = norm_and_cmap(fields, vmin, vmax)

    nplots = len(fields)
    ncols = min(3, max(1, nplots))
    nrows = int(math.ceil(nplots / ncols))
    fig, axes = plt.subplots(
        nrows=nrows,
        ncols=ncols,
        figsize=(5.2 * ncols, 4.2 * nrows),
        constrained_layout=True,
    )
    axes = np.array(axes).reshape(nrows, ncols)

    mesh = None
    for idx, ax in enumerate(axes.ravel()):
        if idx >= nplots:
            ax.axis("off")
            continue
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message="The input coordinates to pcolormesh are interpreted as cell centers, but are not monotonically increasing or decreasing.*",
                category=UserWarning,
            )
            mesh = ax.pcolormesh(
                lons[idx],
                lats[idx],
                fields[idx],
                shading="auto",
                cmap=cmap,
                norm=norm,
                rasterized=True,
            )
        ax.set_title(labels[idx], fontweight="semibold")
        ax.set_xlabel("Longitude")
        ax.set_ylabel("Latitude")
        ax.grid(alpha=0.3, linewidth=0.4)
        if add_landmarks:
            add_atlanta_landmark_background(ax, lats[idx], lons[idx])

    title = var_name if not long_name else f"{var_name} - {long_name}"
    if level_note:
        title += f" ({level_note})"
    fig.suptitle(title, fontweight="bold")

    if mesh is not None:
        cbar = fig.colorbar(mesh, ax=axes.ravel().tolist(), shrink=0.93, pad=0.02)
        if units:
            cbar.set_label(units)

    out_path = out_dir / "maps" / f"{sanitize_filename(var_name)}.png"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=dpi)
    plt.close(fig)

    rel = out_path.relative_to(out_dir).as_posix()
    return PlotEntry(var_name, "map", long_name, units, rel)


def plot_nonspatial_variable(
    var_name: str,
    wrf_files: Sequence[Path],
    out_dir: Path,
    dpi: int,
) -> Optional[PlotEntry]:
    values: List[np.ma.MaskedArray] = []
    labels: List[str] = []
    dim_name = "index"
    long_name = ""
    units = ""

    for path in wrf_files:
        with Dataset(path) as ds:
            var = ds.variables[var_name]
            data, dims = extract_nonspatial_vector(ds, var_name)
            values.append(data)
            labels.append(decode_time_label(ds))
            if dims:
                dim_name = dims[0]
            if not long_name and not units:
                long_name, units = get_attrs(var)

    if not values:
        return None

    first = values[0]
    fig = None

    if np.ndim(first) == 0:
        series = np.array([float(np.asarray(v)) for v in values], dtype=np.float64)
        if not np.isfinite(series).any():
            return None
        fig, ax = plt.subplots(figsize=(9.0, 4.2), constrained_layout=True)
        ax.plot(labels, series, marker="o", linewidth=1.8, color="#006D77")
        ax.set_xlabel("Time")
        ax.set_ylabel(units or var_name)
        ax.set_title(var_name if not long_name else f"{var_name} - {long_name}", fontweight="bold")
        ax.grid(alpha=0.35)
        for tick in ax.get_xticklabels():
            tick.set_rotation(30)
            tick.set_ha("right")
    else:
        vectors = [np.asarray(v).ravel() for v in values]
        min_len = min(len(v) for v in vectors)
        if min_len == 0:
            return None
        stack = np.stack([v[:min_len] for v in vectors], axis=0)
        stack = np.ma.masked_invalid(stack)
        limits = robust_limits([stack])
        if limits is None:
            return None
        vmin, vmax = limits
        norm, cmap = norm_and_cmap([stack], vmin, vmax)

        fig, ax = plt.subplots(figsize=(10.0, 5.2), constrained_layout=True)
        image = ax.imshow(stack, aspect="auto", origin="lower", cmap=cmap, norm=norm)
        ax.set_title(var_name if not long_name else f"{var_name} - {long_name}", fontweight="bold")
        ax.set_xlabel(dim_name)
        ax.set_ylabel("Time index")
        if len(labels) <= 12:
            ax.set_yticks(np.arange(len(labels)))
            ax.set_yticklabels(labels)
        cbar = fig.colorbar(image, ax=ax, shrink=0.92, pad=0.02)
        if units:
            cbar.set_label(units)

    out_path = out_dir / "series" / f"{sanitize_filename(var_name)}.png"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=dpi)
    plt.close(fig)

    rel = out_path.relative_to(out_dir).as_posix()
    return PlotEntry(var_name, "series", long_name, units, rel)


def write_index(entries: Sequence[PlotEntry], out_dir: Path) -> None:
    generated_at = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")
    cards: List[str] = []
    for entry in sorted(entries, key=lambda e: e.var_name):
        subtitle_parts = []
        if entry.long_name:
            subtitle_parts.append(html.escape(entry.long_name))
        if entry.units:
            subtitle_parts.append(f"Units: {html.escape(entry.units)}")
        subtitle = " | ".join(subtitle_parts) if subtitle_parts else entry.kind
        cards.append(
            (
                "<article class='card'>"
                f"<h3>{html.escape(entry.var_name)}</h3>"
                f"<p>{subtitle}</p>"
                f"<a href='{html.escape(entry.relative_path)}'><img src='{html.escape(entry.relative_path)}' alt='{html.escape(entry.var_name)}'></a>"
                "</article>"
            )
        )

    html_content = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Atlanta WRF Field Plots</title>
  <style>
    :root {{
      --bg: #f5f7fa;
      --fg: #12263a;
      --card: #ffffff;
      --accent: #006d77;
      --muted: #5f6b7a;
    }}
    body {{
      margin: 0;
      font-family: "Segoe UI", Tahoma, sans-serif;
      background: linear-gradient(180deg, #eef4fb 0%, var(--bg) 40%, #ebf6f3 100%);
      color: var(--fg);
    }}
    header {{
      padding: 24px 28px 10px;
    }}
    h1 {{
      margin: 0 0 6px;
      font-size: 1.7rem;
    }}
    p.subtitle {{
      margin: 0;
      color: var(--muted);
    }}
    p.generated {{
      margin-top: 4px;
      font-size: 0.85rem;
    }}
    main {{
      padding: 18px 24px 30px;
      display: grid;
      gap: 14px;
      grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    }}
    .card {{
      background: var(--card);
      border-radius: 12px;
      box-shadow: 0 8px 28px rgba(18, 38, 58, 0.08);
      padding: 12px;
      border: 1px solid rgba(0, 109, 119, 0.15);
    }}
    .card h3 {{
      margin: 2px 0 6px;
      font-size: 1rem;
      color: var(--accent);
      overflow-wrap: anywhere;
    }}
    .card p {{
      margin: 0 0 8px;
      font-size: 0.82rem;
      color: var(--muted);
      min-height: 2.4em;
    }}
    .card img {{
      width: 100%;
      border-radius: 8px;
      display: block;
      border: 1px solid rgba(0,0,0,0.06);
      background: #fff;
    }}
  </style>
</head>
<body>
  <header>
    <h1>Atlanta WRF Output Plots</h1>
    <p class="subtitle">Rendered {len(entries)} numeric variables from wrfout files</p>
    <p class="subtitle generated">Generated {generated_at}</p>
  </header>
  <main>
    {"".join(cards)}
  </main>
</body>
</html>
"""

    (out_dir / "index.html").write_text(html_content, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    default_input = Path.home() / "Documents" / "gis4wrf" / "projects" / "atlanta_test" / "run_wrf"
    default_output = Path.home() / "Documents" / "gis4wrf" / "projects" / "atlanta_test" / "plots_all_fields"
    parser = argparse.ArgumentParser(description="Plot all numeric fields from WRF output")
    parser.add_argument("--input-dir", type=Path, default=default_input)
    parser.add_argument("--output-dir", type=Path, default=default_output)
    parser.add_argument("--pattern", default="wrfout_d01_*")
    parser.add_argument("--level-index", type=int, default=0, help="Vertical index used for 3D fields")
    parser.add_argument("--dpi", type=int, default=180)
    parser.add_argument("--max-vars", type=int, default=None, help="Limit variable count for quick tests")
    parser.add_argument("--no-landmarks", action="store_true", help="Disable Atlanta landmark background overlay on map plots")
    return parser.parse_args()


def main() -> int:
    configure_style()
    args = parse_args()

    input_dir = args.input_dir.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    wrf_files = sorted(input_dir.glob(args.pattern))
    if not wrf_files:
        raise FileNotFoundError(f"No WRF output files found in {input_dir} with pattern {args.pattern}")

    with Dataset(wrf_files[0]) as ds0:
        variable_names = [
            name
            for name, var in ds0.variables.items()
            if name != "Times" and is_numeric_variable(var)
        ]

    variable_names.sort()
    if args.max_vars is not None:
        variable_names = variable_names[: max(0, args.max_vars)]

    print(f"Found {len(wrf_files)} wrfout files")
    print(f"Rendering {len(variable_names)} numeric variables")

    entries: List[PlotEntry] = []
    failures: List[Tuple[str, str]] = []

    for idx, name in enumerate(variable_names, 1):
        print(f"[{idx:03d}/{len(variable_names):03d}] {name}")
        try:
            with Dataset(wrf_files[0]) as ds0:
                pair = find_spatial_pair(ds0.variables[name].dimensions)
            if pair is not None:
                entry = plot_spatial_variable(
                    var_name=name,
                    wrf_files=wrf_files,
                    out_dir=output_dir,
                    level_index=max(0, args.level_index),
                    dpi=args.dpi,
                    add_landmarks=not args.no_landmarks,
                )
            else:
                entry = plot_nonspatial_variable(
                    var_name=name,
                    wrf_files=wrf_files,
                    out_dir=output_dir,
                    dpi=args.dpi,
                )
            if entry is not None:
                entries.append(entry)
        except Exception as exc:  # pragma: no cover - diagnostics for plotting edge cases
            failures.append((name, str(exc)))

    write_index(entries, output_dir)

    print(f"\nCreated {len(entries)} plots in {output_dir}")
    print(f"Index: {output_dir / 'index.html'}")
    if failures:
        print(f"Skipped {len(failures)} variables due to errors:")
        for name, message in failures[:20]:
            print(f"  - {name}: {message}")
        if len(failures) > 20:
            print(f"  ... and {len(failures) - 20} more")
    return 0


if __name__ == "__main__":
    sys.exit(main())
