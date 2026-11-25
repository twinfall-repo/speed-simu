"""The fields of a run on its free surface: the displacement, and the
velocity in the frame of the railway and, on the towers, along the normal to
their fractures:

    python surface.py RUN_DIR

Reads RUN_DIR/VTKOUT, written by SPEED with VTKWRITE ... XDMF: the mesh
(mesh_points.bin, mesh_cells.bin, mesh_elements.bin), and for each snapshot
whichever of these it has: Disp_<step>.bin, the displacement; with VELOCITY,
Vel_<step>.bin, the velocity at that step; with VELVV, VelVV_<step>.bin,
the mean of v v^T over the steps since the previous snapshot (xx xy xz yy yz zz,
an XDMF Tensor6).

The free surface is made of the faces of the spectral elements that no other
element shares (the copies of a node on partition borders and on the two
sides of a crack count as one node) and that are not on the sides or the
bottom of the domain, the absorbing boundaries.

At every point of it, from the nearest point of the railway (post/railway.csv):
  r  radial, horizontal, from the track to the point
  t  along the track, as s grows
  z  vertical
and, within FRACTURE_RANGE m of a fracture of the towers (post/fractures/*.stl),
n, the normal to the nearest fracture, towards the railway (the valley).
A component of the velocity is v.e; the RMS velocity along e over a snapshot's
interval is sqrt(e^T VelVV e), its magnitude sqrt(tr VelVV).

Writes RUN_DIR/surface/:
  surface.xmf    for ParaView, one grid per snapshot:
                 Disp (3, x y z); Vel_rtz (3), Vel_n; RMS_rtz (3), RMS, RMS_n
                 (n: NaN away from the fractures)
  maps.xmf       one grid: the frame (e_r, e_t, n, d_track, d_fracture) and over
                 the whole run RMS_run_rtz (3), RMS_run, RMS_run_n, the RMS of
                 all the steps, and RMS_max, RMS_n_max, the largest RMS of a snapshot
  *.bin          their raw data, float32 (float64 points, int32 quadrilaterals)
"""

import re
import sys
import time
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

HERE = Path(__file__).resolve().parent
RAILWAY = HERE / "post" / "railway.csv"
FRACTURES = sorted((HERE / "post" / "fractures").glob("*.stl"))
FRACTURE_RANGE = 30.0  # m: farther from every fracture, no n
# the hexahedron's faces in VTK order, as SPEED's XDMF writes both the
# spectral elements and their linear sub-cells; with the sub-cell's (a, b, c)
# index on that side
FACES = (((0, 3, 7, 4), 0, 0), ((1, 2, 6, 5), 0, -1), ((0, 1, 5, 4), 1, 0),
         ((3, 2, 6, 7), 1, -1), ((0, 1, 2, 3), 2, 0), ((4, 5, 6, 7), 2, -1))
T0 = time.perf_counter()


def log(message):
    print(f"[{time.perf_counter() - T0:7.1f}s] {message}", flush=True)


def stl(path):
    """Triangles (n, 3, 3) of a binary STL."""
    raw = path.read_bytes()
    n = int(np.frombuffer(raw, "<u4", 1, 80)[0])
    if len(raw) != 84 + 50 * n:
        raise SystemExit(f"{path}: {len(raw)} bytes, not a binary STL of {n} triangles")
    rec = np.frombuffer(raw, np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]), n, 84)
    return rec["v"].astype(float)


def nearest(points, targets):
    """Index of the nearest target of each point, and the distance."""
    dist, index = cKDTree(targets).query(points)
    return index, dist


def surface(vtk):
    """The free surface: quadrilaterals of sub-cell faces, as point ids of mesh_points.bin."""
    points = np.memmap(vtk / "mesh_points.bin", "<f8", "r").reshape(-1, 3)
    elements = np.fromfile(vtk / "mesh_elements.bin", "<i4").reshape(-1, 8)
    cells = np.memmap(vtk / "mesh_cells.bin", "<i4", "r").reshape(-1, 8)
    nsub = len(cells) // len(elements)
    m = round(nsub ** (1 / 3))
    if m ** 3 * len(elements) != len(cells):
        raise SystemExit(f"{len(cells)} sub-cells for {len(elements)} elements: not (nn-1)^3 each, "
                         "mixed degrees are not handled")
    log(f"mesh: {len(points):,} points, {len(elements):,} spectral elements of degree {m}, "
        f"{len(cells):,} sub-cells")
    # one id per position for the corners: partition borders and crack sides merged
    corner_ids, inverse = np.unique(elements, return_inverse=True)
    xyz = np.asarray(points[corner_ids])
    positions, merged = np.unique(xyz, axis=0, return_inverse=True)
    corners = merged.ravel()[inverse.ravel()].reshape(elements.shape)
    lo, hi = np.asarray(points).min(0), np.asarray(points).max(0)
    log(f"domain x [{lo[0]:.1f}, {hi[0]:.1f}] y [{lo[1]:.1f}, {hi[1]:.1f}] z from {lo[2]:.1f}; "
        f"{len(corner_ids):,} corner points, {len(positions):,} positions")
    faces = np.concatenate([corners[:, f] for f, _, _ in FACES])          # (6 ne, 4)
    key = np.sort(faces, axis=1)
    _, first, count = np.unique(key, axis=0, return_index=True, return_counts=True)
    once = np.zeros(len(faces), bool)
    once[first[count == 1]] = True
    fx = positions[faces]                                                  # (6 ne, 4, 3)
    tol = 1e-6 * (hi - lo).max()
    on_box = (np.all(np.abs(fx[..., 0] - lo[0]) < tol, 1) | np.all(np.abs(fx[..., 0] - hi[0]) < tol, 1)
              | np.all(np.abs(fx[..., 1] - lo[1]) < tol, 1) | np.all(np.abs(fx[..., 1] - hi[1]) < tol, 1)
              | np.all(np.abs(fx[..., 2] - lo[2]) < tol, 1))
    free = once & ~on_box
    log(f"element faces: {len(faces):,}, on the boundary {once.sum():,}, of which absorbing "
        f"{(once & on_box).sum():,} and free {free.sum():,}")
    # the sub-cells' faces on each free element face
    a, b, c = np.unravel_index(np.arange(nsub), (m, m, m), order="F")   # a fastest, as SPEED writes
    abc = np.stack([a, b, c], 1)
    quads = []
    ne = len(elements)
    for k, (local, axis, side) in enumerate(FACES):
        hit = np.flatnonzero(free[k * ne:(k + 1) * ne])
        subs = np.flatnonzero(abc[:, axis] == (side % m))
        rows = (hit[:, None] * nsub + subs[None, :]).ravel()
        quads.append(np.asarray(cells[np.sort(rows)])[:, list(local)])
    quads = np.concatenate(quads)
    ids, quads = np.unique(quads, return_inverse=True)
    quads = quads.reshape(-1, 4).astype("<i4")
    log(f"free surface: {len(quads):,} quadrilaterals, {len(ids):,} points")
    return ids, np.asarray(points[ids]), quads


def frame(xyz):
    """e_r, e_t from the railway; n from the fractures (NaN out of range); the distances."""
    track = np.loadtxt(RAILWAY)
    s, path = track[:, 0], track[:, 1:4]
    tangent = np.gradient(path, s, axis=0)
    tangent[:, 2] = 0
    tangent /= np.linalg.norm(tangent, axis=1)[:, None]
    k, d_track = nearest(xyz, path)
    e_t = tangent[k]
    e_r = xyz - path[k]
    e_r[:, 2] = 0
    e_r -= (e_r * e_t).sum(1)[:, None] * e_t
    norm = np.linalg.norm(e_r, axis=1)
    on_track = norm < 1e-3
    e_r[on_track] = np.cross([0.0, 0.0, 1.0], e_t[on_track])            # on the track: to the left
    e_r /= np.linalg.norm(e_r, axis=1)[:, None]
    log(f"railway {RAILWAY.name}: {len(path)} points over {s[-1]:.0f} m; distance of the surface "
        f"from it {d_track.min():.1f} to {d_track.max():.1f} m, {on_track.sum()} points on it")
    tris = np.concatenate([stl(f) for f in FRACTURES])
    centres = tris.mean(1)
    normals = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    normals /= np.linalg.norm(normals, axis=1)[:, None]
    # only the points in the fractures' box, grown by FRACTURE_RANGE, can be in range
    near = np.all((xyz > centres.min(0) - FRACTURE_RANGE) & (xyz < centres.max(0) + FRACTURE_RANGE), 1)
    j, d = nearest(xyz[near], centres)
    d_frac = np.full(len(xyz), np.inf)
    d_frac[near] = d
    n = np.full((len(xyz), 3), np.nan)
    n[near] = normals[j]
    valley = path[k] - xyz                                                # towards the railway
    n *= np.where((n * valley).sum(1) < 0, -1.0, 1.0)[:, None]
    n[d_frac > FRACTURE_RANGE] = np.nan
    log(f"fractures {[f.stem for f in FRACTURES]}: {len(tris):,} triangles; {np.isfinite(n[:, 0]).sum():,} "
        f"surface points within {FRACTURE_RANGE:g} m of one")
    return e_r, e_t, n, d_track, d_frac


def snapshots(vtk):
    """(step, time) of the snapshots, from the grids of SPEED.xmf. A run killed
    while writing (the walltime) leaves its last snapshots short or missing:
    those, from the first whose files are not the size of the first
    snapshot's, are dropped."""
    snaps, files = [], []
    for grid in (vtk / "SPEED.xmf").read_text().split("<Grid Name=\"mesh\"")[1:]:
        t = re.search(r'<Time Value="([^"]+)"', grid)
        names = re.findall(r"((?:Disp|Vel|VelVV)_(\d+)\.bin)", grid)
        if not (t and names):
            raise SystemExit(f"{vtk / 'SPEED.xmf'}: a snapshot without a time or a Disp, Vel, VelVV file")
        snaps.append((int(names[0][1]), float(t.group(1))))
        files.append([name for name, _ in names])
    if not snaps:
        raise SystemExit(f"{vtk / 'SPEED.xmf'}: no snapshot")
    size = lambda name: (vtk / name).stat().st_size if (vtk / name).exists() else -1
    whole = [size(name) for name in files[0]]
    for k, names in enumerate(files):
        sizes = [size(name) for name in names]
        if sizes != whole:
            log(f"{vtk / 'SPEED.xmf'}: snapshot {k + 1}/{len(snaps)} (step {snaps[k][0]}, t {snaps[k][1]:g} s) "
                f"has {dict(zip(names, sizes))} bytes, not {whole} (-1: missing): the run was cut short, "
                f"keeping the {k} snapshots before it, to t {snaps[k - 1][1] if k else 0:g} s")
            if k == 0:
                raise SystemExit(f"{vtk / 'SPEED.xmf'}: no whole snapshot")
            return snaps[:k]
    return snaps


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        raise SystemExit(__doc__)
    run = Path(argv[0])
    vtk, out = run / "VTKOUT", run / "surface"
    out.mkdir(exist_ok=True)
    snaps = snapshots(vtk)
    has_d = (vtk / f"Disp_{snaps[-1][0]:08d}.bin").exists()
    has_v = (vtk / f"Vel_{snaps[-1][0]:08d}.bin").exists()
    has_vv = (vtk / f"VelVV_{snaps[-1][0]:08d}.bin").exists()
    log(f"{run}: {len(snaps)} snapshots, t {snaps[0][1]:g} to {snaps[-1][1]:g} s; "
        f"Disp {'yes' if has_d else 'no'}, Vel {'yes' if has_v else 'no'}, VelVV {'yes' if has_vv else 'no'}")
    ids, xyz, quads = surface(vtk)
    e_r, e_t, n, d_track, d_frac = frame(xyz)
    axes = np.stack([e_r, e_t, np.tile([0.0, 0.0, 1.0], (len(xyz), 1))], 1)  # (np, 3 axes, 3)
    xyz.astype("<f8").tofile(out / "points.bin")
    quads.tofile(out / "quads.bin")

    def write(name, values):
        np.asarray(values, "<f4").tofile(out / name)
        return name

    def tensor(vv):
        """(np, 3, 3) from xx xy xz yy yz zz."""
        i, j = np.triu_indices(3)
        c = np.empty((len(vv), 3, 3))
        c[:, i, j] = vv
        c[:, j, i] = vv
        return c

    along = lambda c, e: np.sqrt(np.maximum(np.einsum("pi,pij,pj->p", e, c, e), 0))
    grids, c_run, rms_max, rms_n_max = [], np.zeros((len(xyz), 3, 3)), np.zeros(len(xyz)), np.zeros(len(xyz))
    for k, (step, t) in enumerate(snaps):
        attrs = []
        if has_d:
            d = np.memmap(vtk / f"Disp_{step:08d}.bin", "<f4", "r").reshape(-1, 3)[ids]
            attrs.append(("Disp", 3, write(f"Disp_{step:08d}.bin", d)))
        if has_v:
            v = np.asarray(np.memmap(vtk / f"Vel_{step:08d}.bin", "<f4", "r").reshape(-1, 3)[ids], float)
            attrs.append(("Vel_rtz", 3, write(f"Vel_rtz_{step:08d}.bin", np.einsum("pij,pj->pi", axes, v))))
            attrs.append(("Vel_n", 1, write(f"Vel_n_{step:08d}.bin", (n * v).sum(1))))
        if has_vv:
            vv = np.asarray(np.memmap(vtk / f"VelVV_{step:08d}.bin", "<f4", "r").reshape(-1, 6)[ids], float)
            c = tensor(vv)
            rms = np.sqrt(np.maximum(np.trace(c, axis1=1, axis2=2), 0))
            rms_n = along(c, np.nan_to_num(n))
            rms_n[np.isnan(n[:, 0])] = np.nan
            attrs.append(("RMS_rtz", 3, write(f"RMS_rtz_{step:08d}.bin",
                                               np.stack([along(c, axes[:, i]) for i in range(3)], 1))))
            attrs.append(("RMS", 1, write(f"RMS_{step:08d}.bin", rms)))
            attrs.append(("RMS_n", 1, write(f"RMS_n_{step:08d}.bin", rms_n)))
            if step > 0:                                   # snapshot 0 holds no interval
                c_run += c * (step - snaps[k - 1][0])
                rms_max = np.maximum(rms_max, rms)
                rms_n_max = np.fmax(rms_n_max, rms_n)
        grids.append((t, attrs))
        if k % 50 == 0 or k == len(snaps) - 1:
            log(f"  snapshot {k + 1}/{len(snaps)}: step {step}, t {t:g} s"
                + (f", |Disp| on the surface up to {np.linalg.norm(d, axis=1).max():.3e} m" if has_d else "")
                + (f", RMS on the surface up to {rms.max():.3e} m/s" if has_vv else ""))
    xdmf(out / "surface.xmf", len(xyz), len(quads), grids)

    maps = [("e_r", 3, write("e_r.bin", e_r)), ("e_t", 3, write("e_t.bin", e_t)), ("n", 3, write("n.bin", n)),
            ("d_track", 1, write("d_track.bin", d_track)), ("d_fracture", 1, write("d_fracture.bin", d_frac))]
    if has_vv:
        c_run /= max(snaps[-1][0], 1)
        rms_run_n = along(c_run, np.nan_to_num(n))
        rms_run_n[np.isnan(n[:, 0])] = np.nan
        rms_n_max[np.isnan(n[:, 0])] = np.nan
        maps += [("RMS_run_rtz", 3, write("RMS_run_rtz.bin", np.stack([along(c_run, axes[:, i]) for i in range(3)], 1))),
                 ("RMS_run", 1, write("RMS_run.bin", np.sqrt(np.trace(c_run, axis1=1, axis2=2)))),
                 ("RMS_run_n", 1, write("RMS_run_n.bin", rms_run_n)),
                 ("RMS_max", 1, write("RMS_max.bin", rms_max)),
                 ("RMS_n_max", 1, write("RMS_n_max.bin", rms_n_max))]
        log(f"over the run: RMS up to {np.sqrt(np.trace(c_run, axis1=1, axis2=2)).max():.3e} m/s, "
            f"largest RMS of a snapshot {rms_max.max():.3e} m/s, "
            f"on the towers along n up to {np.nanmax(rms_n_max) if np.isfinite(rms_n_max).any() else float('nan'):.3e} m/s")
    xdmf(out / "maps.xmf", len(xyz), len(quads), [(None, maps)])
    log(f"wrote {out}/surface.xmf ({len(grids)} snapshots) and maps.xmf")


def xdmf(path, npoints, nquads, grids):
    """An XDMF file over points.bin and quads.bin: a temporal collection, or one grid if its time is None."""
    def grid(t, attrs):
        s = ' <Grid Name="surface" GridType="Uniform">\n'
        if t is not None:
            s += f'  <Time Value="{t:.8e}"/>\n'
        s += (f'  <Topology TopologyType="Quadrilateral" NumberOfElements="{nquads}">\n'
              f'   <DataItem Dimensions="{nquads} 4" NumberType="Int" Precision="4" Format="Binary" '
              f'Endian="Little">quads.bin</DataItem>\n  </Topology>\n'
              f'  <Geometry GeometryType="XYZ">\n'
              f'   <DataItem Dimensions="{npoints} 3" NumberType="Float" Precision="8" Format="Binary" '
              f'Endian="Little">points.bin</DataItem>\n  </Geometry>\n')
        for name, ncomp, fname in attrs:
            kind = "Vector" if ncomp == 3 else "Scalar"
            s += (f'  <Attribute Name="{name}" AttributeType="{kind}" Center="Node">\n'
                  f'   <DataItem Dimensions="{npoints} {ncomp}" NumberType="Float" Precision="4" '
                  f'Format="Binary" Endian="Little">{fname}</DataItem>\n  </Attribute>\n')
        return s + " </Grid>\n"
    body = "".join(grid(t, a) for t, a in grids)
    if grids[0][0] is not None:
        body = f' <Grid Name="velocity" GridType="Collection" CollectionType="Temporal">\n{body} </Grid>\n'
    path.write_text(f'<?xml version="1.0" ?>\n<Xdmf Version="3.0">\n<Domain>\n{body}</Domain>\n</Xdmf>\n')


if __name__ == "__main__":
    main()
