"""The movie of a SPEED run with the train loads of TTB2SPEED: the train runs
under the towers as in the loads, the displacement spreads over the
orthophoto, and the towers' monitored points move in a plot below:

    python movie/speed_movie.py RUN_DIR SCENE_DIR OUT_DIR low|high [FRAME ...]

RUN_DIR is a run of run_case.sh with surface.py's output (RUN_DIR/surface,
the displacement on the free surface), monitors.py's (RUN_DIR/monitors) and
the case's files (its .mate, with the PLOZ and FUNC lines of the loads, and
the load files they name). SCENE_DIR is dtm_voxelization's output of the
case (output/rialba), as for movie.py.

- The train: the first axle reaches each load at the first time its load
  function reaches half its peak (the tapered loads at the ends left out); a line through those (arc length, time) pairs gives
  the head's arc length in time, and the direction it runs.
- The field: the component COMPONENT of the displacement, from the free
  surface of the voxel mesh to the terrain of the orthophoto (every 2 m):
  each terrain point takes the inverse-distance mean of its NEIGHBOURS nearest
  surface points, and none (transparent) farther than REACH m from all of
  them. A diverging colour map, transparent around zero and opaque towards
  +-the CLIP percentile of |value| over the run, over the orthophoto.
- The camera: abreast of the head of the train, out over the lake, for
  FOLLOW s of simulated time, then over EASE s out to CAMERA, the towers and
  the loads' stretch, to the end.
- The plot: that component at the points MONITORS of LS.input (the towers),
  with a cursor at the frame's time; the same colours mark them in the view.

The movie runs SLOW times slower than the simulated time; the field is
interpolated linearly between snapshots. low is 960 x 540 at 12 frames a
second, high 1920 x 1080 at 30. Frames go to OUT_DIR/frames, ffmpeg makes
OUT_DIR/speed_<quality>.mp4; given FRAME numbers, only those, no video.
"""

import re
import subprocess
import sys
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pyvista as pv
from PIL import Image
from scipy.spatial import cKDTree

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import surface  # noqa: E402  (speed-simu's surface.py: the snapshots of SPEED.xmf)
from movie import railway, scene  # noqa: E402
from train import build, place  # noqa: E402

QUALITY = {"low": ((960, 540), 12), "high": ((1920, 1080), 30)}
SLOW = 2  # the movie runs this many times slower than the simulation
COMPONENT, LABEL = 0, "u_x"  # the displacement's component shown, and its name
MONITORS = (8, 9, 10, 11, 12)  # the towers' points in LS.input
NEIGHBOURS, REACH = 4, 50.0  # surface points averaged per terrain point; m beyond which none (the 42 m cells far from the towers stand up to ~20 m off the DTM)
CLIP = 99.5  # the colour scale's end: this percentile of |value| over the run
PLOT = 0.28  # the plot's share of the frame's height
CAMERA = ((-1080.0, -860.0, 120.0), (-220.0, 90.0, -95.0))  # camera, focal point: the towers and the loads' stretch
FOLLOW, EASE = 4.0, 3.0  # s of simulated time: the camera follows the train's head, then eases out to CAMERA
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
    k = np.searchsorted(s, head_s)
    ahead = direction * (path[min(k + 10, len(s) - 1)] - path[max(k - 10, 0)])
    ahead[2] = 0
    ahead /= np.linalg.norm(ahead)
    lake = -direction * np.cross(ahead, [0, 0, 1])  # the lake lies left of the railway's increasing s
    front = np.array([np.interp(head_s - 15 * direction, s, path[:, i]) for i in range(3)])
    return front + 50 * ahead + 70 * lake + [0, 0, 22], front + [0, 0, 4]


def camera(path, s, head_s, direction, t):
    """follow() up to FOLLOW s, a smoothstep to CAMERA over the next EASE s."""
    cam, focal = follow(path, s, head_s, direction)
    a = np.clip((t - FOLLOW) / EASE, 0, 1)
    a = a * a * (3 - 2 * a)
    return (1 - a) * cam + a * np.array(CAMERA[0]), (1 - a) * focal + a * np.array(CAMERA[1])


def monitors(run):
    """{point: (t, value)} of COMPONENT of the displacement at MONITORS, and their coordinates."""
    series, where = {}, {}
    for p in MONITORS:
        path = run / "monitors" / f"point_{p:02d}.txt"
        head = path.read_text().splitlines()[:2]
        where[p] = np.array([float(v) for v in re.findall(r"x (\S+) y (\S+) z (\S+)", head[0])[0]])
        columns = head[1].lstrip("# ").split()
        data = np.loadtxt(path)
        series[p] = (data[:, 0], data[:, columns.index(["ux", "uy", "uz"][COMPONENT])])
    log(f"monitors {MONITORS}: {len(series[MONITORS[0]][0])} times each, |{LABEL}| up to "
        f"{max(np.abs(v).max() for _, v in series.values()):.3e} m")
    return series, where


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) < 4 or argv[3] not in QUALITY:
        raise SystemExit(__doc__)
    run, scene_dir, out, quality = Path(argv[0]), Path(argv[1]), Path(argv[2]), argv[3]
    only = [int(f) for f in argv[4:]]
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
    log(f"camera: follows the head for t < {FOLLOW:g} s (s {s0:.0f} to {s0 + speed * FOLLOW:.0f} m), "
        f"eases out to {CAMERA} by t {FOLLOW + EASE:g} s")
    if speed < 0:  # place() puts the cars behind the head towards smaller s: run along the reversed track
        s_run, path_run, head = s[-1] - s[::-1], path[::-1], lambda t: s[-1] - (s0 + speed * t)
    else:
        s_run, path_run, head = s, path, lambda t: s0 + speed * t

    # the field, from the free surface to the terrain
    xyz = np.fromfile(run / "surface" / "points.bin", "<f8").reshape(-1, 3)
    plotter = scene(scene_dir, (width, view_h))
    terrain = plotter.meshes[0]
    dist, near = cKDTree(xyz).query(terrain.points, NEIGHBOURS)
    weight = 1 / np.maximum(dist, 1e-3)
    weight /= weight.sum(1)[:, None]
    outside = dist[:, 0] > REACH
    log(f"terrain {terrain.n_points:,} points from {len(xyz):,} surface points: nearest within "
        f"{np.median(dist[:, 0]):.2f} m (median), {np.percentile(dist[:, 0], 99):.2f} m (99%); "
        f"{outside.sum():,} beyond {REACH:g} m, left clear")

    def field(step):
        u = np.fromfile(run / "surface" / f"Disp_{step:08d}.bin", "<f4").reshape(-1, 3)[:, COMPONENT]
        v = (u[near] * weight).sum(1)
        v[outside] = np.nan
        return v

    sample = [field(st) for st in steps[::max(1, len(steps) // 40)]]
    clip = np.nanpercentile(np.abs(np.concatenate(sample)), CLIP)
    log(f"colour scale +-{clip:.3e} m, the {CLIP:g} percentile of |{LABEL}| on the terrain")
    overlay = terrain.copy()
    overlay.points[:, 2] += 0.5  # just above the photo
    overlay.point_data.clear()
    overlay[LABEL] = field(steps[0])
    lut = pv.LookupTable(cmap="RdBu_r", n_values=256, scalar_range=(-clip, clip))
    rgba = lut.values.copy()
    rgba[:, 3] = np.minimum(1, np.abs(np.linspace(-1, 1, 256)) * 1.6) * 0.85 * 255  # clear at zero
    lut.values = rgba
    lut.nan_opacity = 0.0
    plotter.add_mesh(overlay, scalars=LABEL, cmap=lut, clim=(-clip, clip), ambient=0.6, diffuse=0.4, show_scalar_bar=True,
                     scalar_bar_args=dict(title=f"{LABEL} (m)", fmt="%.1e", position_x=0.6, position_y=0.86,
                                          width=0.33, height=0.06, title_font_size=14, label_font_size=12,
                                          color="white"))
    railway(plotter, scene_dir, track, (width, view_h))
    cars, texture = build()
    train = place(cars, path_run, s_run, head(0))
    plotter.add_mesh(train, texture=texture, ambient=0.35, diffuse=0.7)
    series, where = monitors(run)
    for p, c in zip(MONITORS, COLOURS):
        plotter.add_mesh(pv.Sphere(radius=4.0, center=where[p]), color=c, ambient=0.6)
    stamp = plotter.add_text("", position=(12, view_h - 30), font_size=12, color="white")

    fig, ax = plt.subplots(figsize=(width / 100, plot_h / 100), dpi=100)
    for (p, (t, v)), c in zip(series.items(), COLOURS):
        ax.plot(t, v, color=c, lw=1.2, label=f"tower point {p}")
    cursor = ax.axvline(0, color="k", lw=1)
    ax.set_xlim(0, times[-1])
    ax.set_xlabel("t (s)")
    ax.set_ylabel(f"{LABEL} (m)")
    ax.ticklabel_format(axis="y", style="sci", scilimits=(0, 0))
    ax.legend(loc="upper right", ncol=len(MONITORS), fontsize=7, frameon=False)
    ax.grid(alpha=0.3)
    fig.tight_layout(pad=0.4)

    for n in only or range(len(frame_t)):
        t = frame_t[n]
        k = min(np.searchsorted(times, t, side="right") - 1, len(times) - 2)
        a = (t - times[k]) / (times[k + 1] - times[k])
        overlay[LABEL] = (1 - a) * field(steps[k]) + a * field(steps[k + 1])
        train.points = place(cars, path_run, s_run, head(t)).points
        cam, focal = camera(path, s, s0 + speed * t, np.sign(speed), t)
        plotter.camera_position = [tuple(cam), tuple(focal), (0, 0, 1)]
        plotter.camera.clipping_range = (1.0, 12000.0)
        stamp.SetInput(f"t = {t:5.2f} s   train at {abs(speed) * 3.6:.0f} km/h   {LABEL} of the displacement")
        plotter.render()
        view = plotter.screenshot(return_img=True)
        cursor.set_xdata([t, t])
        fig.canvas.draw()
        plot = np.asarray(fig.canvas.buffer_rgba())[..., :3]
        Image.fromarray(np.vstack([view[:, :, :3], plot])).save(frames_dir / f"frame_{n:05d}.png")
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
    video = out / f"speed_{quality}.mp4"
    command = [ffmpeg, "-y", "-loglevel", "error", "-framerate", str(fps),
               "-i", str(frames_dir / "frame_%05d.png"), "-c:v", "libx264", "-crf", "18",
               "-pix_fmt", "yuv420p", str(video)]
    log(" ".join(command))
    subprocess.run(command, check=True)
    log(f"wrote {video}: {video.stat().st_size / 1024**2:.1f} MB")


if __name__ == "__main__":
    main()
