"""The avalanche galleries, the tunnel portals and the rails of the railway, low detail:

    python galleries.py RAILWAY_CSV      # galleries_preview.png, the first gallery

Along the stretches of kind 1 (avalanche gallery) of railway.csv, a concrete
gallery: a wall on the mountain side, a roof slab over the track, and on
the lake side a pillar every PILLARS m, between which the train shows. Along
the stretches of kind 2 (tunnel), a solid arched tube that hides the train,
itself hidden where the mountain is over it; at every mouth of one, a
portal: an arched headwall, dark in its opening. A likeness, not a survey of the real structures.

rails() gives the two rails, GAUGE apart, their tops on the track's line
(where train.py sets the wheels), outside the tunnels.

build() gives (concrete, openings, tunnels): the galleries and portals, the
dark openings of the portals, and the tunnels' tubes, for movie.py to drape
in the orthophoto where the DTM leaves them out in the open.
"""

import sys
from pathlib import Path

import numpy as np
import pyvista as pv

MOUNTAIN, LAKE = 3.2, 3.4  # m from the track's axis to the wall's face and to the pillars' inner face
CLEAR, SLAB = 7.6, 1.0  # m, the clear height over the rail, the roof's thickness
PILLARS, PILLAR = 8.0, (1.0, 0.8)  # m between pillars; a pillar's size along and across the track
WALL = 0.8  # m, the mountain wall's thickness
ARCH = 3.6, 4.6  # m, a portal opening's half width and the height its arch springs from
RING = 2.0  # m, the headwall round the opening
LINING = 0.8  # m, the tunnel's lining round the opening
GAUGE, RAIL = 1.435, (0.07, 0.15)  # m, standard gauge; a rail's head width and height


def frames(path):
    """ahead and lake (left of the run, as movie.py) unit vectors along the path."""
    ahead = np.gradient(path, axis=0)
    ahead[:, 2] = 0
    ahead /= np.linalg.norm(ahead, axis=1)[:, None]
    return ahead, -np.cross(ahead, [0, 0, 1])


def extrude(section, points, lake):
    """The closed polygon section (a across, lake positive; b up) swept along
    points, with its ends capped."""
    n, m = len(points), len(section)
    up = np.array([0.0, 0.0, 1.0])
    ring = points[:, None] + section[None, :, :1] * lake[:, None] + section[None, :, 1:] * up
    i, j = np.meshgrid(np.arange(n - 1), np.arange(m), indexing="ij")
    k, k1 = (i * m + j).ravel(), (i * m + (j + 1) % m).ravel()
    faces = [np.column_stack([np.full(k.size, 4), k, k + m, k1 + m, k1]).ravel()]
    for end in (0, n - 1):
        faces.append(np.concatenate([[m], end * m + np.arange(m)]))
    return pv.PolyData(ring.reshape(-1, 3), np.concatenate(faces)).triangulate()


def box(center, ahead, lake, size):
    """A box of size (along, across, up) centred at center, aligned to the track."""
    cube = pv.Cube(x_length=size[0], y_length=size[1], z_length=size[2])
    p = cube.points
    cube.points = center + p[:, :1] * ahead + p[:, 1:2] * lake + p[:, 2:] * [0, 0, 1]
    return cube


def arch(n=24):
    """The opening of a portal, (a, b), from the bottom of one side round to the other."""
    w, spring = ARCH
    t = np.linspace(np.pi, 0, n)
    return np.vstack([[[-w, 0]], np.column_stack([w * np.cos(t), spring + w * np.sin(t)]), [[w, 0]]])


def portal(point, ahead, lake, outward):
    """A headwall facing outward (+1 along ahead, or -1) round a dark opening."""
    up = np.array([0.0, 0.0, 1.0])
    inner = arch()
    w, spring = ARCH
    outer = inner * [(w + RING) / w, (spring + w + RING) / (spring + w)]
    to3 = lambda ab, back: point + ab[:, :1] * lake + ab[:, 1:] * up - back * outward * ahead
    m = len(inner)
    k = np.arange(m - 1)
    wall = pv.PolyData(np.vstack([to3(inner, 0), to3(outer, 0)]),
                       np.column_stack([np.full(m - 1, 4), k, k + 1, m + k + 1, m + k]).ravel())
    dark = pv.PolyData(to3(inner, -0.05), np.concatenate([[m], np.arange(m)])).triangulate()  # on the tube's end
    return wall, dark


def rails(track):
    """track: the rows of railway.csv, s x y z kind."""
    s, path, kind = track[:, 0], track[:, 1:4], track[:, 4].astype(int)
    _, lake = frames(path)
    w, h = RAIL
    parts = []
    for run in np.split(np.arange(len(s)), np.flatnonzero(np.diff(kind == 2)) + 1):
        if kind[run[0]] == 2 or len(run) < 2:
            continue
        for side in (-1, 1):
            a = side * (GAUGE + w) / 2  # the gauge is between the heads' inner faces
            section = np.array([[a - w / 2, -h], [a + w / 2, -h], [a + w / 2, 0], [a - w / 2, 0]])
            parts.append(extrude(section, path[run], lake[run]))
    print(f"rails: {len(parts) // 2} runs outside the tunnels, gauge {GAUGE} m", flush=True)
    return parts[0].append_polydata(*parts[1:])


def build(track):
    """track: the rows of railway.csv, s x y z kind."""
    s, path, kind = track[:, 0], track[:, 1:4], track[:, 4].astype(int)
    ahead, lake = frames(path)
    runs = np.split(np.arange(len(s)), np.flatnonzero(np.diff(kind)) + 1)
    section = np.array([[-MOUNTAIN - WALL, -0.5], [-MOUNTAIN, -0.5], [-MOUNTAIN, CLEAR],
                        [LAKE + PILLAR[1] + 0.3, CLEAR], [LAKE + PILLAR[1] + 0.3, CLEAR + SLAB],
                        [-MOUNTAIN - WALL, CLEAR + SLAB]])
    concrete, openings, tunnels = [], [], []
    for run in runs:
        if kind[run[0]] == 1 and len(run) > 1:
            concrete.append(extrude(section, path[run], lake[run]))
            for st in np.arange(s[run[0]] + PILLAR[0] / 2, s[run[-1]], PILLARS):
                i = np.searchsorted(s, st)
                h = CLEAR + 0.5
                concrete.append(box(path[i] + (LAKE + PILLAR[1] / 2) * lake[i] + (h / 2 - 0.5) * np.array([0, 0, 1]),
                                    ahead[i], lake[i], (PILLAR[0], PILLAR[1], h)))
            print(f"gallery from s {s[run[0]]:.0f} to {s[run[-1]]:.0f} m", flush=True)
        if kind[run[0]] == 2:
            # the tunnel, a solid tube the length of it with the train inside, hidden where the mountain is over it
            w, spring = ARCH
            tube = arch() * [(w + LINING) / w, (spring + w + LINING) / (spring + w)]
            tube[[0, -1], 1] = -0.5
            tunnels.append(extrude(tube, path[run], lake[run]))
            print(f"tunnel from s {s[run[0]]:.0f} to {s[run[-1]]:.0f} m", flush=True)
            for i, outward, other in ((run[0], -1, run[0] - 1), (run[-1], 1, run[-1] + 1)):
                if 0 <= other < len(s):  # a mouth inside the domain
                    wall, dark = portal(path[i], ahead[i], lake[i], outward)
                    concrete.append(wall)
                    openings.append(dark)
                    print(f"tunnel portal at s {s[i]:.0f} m, "
                          f"{'gallery' if kind[other] == 1 else 'open track'} outside", flush=True)
    join = lambda parts: parts[0].append_polydata(*parts[1:])
    return join(concrete), join(openings), join(tunnels)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        raise SystemExit(__doc__)
    track = np.loadtxt(argv[0])
    concrete, openings, tunnels = build(track)
    at = track[np.searchsorted(track[:, 0], 90.0), 1:4]  # the first gallery, out of its tunnel
    ahead, lake = (v[np.searchsorted(track[:, 0], 90.0)] for v in frames(track[:, 1:4]))
    plotter = pv.Plotter(off_screen=True, window_size=(1600, 900))
    plotter.set_background("#d0d8e2")
    plotter.add_mesh(pv.lines_from_points(track[:, 1:4]), color="#2a2a2a", line_width=6)
    plotter.add_mesh(concrete, color="#b8b4aa")
    plotter.add_mesh(openings, color="#151515")
    plotter.add_mesh(tunnels, color="#7d8a6a")
    plotter.camera_position = [tuple(at + 30 * ahead + 35 * lake + [0, 0, 12]),
                               tuple(at + 10 * ahead + [0, 0, 3]), (0, 0, 1)]
    out = Path(__file__).with_name("galleries_preview.png")
    plotter.screenshot(out)
    print(f"wrote {out}", flush=True)


if __name__ == "__main__":
    main()
