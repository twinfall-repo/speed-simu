"""One frame of the scene, to set up the look before any movie:

    python movie/preview.py ORTHO.vtu RAILWAY.csv S_HEAD OUT.png

ORTHO.vtu is a draped orthophoto of dtm_voxelization (`orthophoto`, an rgb
per point), RAILWAY.csv its `railway` path (s x y z kind), both in the DTM's
frame, as the SPEED meshes. The train of train.py stands with its head at arc
length S_HEAD, and the camera looks at it from the lake side, from above.
Only the photo within WINDOW metres of the train is drawn.
"""

import sys

import numpy as np
import pyvista as pv

from train import build, place

WINDOW = 350.0  # m around the train's middle that the photo is cropped to
RAIL_LIFT = 0.3  # m the track ribbon is drawn over the path, against z-fighting


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 4:
        raise SystemExit(__doc__)
    ortho_path, railway_path, s_head, out = argv[0], argv[1], float(argv[2]), argv[3]

    track = np.loadtxt(railway_path)
    s, path, kind = track[:, 0], track[:, 1:4], track[:, 4].astype(int)
    print(f"railway {railway_path}: {s[-1]:.0f} m, head at s {s_head:.0f}", flush=True)
    cars, texture = build()
    train = place(cars, path, s, s_head)
    middle = np.array(train.center)
    print(f"  train middle at {middle.round(1)}, under a tunnel or gallery: "
          f"{kind[np.abs(s - s_head) < 60].max() > 0}", flush=True)

    ortho = pv.read(ortho_path)
    bounds = [middle[0] - WINDOW, middle[0] + WINDOW, middle[1] - WINDOW, middle[1] + WINDOW,
              -1e9, 1e9]
    ortho = ortho.clip_box(bounds, invert=False).extract_surface()
    print(f"  {ortho_path}: {ortho.n_points:,} points within {WINDOW:g} m", flush=True)

    plotter = pv.Plotter(off_screen=True, window_size=(1920, 1080))
    plotter.set_background("#cfd8e3")
    plotter.add_mesh(ortho, scalars="rgb", rgb=True, ambient=0.4, diffuse=0.7)
    open_track = path[kind < 2] + [0, 0, RAIL_LIFT]
    plotter.add_mesh(pv.PolyData(open_track), color="#3a3a3a", point_size=3,
                     render_points_as_spheres=True)
    plotter.add_mesh(train, texture=texture, ambient=0.35, diffuse=0.7)

    k = np.searchsorted(s, s_head)
    ahead = path[min(k + 5, len(s) - 1)] - path[max(k - 5, 0)]
    ahead /= np.linalg.norm(ahead)
    right = np.cross(ahead, [0, 0, 1])
    plotter.camera_position = [tuple(middle + 90 * ahead - 140 * right + [0, 0, 90]),
                               tuple(middle), (0, 0, 1)]
    plotter.screenshot(out)
    print(f"wrote {out}", flush=True)


if __name__ == "__main__":
    main()
