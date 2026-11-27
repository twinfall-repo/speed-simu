"""The movie of a SPEED run with the train loads of TTB2SPEED: the train runs
under the towers as in the loads, a component of the displacement or of
the velocity spreads over the orthophoto, and the towers' monitored points
move in a plot below:

    python movie/speed_movie.py RUN_DIR SCENE_DIR OUT_DIR low|high [FIELD] [log] [FRAME ...]

FIELD is Disp_x (the default), Disp_y, Disp_z, Vel_x, Vel_y or Vel_z, read
from SPEED's own output in RUN_DIR/VTKOUT on the free surface of surface.py.
RUN_DIR is a run of run_case.sh with monitors.py's output (RUN_DIR/monitors) and
the case's files (its .mate, with the PLOZ and FUNC lines of the loads, and
the load files they name). SCENE_DIR is dtm_voxelization's output of the
case (output/rialba), as for movie.py.

- The train: the first axle reaches each load at the first time its load
  function reaches half its peak (the tapered loads at the ends left out); a line through those (arc length, time) pairs gives
  the head's arc length in time, and the direction it runs.
- The field: the component of FIELD, from the free surface of the voxel
  mesh to a raster on the terrain of the orthophoto, its 2 m lattice refined
  to SAMPLE m: each node takes the value interpolated in x and y on the
  upward face of the surface over it, of several the closest in z: on the
  top of a voxel with SPEED's own biquadratic basis on its 3 x 3 nodes, on a
  slanted face linearly. Then a picture rather than a measurement: a
  normalised Gaussian smoothing whose sigma is SMOOTHING times the element
  size under each node (itself blurred over SEAM m), which rounds off the
  corners between the elements and the steps between the columns where the
  mesh is coarse and keeps the detail where it is fine (0.8 m nodes at the
  towers, 2.3 m around, 7 to 21 m far off); then cubic to PIXEL m, drawn as
  the RGBA texture of the terrain. A diverging colour map, linear up to
  +-the CLIP percentile of |value| over the run, clear at zero and more
  opaque towards it; with log, signed log over DECADES decades up to the
  decade nearest that percentile, clear below them.
- The camera: abreast of the head of the train, out over the lake, for
  FOLLOW s of simulated time; a little farther back (FAR of the way to
  CAMERA) to HOLD s; then over EASE s out to CAMERA, the towers and the
  loads' stretch, to the end. Its path is smoothed over SMOOTH s.
- The labels: matplotlib's Computer Modern and mathtext, as LaTeX, FONT pt at 1920 wide.
- The plot: that component at the points MONITORS of LS.input (the towers),
  with a cursor at the frame's time; the same colours mark them in the view.

The movie runs SLOW times slower than the simulated time; the field is
interpolated linearly between snapshots. low is 960 x 540 at 12 frames a
second, high 1920 x 1080 at 30. Frames go to OUT_DIR/frames, ffmpeg makes
OUT_DIR/speed_<quality>_<FIELD>.mp4; given FRAME numbers, only those, no video.
"""

import re
import subprocess
import sys
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.patheffects as effects
import matplotlib.pyplot as plt
import numpy as np
import pyvista as pv
from PIL import Image
from scipy.ndimage import gaussian_filter, gaussian_filter1d, zoom
from scipy.spatial import cKDTree

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import surface  # noqa: E402  (speed-simu's surface.py: the snapshots of SPEED.xmf)
from movie import railway, scene  # noqa: E402
from train import build, place  # noqa: E402

QUALITY = {"low": ((960, 540), 12), "high": ((1920, 1080), 30)}
SLOW = 2  # the movie runs this many times slower than the simulation
FIELDS = {"Disp": ("u", "m", "displacement"), "Vel": ("v", "m/s", "velocity")}  # SPEED's name: symbol, unit, name
MONITORS = (8, 9, 10, 11, 12)  # the towers' points in LS.input
SAMPLE, PIXEL = 0.5, 0.25  # m: the raster on the terrain the field is taken on, and the one it is drawn at
CANDIDATES = 24  # upward triangles of the surface, nearest by centre, tried for each terrain point
CHUNK = 500_000  # terrain points located at a time: memory
CLIP = 99.9  # the colour scale's end: this percentile of |value| over the run (log: the decade nearest it)
DECADES = 3  # decades of the signed log colour scale (log) below its end
SMOOTHING = 0.5  # the sigma of the field's smoothing, as a fraction of the element size under each point; 0: none
SEAM = 10.0  # m, the sigma over which the element size is blurred first, so that the smoothing changes gradually
PLOT = 0.28  # the plot's share of the frame's height
CAMERA = ((-1080.0, -860.0, 120.0), (-220.0, 90.0, -95.0))  # camera, focal point: the towers and the loads' stretch
# s of simulated time: the camera follows the head of the train up to FOLLOW, eases back over 1 s to a
# farther view, FAR of the way to CAMERA, holds it to HOLD, then eases out to CAMERA over EASE
FOLLOW, FAR, HOLD, EASE = 3.0, 0.075, 6.0, 3.0
SMOOTH = 0.5  # s, the camera's path is smoothed in time over this (a Gaussian's sigma): no jitter from the track's points
FONT = 18  # pt of the labels at 1920 wide, scaled with the width; Computer Modern, as LaTeX
COLOURS = ("#e41a1c", "#ff7f00", "#4daf4a", "#984ea3", "#377eb8")
T0 = time.perf_counter()


def log(message):
    print(f"[{time.perf_counter() - T0:7.1f}s] {message}", flush=True)


def train_timing(run, s, path):
    """(s at t = 0, speed in m/s, signed: + if the train runs as s grows) from the loads."""
    mate = next(run.glob("*.mate"))
    text = mate.read_text()
    ploz = {int(n): np.array([float(x), float(y), float(z)])
            for n, x, y, z in re.findall(r"^\s*PLOZ\s+(\d+)\s+(\S+)\s+(\S+)\s+(\S+)", text, re.M)}
    funcs = {int(n): f for n, f in re.findall(r"^\s*FUNC\s+(\d+)\s+3\s+\d+\s+'([^']+)'", text, re.M)}
    if not funcs:
        raise SystemExit(f"{mate}: no FUNC ... 3 with a load file: not a run with TTB2SPEED loads")
    # an axle is over a load when the load first reaches half its peak: the
    # load files may be non-zero, if tiny, long before (the tails of TTB-2D's
    # loads); the tapered loads at the ends, peaks below a tenth of the median, are left out
    peaks, arrivals = {}, {}
    for n, name in funcs.items():
        f = np.loadtxt(run / name, skiprows=1)
        peaks[n] = np.abs(f[:, 1]).max()
        arrivals[n] = f[np.argmax(np.abs(f[:, 1]) >= 0.5 * peaks[n]), 0]
    keep = [n for n in funcs if peaks[n] >= 0.1 * np.median(list(peaks.values()))]
    pairs = np.array([(s[np.argmin(np.linalg.norm(path - ploz[n], axis=1))], arrivals[n]) for n in keep])
    speed, s0 = np.polyfit(pairs[:, 1], pairs[:, 0], 1)
    misfit = np.abs(pairs[:, 0] - (s0 + speed * pairs[:, 1])).max()
    log(f"train from {len(pairs)} loads of {mate.name} ({len(funcs) - len(keep)} tapered left out): loads over s {pairs[:, 0].min():.0f} to "
        f"{pairs[:, 0].max():.0f} m, head at s {s0:.1f} m at t = 0, {abs(speed) * 3.6:.1f} km/h towards "
        f"{'growing' if speed > 0 else 'decreasing'} s (misfit {misfit:.1f} m)")
    return s0, speed


def follow(path, s, head_s, direction):
    """Camera and focal point abreast of the head of the train, out over the
    lake, a little ahead of it, as movie.py's follow; head_s the head's arc
    length along the railway, direction +-1 the way the train runs along s."""
    at = lambda arc: np.array([np.interp(arc, s, path[:, i]) for i in range(3)])
    ahead = direction * (at(head_s + 20) - at(head_s - 20))
    ahead[2] = 0
    ahead /= np.linalg.norm(ahead)
    lake = -direction * np.cross(ahead, [0, 0, 1])  # the lake lies left of the railway's increasing s
    front = at(head_s - 15 * direction)
    return front + 50 * ahead + 70 * lake + [0, 0, 22], front + [0, 0, 4]


def cameras(path, s, s0, speed, frame_t, per_second):
    """Camera and focal point at every frame: follow() smoothed in time, eased
    to FAR of the way to CAMERA after FOLLOW, then out to CAMERA after HOLD."""
    cam, focal = (gaussian_filter1d(np.array(v), SMOOTH * per_second, axis=0, mode="nearest")
                  for v in zip(*(follow(path, s, s0 + speed * t, np.sign(speed)) for t in frame_t)))
    smooth = lambda a, b: (lambda x: x * x * (3 - 2 * x))(np.clip((frame_t - a) / (b - a), 0, 1))[:, None]
    a = FAR * smooth(FOLLOW, FOLLOW + 1) + (1 - FAR) * smooth(HOLD, HOLD + EASE)
    return (1 - a) * cam + a * np.array(CAMERA[0]), (1 - a) * focal + a * np.array(CAMERA[1])


def candidates(centres, points, test, width):
    """For each point, of the CANDIDATES items nearest by centre in x and y, the
    one test(k, rows) says it falls in, closest in z: (item, gap in z, its data,
    width columns), CHUNK points at a time."""
    tree = cKDTree(centres)
    best, gap = np.full(len(points), -1), np.full(len(points), np.inf)
    data = np.zeros((len(points), width))
    for start in range(0, len(points), CHUNK):
        rows = slice(start, start + CHUNK)
        _, cand = tree.query(points[rows, :2], CANDIDATES)
        b, g, d = best[rows], gap[rows], data[rows]  # views
        for j in range(CANDIDATES):
            k = cand[:, j]
            inside, z, extra = test(k, rows)
            dz = np.abs(z - points[rows, 2])
            better = inside & (dz < g)
            b[better], g[better], d[better] = k[better], dz[better], extra[better]
    return best, gap, data


def locate(points, xyz, quads):
    """Every point under the upward faces of the free surface, as (the 9
    surface points, their weights) of its value, and whether it is under one.
    The surface is SPEED's degree 2: its sub-cell quads come four to an element
    face (surface.py keeps SPEED's order). On a horizontal element face, the
    top of a voxel, the value is the face's biquadratic interpolant on its
    3 x 3 nodes, SPEED's own; on a slanted one, linear on the sub-quads'
    triangles. Of several faces over a point, the closest in z."""
    if len(quads) % 4:
        raise SystemExit(f"{len(quads)} surface quads, not four to an element face: not SPEED degree 2")
    groups = quads.reshape(-1, 4, 4)
    a, b, d = (xyz[groups[:, 0, i]] for i in (0, 1, 3))
    normal = np.cross(b - a, d - a)
    nz = np.abs(normal[:, 2]) / np.linalg.norm(normal, axis=1)
    # the horizontal faces that are rectangles in x and y: their 3 x 3 nodes in a grid, x then y;
    # the others (the trapezoids where the voxels change size) go with the slanted ones
    flat = groups[nz > 0.999]
    p = xyz[flat.reshape(-1, 16)]
    lo, hi = p[..., :2].min(1), p[..., :2].max(1)
    ij = np.rint((p[..., :2] - lo[:, None]) / (hi - lo)[:, None] * 2)
    rect = np.all(np.abs(p[..., :2] - (lo[:, None] + ij * (hi - lo)[:, None] / 2)) < 1e-3, (1, 2)) \
        & (np.ptp(p[..., 2], axis=1) < 1e-3)
    slanted = np.concatenate([groups[(nz > 0.3) & (nz <= 0.999)], flat[~rect]])
    flat, p, lo, hi, ij = flat[rect], p[rect], lo[rect], hi[rect], ij[rect].astype(int)
    ids = flat.reshape(-1, 16)
    grid = np.full((len(flat), 3, 3), -1)
    grid[np.repeat(np.arange(len(flat)), 16), ij[..., 0].ravel(), ij[..., 1].ravel()] = ids.ravel()
    if (grid < 0).any():
        raise SystemExit("rectangular element faces whose nodes do not fill a 3 x 3 grid: not SPEED degree 2")
    ztop = p[:, 0, 2]

    def in_flat(k, rows):
        xi = 2 * (points[rows, :2] - lo[k]) / (hi[k] - lo[k]) - 1
        return np.all(np.abs(xi) <= 1 + 1e-9, 1), ztop[k], xi

    best, gap, xi = candidates((lo + hi) / 2, points, in_flat, 2)
    basis = lambda s: np.stack([s * (s - 1) / 2, 1 - s * s, s * (s + 1) / 2], -1)
    weights = (basis(xi[:, 0])[:, :, None] * basis(xi[:, 1])[:, None, :]).reshape(-1, 9)
    nodes = grid[np.maximum(best, 0)].reshape(-1, 9)
    # the slanted faces: linear on the two triangles of each sub-quad
    tri = np.vstack([slanted.reshape(-1, 4)[:, [0, 1, 2]], slanted.reshape(-1, 4)[:, [0, 2, 3]]])
    ta, tb, tc = (xyz[tri[:, i]] for i in range(3))

    def in_tri(k, rows):
        e1, e2, r = tb[k, :2] - ta[k, :2], tc[k, :2] - ta[k, :2], points[rows, :2] - ta[k, :2]
        with np.errstate(divide="ignore", invalid="ignore"):
            det = e1[:, 0] * e2[:, 1] - e2[:, 0] * e1[:, 1]
            l1 = (r[:, 0] * e2[:, 1] - e2[:, 0] * r[:, 1]) / det
            l2 = (e1[:, 0] * r[:, 1] - r[:, 0] * e1[:, 1]) / det
        l = np.column_stack([1 - l1 - l2, l1, l2])
        return l.min(1) >= -1e-9, (l * np.stack([ta[k, 2], tb[k, 2], tc[k, 2]], 1)).sum(1), l

    t_best, t_gap, lam = candidates(((ta + tb + tc) / 3)[:, :2], points, in_tri, 3)
    use = (t_best >= 0) & (t_gap < gap)
    nodes[use] = np.column_stack([tri[t_best[use]], np.repeat(tri[t_best[use], :1], 6, 1)])
    weights[use] = np.column_stack([lam[use], np.zeros((use.sum(), 6))])
    found = (best >= 0) | (t_best >= 0)
    gap = np.where(use, t_gap, gap)
    area = 0.5 * np.linalg.norm(np.cross(tb - ta, tc - ta), axis=1)
    size = np.where(use, 2 * np.sqrt(2 * area[np.maximum(t_best, 0)]), (hi - lo).mean(1)[np.maximum(best, 0)])
    size[~found] = np.median(size[found])
    log(f"field on {len(points):,} terrain points: {len(flat):,} horizontal element faces (biquadratic), "
        f"{len(slanted):,} slanted or not rectangles (linear, {(~rect).sum():,} horizontal), "
        f"{len(groups) - len(flat) - len(slanted):,} walls left out; "
        f"{(found & ~use).mean():.2%} of the points on a horizontal face, {use.mean():.2%} on a slanted one, "
        f"{(~found).sum():,} on none (left clear); terrain to face in z {np.median(gap[found]):.1f} m median, "
        f"{np.percentile(gap[found], 99):.1f} m at 99%; element size under them {np.percentile(size, 5):.2f} to "
        f"{np.percentile(size, 95):.1f} m (5 to 95%)")
    return nodes, weights, found, size


def blur(img, sigma):
    """img smoothed by a Gaussian of sigma pixels; past 4 pixels on a copy
    coarser by a power of 2, brought back linearly."""
    if sigma <= 4:
        return gaussian_filter(img, sigma, mode="nearest")
    f = 2 ** int(np.log2(sigma / 2))
    h, w = img.shape
    pad = np.pad(img, ((0, -h % f), (0, -w % f)), mode="edge")
    small = pad.reshape(pad.shape[0] // f, f, pad.shape[1] // f, f).mean((1, 3))
    return zoom(gaussian_filter(small, sigma / f, mode="nearest"), f, order=1)[:h, :w]


def smoother(size, found):
    """smooth(v): v on the SAMPLE raster smoothed by a normalised Gaussian
    whose sigma is SMOOTHING x the element size under each pixel: blurs at
    sigmas a factor 2 apart, each pixel blending the two that bracket its own.
    Where the mesh is fine it keeps the detail; where it is coarse it rounds
    off the corners between the elements and the steps between the columns."""
    sigma = SMOOTHING * blur(size, SEAM / SAMPLE) / SAMPLE  # pixels; the element size blurred, or seams show where it jumps
    levels = sigma.min() * 2.0 ** np.arange(int(np.ceil(np.log2(sigma.max() / sigma.min()))) + 1)
    position = np.log2(sigma / levels[0])
    lower = np.minimum(position.astype(int), max(len(levels) - 2, 0))
    upper = np.minimum(lower + 1, len(levels) - 1)
    frac = np.clip(position - lower, 0, 1)
    mask = found.astype(float)
    norms = [np.maximum(blur(mask, s), 1e-6) for s in levels]
    log(f"smoothing: sigma {SMOOTHING:g} x element size, {sigma.min() * SAMPLE:.2f} to {sigma.max() * SAMPLE:.1f} m, "
        f"blurs at {', '.join(f'{s * SAMPLE:.2g}' for s in levels)} m")

    def smooth(v):
        data = np.where(found, v, 0.0)
        out = np.zeros_like(data)
        for k, s in enumerate(levels):
            weight = np.where(lower == k, 1 - frac, 0) + np.where(upper == k, frac, 0)
            if weight.any():
                out += weight * blur(data, s) / norms[k]
        return out
    return smooth


def monitors(run, column, label):
    """{point: (t, value)} of the column (ux, vx, ...) of monitors.py at MONITORS, and their coordinates."""
    series, where = {}, {}
    for p in MONITORS:
        path = run / "monitors" / f"point_{p:02d}.txt"
        head = path.read_text().splitlines()[:2]
        where[p] = np.array([float(v) for v in re.findall(r"x (\S+) y (\S+) z (\S+)", head[0])[0]])
        columns = head[1].lstrip("# ").split()
        data = np.loadtxt(path)
        if column not in columns:
            raise SystemExit(f"{path}: no column {column} (has {columns}): set OPTIOUT in SPEED.input")
        series[p] = (data[:, 0], data[:, columns.index(column)])
    log(f"monitors {MONITORS}: {len(series[MONITORS[0]][0])} times each, |{label}| up to "
        f"{max(np.abs(v).max() for _, v in series.values()):.3e}")
    return series, where


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) < 4 or argv[3] not in QUALITY:
        raise SystemExit(__doc__)
    run, scene_dir, out, quality = Path(argv[0]), Path(argv[1]), Path(argv[2]), argv[3]
    logscale = "log" in argv[4:]
    chosen = [a for a in argv[4:] if not a.isdigit() and a != "log"] or ["Disp_x"]
    only = [int(f) for f in argv[4:] if f.isdigit()]
    name, axis = chosen[0].split("_") if "_" in chosen[0] else (chosen[0], "")
    if name not in FIELDS or axis not in ("x", "y", "z") or len(chosen) > 1:
        raise SystemExit(f"field {' '.join(chosen)}: not one of Disp_x, ..., Vel_z\n{__doc__}")
    component = "xyz".index(axis)
    symbol_letter, unit, long_name = FIELDS[name]
    label = f"{symbol_letter}_{axis}"
    log(f"field {name}_{axis}: {label} ({unit}) of the {long_name}, from {run / 'VTKOUT'}")
    (width, height), fps = QUALITY[quality]
    frames_dir = out / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    view_h = int(height * (1 - PLOT)) // 2 * 2
    plot_h = height - view_h

    snaps = surface.snapshots(run / "VTKOUT")
    steps = np.array([st for st, _ in snaps])
    times = np.array([t for _, t in snaps])
    frame_t = np.arange(0, times[-1], 1 / (fps * SLOW))
    log(f"{run}: {len(snaps)} snapshots to t {times[-1]:g} s; {quality} {width} x {height}, "
        f"{len(frame_t)} frames at {fps} fps, {SLOW}x slower than the simulation")

    track = np.loadtxt(scene_dir / "railway.csv")
    s, path = track[:, 0], track[:, 1:4]
    s0, speed = train_timing(run, s, path)
    log(f"camera: follows the head to t {FOLLOW:g} s (s {s0:.0f} to {s0 + speed * FOLLOW:.0f} m), smoothed over "
        f"{SMOOTH:g} s; {FAR:g} of the way to {CAMERA} from t {FOLLOW + 1:g} to {HOLD:g} s; all the way by t {HOLD + EASE:g} s")
    cams, focals = cameras(path, s, s0, speed, frame_t, fps * SLOW)
    if speed < 0:  # place() puts the cars behind the head towards smaller s: run along the reversed track
        s_run, path_run, head = s[-1] - s[::-1], path[::-1], lambda t: s[-1] - (s0 + speed * t)
    else:
        s_run, path_run, head = s, path, lambda t: s0 + speed * t

    # the field, from the free surface to the terrain
    vtk = run / "VTKOUT"
    ids_file = run / "surface" / "ids.bin"
    if ids_file.exists():  # surface.py's: the free surface's points among SPEED's
        ids = np.fromfile(ids_file, "<i8")
        xyz = np.fromfile(run / "surface" / "points.bin", "<f8").reshape(-1, 3)
        quads = np.fromfile(run / "surface" / "quads.bin", "<i4").reshape(-1, 4)
        log(f"free surface from {ids_file}: {len(ids):,} points, {len(quads):,} quadrilaterals")
    else:
        log(f"no {ids_file}: the free surface from the mesh, as surface.py does")
        ids, xyz, quads = surface.surface(vtk)
    plotter = scene(scene_dir, (width, view_h))
    terrain = plotter.meshes[0]
    # the SAMPLE raster: the terrain's 2 m lattice refined, a point (and a height) per node
    refine = int(round(np.log2(2.0 / SAMPLE)))
    fine = terrain.subdivide(refine, "linear") if refine > 0 else terrain
    corner = terrain.points[:, :2].min(0)
    ij = np.rint((fine.points[:, :2] - corner) / SAMPLE).astype(int)
    shape = tuple(ij.max(0)[::-1] + 1)  # rows y, columns x
    if np.abs(fine.points[:, :2] - corner - ij * SAMPLE).max() > 1e-3 or len(np.unique(ij, axis=0)) != np.prod(shape):
        raise SystemExit(f"the terrain refined {refine} times is not a full {SAMPLE} m lattice")
    points = np.empty((*shape, 3))
    points[ij[:, 1], ij[:, 0]] = fine.points
    log(f"field raster: {shape[1]} x {shape[0]} nodes at {SAMPLE:g} m (the terrain refined {refine} times), "
        f"drawn at {PIXEL:g} m")
    nodes, weights, found, size = locate(points.reshape(-1, 3), xyz, quads)
    nodes, weights = nodes.astype(np.int32), weights.astype(np.float32)
    found, size = found.reshape(shape), size.reshape(shape)
    smooth = smoother(size, found) if SMOOTHING else None
    up = SAMPLE / PIXEL
    drawn = (int((shape[0] - 1) * up) + 1, int((shape[1] - 1) * up) + 1)
    visible = zoom(found.astype(np.uint8), (drawn[0] / shape[0], drawn[1] / shape[1]), order=0) > 0
    cache = {}

    def field(step, fine_raster=True):
        """The field at a snapshot on the SAMPLE raster, smoothed; on the PIXEL raster (cubic) if fine_raster."""
        if (step, fine_raster) in cache:
            return cache[step, fine_raster]
        u = np.asarray(np.memmap(vtk / f"{name}_{step:08d}.bin", "<f4", "r").reshape(-1, 3)[ids, component], np.float32)
        v = (u[nodes] * weights).sum(1).reshape(shape)
        v = smooth(v) if smooth else np.where(found, v, 0.0)
        if fine_raster:
            v = zoom(v, (drawn[0] / shape[0], drawn[1] / shape[1]), order=3).astype(np.float32)
            v[~visible] = np.nan
        else:
            v[~found] = np.nan
        if len(cache) > 3:
            cache.pop(next(iter(cache)))
        cache[step, fine_raster] = v
        return v

    # the colour scale from 40 snapshots, every 4th node each way: 40 whole rasters would not fit in memory
    sample = [np.abs(field(st, False)[::4, ::4]).astype(np.float32).ravel() for st in steps[::max(1, len(steps) // 40)]]
    cache.clear()
    top = np.nanpercentile(np.concatenate(sample), CLIP)
    if logscale:
        clip = 10.0 ** np.round(np.log10(top))
        floor = clip / 10**DECADES
        log(f"colour scale: signed log from {floor:.0e} to {clip:.0e} {unit}, the decade nearest the "
            f"{CLIP:g} percentile of |{label}| on the terrain, {top:.3e}")
    else:
        clip = top
        log(f"colour scale: linear to +-{clip:.3e} {unit}, the {CLIP:g} percentile of |{label}| on the terrain")

    def shade(v):
        """v in -1 to 1: linear to +-clip, or the signed log, 0 below floor, +-1 from clip."""
        if not logscale:
            return np.clip(v / clip, -1, 1)
        with np.errstate(divide="ignore", invalid="ignore"):
            return np.sign(v) * np.clip(np.log10(np.abs(v) / floor) / DECADES, 0, 1)

    colours = (plt.get_cmap("RdBu_r")(np.linspace(0, 1, 256)) * 255).astype(np.uint8)
    ramp = np.abs(np.linspace(-1, 1, 256))
    colours[:, 3] = (np.minimum(1, ramp * 2.5) if logscale else np.sqrt(ramp)) * 0.85 * 255  # clear at zero

    def texture_of(v):
        """The RGBA texture of v on the PIXEL raster, clear where there is no field; north up."""
        s = shade(v)
        rgba = colours[np.rint((np.nan_to_num(s) + 1) * 127.5).astype(np.uint8)]
        rgba[np.isnan(s), 3] = 0
        tex = pv.Texture(np.ascontiguousarray(rgba[::-1]))
        tex.interpolate = True
        return tex

    # the overlay: the terrain just above the photo, the field's raster as its texture
    overlay = terrain.copy()
    overlay.point_data.clear()
    overlay = overlay.extract_cells(np.abs(overlay.cell_normals[:, 2]) >= 0.05).extract_surface()  # not the DTM's skirt
    overlay.points[:, 2] += 0.5
    extent = (np.array(drawn[::-1]) - 1) * PIXEL
    overlay.active_texture_coordinates = (overlay.points[:, :2] - corner + PIXEL / 2) / (extent + PIXEL)
    field_actor = plotter.add_mesh(overlay, texture=texture_of(field(steps[0])), ambient=0.6, diffuse=0.4)
    railway(plotter, scene_dir, track, (width, view_h))
    cars, texture = build()
    train = place(cars, path_run, s_run, head(0))
    plotter.add_mesh(train, texture=texture, ambient=0.35, diffuse=0.7)
    series, where = monitors(run, f"{symbol_letter}{axis}", label)
    for p, c in zip(MONITORS, COLOURS):
        plotter.add_mesh(pv.Sphere(radius=4.0, center=where[p]), color=c, ambient=0.6)

    # the frame, all in matplotlib: the view, its time and colour bar over it, the plot below
    fs = FONT * width / 1920
    plt.rcParams.update({"font.family": "serif", "font.serif": ["cmr10"], "mathtext.fontset": "cm",
                         "axes.formatter.use_mathtext": True, "axes.unicode_minus": False,
                         "font.size": fs, "axes.labelsize": fs, "xtick.labelsize": 0.85 * fs,
                         "ytick.labelsize": 0.85 * fs, "legend.fontsize": 0.85 * fs})
    symbol = f"${label}$"
    fig = plt.figure(figsize=(width / 100, height / 100), dpi=100)
    ax_view = fig.add_axes((0, plot_h / height, 1, view_h / height))
    ax_view.set_axis_off()
    image = ax_view.imshow(np.zeros((view_h, width, 3), np.uint8), aspect="auto", interpolation="none")
    halo = [effects.withStroke(linewidth=0.12 * fs, foreground="black")]
    stamp = ax_view.text(0.012, 0.95, "", transform=ax_view.transAxes, va="top", color="white",
                         fontsize=1.2 * fs, path_effects=halo)
    bar_ax = ax_view.inset_axes((0.62, 0.86, 0.34, 0.04))
    bar = fig.colorbar(plt.cm.ScalarMappable(plt.Normalize(-1, 1), "RdBu_r"), cax=bar_ax,
                       orientation="horizontal")
    if logscale:
        exponents = np.round(np.log10(clip)) - np.arange(DECADES + 1)
        bar.set_ticks(np.concatenate([-np.linspace(1, 0, DECADES + 1), np.linspace(0, 1, DECADES + 1)[1:]]),
                      labels=[f"$-10^{{{e:.0f}}}$" for e in exponents[:-1]] + [f"$\\pm 10^{{{exponents[-1]:.0f}}}$"]
                      + [f"$10^{{{e:.0f}}}$" for e in exponents[::-1][1:]])
    else:
        e = np.floor(np.log10(clip))
        bar.set_ticks([-1, -0.5, 0, 0.5, 1], labels=[f"${v * clip / 10**e:.2g}$" for v in (-1, -0.5, 0, 0.5, 1)])
        bar.ax.text(1.0, -1.6, f"$\\times 10^{{{e:.0f}}}$", transform=bar.ax.transAxes, ha="right", va="top",
                    color="white", path_effects=halo)
    bar.ax.xaxis.set_tick_params(color="white", labelcolor="white")
    bar.ax.xaxis.get_offset_text().set(color="white", path_effects=halo)
    for tick in bar.ax.get_xticklabels():
        tick.set_path_effects(halo)
    bar.set_label(f"{symbol} ({unit})", color="white", path_effects=halo)
    bar.ax.xaxis.set_label_position("top")
    left, bottom, top = 5.5 * fs, 3.0 * fs, 1.8 * fs  # px round the plot: tick labels, axis labels, the 1e-6 above
    ax = fig.add_axes((left / width, bottom / height, 1 - 1.4 * left / width, (plot_h - bottom - top) / height))
    for (p, (t, v)), c in zip(series.items(), COLOURS):
        ax.plot(t, v, color=c, lw=1.5, label=f"point {p}")
    cursor = ax.axvline(0, color="k", lw=1.2)
    ax.set_xlim(0, times[-1])
    ax.set_xlabel("$t$ (s)", labelpad=1)
    ax.set_ylabel(f"{symbol} ({unit})")
    ax.ticklabel_format(axis="y", style="sci", scilimits=(0, 0))
    ax.legend(loc="upper right", ncol=len(MONITORS), framealpha=0.85, edgecolor="none")
    ax.grid(alpha=0.3)

    for n in only or range(len(frame_t)):
        t = frame_t[n]
        k = min(np.searchsorted(times, t, side="right") - 1, len(times) - 2)
        a = (t - times[k]) / (times[k + 1] - times[k])
        field_actor.texture = texture_of((1 - a) * field(steps[k]) + a * field(steps[k + 1]))
        train.points = place(cars, path_run, s_run, head(t)).points
        cam, focal = cams[n], focals[n]
        plotter.camera_position = [tuple(cam), tuple(focal), (0, 0, 1)]
        plotter.camera.clipping_range = (5.0, 12000.0)  # the near plane far enough for the overlay, 0.5 m up, not to flicker
        plotter.render()
        image.set_data(plotter.screenshot(return_img=True)[:, :, :3])
        stamp.set_text(f"$t = {t:.2f}$ s,  train at {abs(speed) * 3.6:.0f} km/h,  {symbol} of the {long_name}")
        cursor.set_xdata([t, t])
        fig.canvas.draw()
        Image.fromarray(np.asarray(fig.canvas.buffer_rgba())[..., :3]).save(frames_dir / f"frame_{n:05d}.png")
        if only or n % 50 == 0:
            log(f"  frame {n}/{len(frame_t)}: t {t:.2f} s (snapshots {steps[k]}-{steps[k + 1]}), "
                f"head at s {s0 + speed * t:.0f} m, camera {cam.round(0)} -> {focal.round(0)}")
    plotter.close()
    if only:
        return

    try:
        import imageio_ffmpeg
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        ffmpeg = "ffmpeg"
    video = out / f"speed_{quality}_{name}_{axis}{'_log' if logscale else ''}.mp4"
    command = [ffmpeg, "-y", "-loglevel", "error", "-framerate", str(fps),
               "-i", str(frames_dir / "frame_%05d.png"), "-c:v", "libx264", "-crf", "18",
               "-pix_fmt", "yuv420p", str(video)]
    log(" ".join(command))
    subprocess.run(command, check=True)
    log(f"wrote {video}: {video.stat().st_size / 1024**2:.1f} MB")


if __name__ == "__main__":
    main()
