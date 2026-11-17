"""The train of train.py running along the railway, as a time series for
ParaView:

    python movie/train_series.py RAILWAY.csv OUT_DIR

RAILWAY.csv is dtm_voxelization's `railway` path (s x y z kind, DTM frame).
The train enters at the path's first point and runs at SPEED until its tail
has left the last, one frame every DT seconds. OUT_DIR gets

  train_NNNN.vtu   the train at frame N, a few thousand cells
  train.pvd        the collection, with the time of each frame in seconds:
                   open it in ParaView and play
  train_texture.png  the livery, to apply as the texture (Properties >
                   Texture), the .vtu carry its coordinates

Each .vtu carries, besides the texture coordinates, a cell "rgb" sampled from
the texture at the cell's centre -- colour by it with Map Scalars off for a
quick look without the texture -- and a cell "kind", the railway's kind (0
open, 1 gallery, 2 tunnel) under the cell's car: threshold kind < 2 to hide
the cars in a tunnel.
"""

import sys
from pathlib import Path

import numpy as np
import pyvista as pv
from scipy.spatial import cKDTree

from train import CARS, END_CAR, GAP, MID_CAR, build, place

SPEED = 80 / 3.6  # m/s, the line's speed limit there (OSM maxspeed 80)
DT = 0.2  # s between frames


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2:
        raise SystemExit(__doc__)
    track = np.loadtxt(argv[0])
    out = Path(argv[1])
    out.mkdir(parents=True, exist_ok=True)
    s, path, kind = track[:, 0], track[:, 1:4], track[:, 4].astype(int)

    cars, texture = build()
    tree = cKDTree(path[:, :2])
    texture.to_image().save(out / "train_texture.png")
    pixels = np.asarray(texture.to_array())  # (h, w, 3), row 0 at v = 1
    h, w = pixels.shape[:2]
    length = 2 * END_CAR + (CARS - 2) * MID_CAR + (CARS - 1) * GAP
    heads = np.arange(0.0, s[-1] + length, SPEED * DT)
    print(f"railway {argv[0]}: {s[-1]:.0f} m; train {length:.1f} m at {SPEED * 3.6:.0f} km/h, "
          f"{len(heads)} frames every {DT:g} s, {len(heads) * DT:.1f} s in all", flush=True)

    entries = []
    for n, head in enumerate(heads):
        grid = place(cars, path, s, head).cast_to_unstructured_grid()
        # each cell's mean texture coordinates, from its points
        ends = grid.offset
        uv = np.add.reduceat(grid.point_data["uv"][grid.cell_connectivity], ends[:-1]) \
            / np.diff(ends)[:, None]
        col = np.clip((uv[:, 0] * (w - 1)).astype(int), 0, w - 1)
        row = np.clip(((1 - uv[:, 1]) * (h - 1)).astype(int), 0, h - 1)
        grid.cell_data["rgb"] = pixels[row, col, :3].astype(np.uint8)
        # the railway's kind under each cell: that of the nearest path point
        nearest = tree.query(np.asarray(grid.cell_centers().points)[:, :2])[1]
        grid.cell_data["kind"] = kind[nearest]
        name = f"train_{n:04d}.vtu"
        grid.save(out / name)
        entries.append(f'    <DataSet timestep="{n * DT:.3f}" file="{name}"/>')
        if n % 50 == 0 or n == len(heads) - 1:
            print(f"  frame {n}: head at s {head:.0f} m, t {n * DT:.1f} s, "
                  f"railway kinds under it: {sorted(set(kind[nearest].tolist()))}", flush=True)

    pvd = out / "train.pvd"
    pvd.write_text('<?xml version="1.0"?>\n<VTKFile type="Collection" version="0.1">\n'
                   "  <Collection>\n" + "\n".join(entries) + "\n  </Collection>\n</VTKFile>\n")
    print(f"wrote {pvd}: {len(entries)} frames in {out}", flush=True)


if __name__ == "__main__":
    main()
