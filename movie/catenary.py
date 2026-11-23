"""The overhead line of the railway (3 kV DC on the Lecco-Tirano), low detail:

    python catenary.py RAILWAY_CSV      # catenary_preview.png, a stretch of it

A mast every SPAN m outside the tunnels (also in the avalanche galleries,
which the scene does not show), on the lake side, with a bracket out over
the track; the contact wire at CONTACT m over the rail and the messenger wire
over it, sagging between the masts. A likeness, not a
survey: the masts are not where the real ones are.

build() gives (masts, wires): the masts and brackets as tubes, the wires as
lines, to be drawn a pixel or two wide whatever the distance.
"""

import sys
from pathlib import Path

import numpy as np
import pyvista as pv

SPAN = 50.0  # m between masts
OFFSET = 3.0  # m from the track's axis to a mast, lake side
MAST = 7.6  # m, the mast's top over the rail
CONTACT, MESSENGER, SAG = 5.3, 6.7, 0.9  # m over the rail; the messenger's sag at mid-span


def build(track):
    """track: the rows of railway.csv, s x y z kind."""
    s, path, kind = track[:, 0], track[:, 1:4], track[:, 4].astype(int)
    ahead = np.gradient(path, axis=0)
    ahead[:, 2] = 0
    ahead /= np.linalg.norm(ahead, axis=1)[:, None]
    lake = -np.cross(ahead, [0, 0, 1])  # left of the run, as movie.py
    up = np.array([0.0, 0.0, 1.0])

    tubes = []
    stations = np.arange(SPAN / 2, s[-1], SPAN)
    k = np.searchsorted(s, stations).clip(0, len(s) - 1)
    k = k[kind[k] != 2]
    for i in k:
        foot = path[i] + OFFSET * lake[i]
        tubes.append(pv.Line(foot - 1.5 * up, foot + MAST * up).tube(radius=0.13, n_sides=8))
        for z in (MESSENGER + 0.2, CONTACT + 0.3):  # the bracket and the register arm
            tubes.append(pv.Line(foot + z * up, path[i] - 0.3 * lake[i] + z * up).tube(radius=0.05, n_sides=6))
    masts = tubes[0].append_polydata(*tubes[1:]) if tubes else pv.PolyData()

    phase = (s - SPAN / 2) / SPAN % 1  # 0 at a mast's station, 0.5 mid-span
    sag = SAG * 4 * phase * (1 - phase)
    lines = []
    for height in (np.full_like(s, CONTACT), MESSENGER - sag):
        wire = path + height[:, None] * up
        runs = np.split(np.arange(len(s)), np.flatnonzero(np.diff(kind == 2)) + 1)
        for run in runs:
            if kind[run[0]] != 2 and len(run) > 1:
                lines.append(pv.lines_from_points(wire[run]))
    wires = lines[0].append_polydata(*lines[1:])
    print(f"catenary: {len(k)} masts every {SPAN:g} m outside the tunnels, wires in "
          f"{len(lines) // 2} runs outside the tunnels, {s[-1]:.0f} m of railway", flush=True)
    return masts, wires


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        raise SystemExit(__doc__)
    track = np.loadtxt(argv[0])
    masts, wires = build(track)
    i = np.flatnonzero(track[:, 4] == 0)[len(track) // 4]  # somewhere on the open track
    at = track[i, 1:4]
    plotter = pv.Plotter(off_screen=True, window_size=(1600, 900))
    plotter.set_background("#d0d8e2")
    plotter.add_mesh(pv.lines_from_points(track[:, 1:4]), color="#2a2a2a", line_width=6)
    plotter.add_mesh(masts, color="#8a8f94")
    plotter.add_mesh(wires, color="#3a3a3a", line_width=2)
    plotter.camera_position = [tuple(at + [-60, -80, 25]), tuple(at + [0, 0, 4]), (0, 0, 1)]
    out = Path(__file__).with_name("catenary_preview.png")
    plotter.screenshot(out)
    print(f"wrote {out}", flush=True)


if __name__ == "__main__":
    main()
