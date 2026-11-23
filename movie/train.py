"""A low-detail textured train that runs along a path, for the movies:

    python movie/train.py [SIDE.png]        # writes movie/train_preview.png

Two coupled units of five cars, the double trainset of the TTB-2D train loads
(cases/rialba_ttb), after the Trenord "Donizetti" (Alstom Coradia Stream) that
serve the Lecco-Tirano line: each unit about 112 m with a cab at either end,
the pair about 225 m, 2.9 m wide, 4 m over the rail. The
dimensions are a likeness, not a drawing, and so is the livery, painted here
in a texture after the Trenord livery of photos of the train on Wikimedia
Commons: lime green body between a blue skirt and a light blue band under
the roof, yellow-green doors, a white cab with a green nose round a wide dark
windscreen. Any side view of a car can
replace the painted side, given as SIDE.png and stretched over both sides of
every car (its left edge goes to the car's front); the cabs keep their
painted face.

Each car is a cross-section swept along the car, with the texture's u along
the car and its v around the section, bottom of one side to the bottom of the
other over the roof. The two end cars of each unit taper into a nose over NOSE
metres and end in a cap carrying the cab's face, so the two units meet nose to
nose; between the other cars the caps are dark, as a gangway.

`build(side)` gives the cars in their own frame (x along the car from its
centre, z up from the rail) and the texture; `place(cars, path, s_head)`
puts them on a path -- (n, 3) points with their arc length -- with the head
of the train at s_head, each car resting on its two bogies, so a car spans a
curve as a chord and follows the grade.
"""

import sys
from pathlib import Path

import numpy as np
import pyvista as pv
from PIL import Image, ImageDraw

END_CAR, MID_CAR, GAP = 23.0, 21.0, 0.8  # m, car lengths and the gap between cars
CARS = 5  # cars in a unit, a cab at each end
UNITS = 2  # units coupled into the train
LENGTH = UNITS * (2 * END_CAR + (CARS - 2) * MID_CAR + (CARS - 1) * GAP) + (UNITS - 1) * GAP  # m
WIDTH, HEIGHT, FLOOR = 2.90, 4.00, 0.45  # m, body width, roof over the rail, body bottom
NOSE = 3.5  # m over which an end car narrows into its nose
BOGIE = 0.35  # bogie centres at this fraction of the car length from its centre
# the Trenord livery of the ETR 204 "Donizetti", after photos on Wikimedia Commons
WHITE, LIME, LIGHT_BLUE, BLUE, DOOR, GLASS, FRAME, DARK, ROOF, RED = (
    (238, 240, 240), (122, 201, 67), (86, 156, 222), (30, 92, 176), (206, 222, 78),
    (34, 38, 44), (150, 156, 160), (36, 38, 42), (178, 182, 186), (210, 40, 40))
SIDE_U, FACE_U = 0.88, 0.90  # the texture's sides end at SIDE_U, a cab's face starts at FACE_U


def livery(side=None, width=2048, height=512):
    """The texture: the side of a car, front to the left, over u 0..SIDE_U
    (painted, or SIDE stretched there), and the face of a cab past FACE_U.
    Up the side: dark underframe, blue skirt, a thin white line, the lime
    green body with its windows and yellow-green doors, a white line, a
    light blue band under the roof, the grey roof. The cab: white, its upper
    nose lime green round a wide black windscreen, blue at the bottom, the
    headlights and the red coupler."""
    image = Image.new("RGB", (width, height), WHITE)
    draw = ImageDraw.Draw(image)
    y = lambda frac: int(height * (1 - frac))  # frac of the height, from the bottom
    x = lambda frac: int(width * frac)  # frac of the width, from the left
    end = x(SIDE_U)
    bands = ((0.00, 0.07, DARK), (0.07, 0.28, BLUE), (0.28, 0.32, WHITE), (0.32, 0.84, LIME),
             (0.84, 0.87, WHITE), (0.87, 0.95, LIGHT_BLUE), (0.95, 1.00, ROOF))
    for lo, hi, colour in bands:
        draw.rectangle([0, y(hi), end, y(lo)], fill=colour)
    windows = np.linspace(0.06, 0.94, 9)
    for w in windows:  # windows, a grey frame round dark glass, not over the doors
        if min(abs(w - 0.22), abs(w - 0.78)) < 0.07:
            continue
        x0, x1 = x(SIDE_U * (w - 0.035)), x(SIDE_U * (w + 0.035))
        draw.rounded_rectangle([x0, y(0.79), x1, y(0.47)], radius=8, fill=GLASS, outline=FRAME, width=5)
    for door in (0.22, 0.78):  # two doors per car, glazed in their upper half
        x0, x1 = x(SIDE_U * (door - 0.04)), x(SIDE_U * (door + 0.04))
        draw.rectangle([x0, y(0.82), x1, y(0.09)], fill=DOOR, outline=DARK, width=4)
        mid = (x0 + x1) // 2
        draw.line([mid, y(0.82), mid, y(0.09)], fill=DARK, width=3)
        for gx0, gx1 in ((x0 + 10, mid - 8), (mid + 8, x1 - 10)):
            draw.rounded_rectangle([gx0, y(0.76), gx1, y(0.45)], radius=6, fill=GLASS)
    if side:
        image.paste(Image.open(side).convert("RGB").resize((end, height)), (0, 0))
    face = x(FACE_U)
    draw.rectangle([face, 0, width, height], fill=WHITE)
    draw.rectangle([face, y(0.97), width, y(0.60)], fill=LIME)  # the upper nose
    draw.rounded_rectangle([face + 14, y(0.90), width - 14, y(0.56)], radius=18, fill=GLASS)  # windscreen
    draw.rectangle([face, y(0.24), width, y(0.0)], fill=BLUE)  # the lower front
    for lamp in (0.18, 0.82):  # headlights, in dark surrounds
        cx = face + (width - face) * lamp
        draw.ellipse([cx - 16, y(0.42) - 11, cx + 16, y(0.42) + 11], fill=DARK)
        draw.ellipse([cx - 8, y(0.42) - 6, cx + 8, y(0.42) + 6], fill=(255, 250, 220))
    cx = face + (width - face) / 2
    draw.rectangle([cx - 14, y(0.16), cx + 14, y(0.06)], fill=RED)  # the coupler
    return image


def section(n=40):
    """(y, z) around the car from the bottom of its left side to the bottom of
    its right one, and the v of each point (its arc-length fraction)."""
    half, shoulder = WIDTH / 2, HEIGHT - 0.6
    t = np.linspace(0, np.pi, n // 2)
    roof = np.column_stack([-half * np.cos(t), shoulder + 0.6 * np.sin(t)])
    left = np.column_stack([np.full(4, -half), np.linspace(FLOOR, shoulder, 4)])
    right = left[::-1] * [-1, 1]
    yz = np.vstack([left[:-1], roof, right[1:]])
    arc = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(yz, axis=0), axis=1))])
    # v climbs one side (0 to 1 at the shoulder), the roof stays near 1, and
    # comes down the other side: the side image is then right side up on both
    v = np.minimum(arc, arc[-1] - arc) / (shoulder - FLOOR + 0.3)
    return yz, np.clip(v, 0, 0.97)  # v = 1 would wrap onto the bottom row


def textured(mesh):
    """The "uv" point array made the texture coordinates: they are carried
    through appends as a plain array, not as the active ones."""
    mesh.active_texture_coordinates = mesh.point_data["uv"]
    return mesh


def car(length, nose_front, nose_back, nx=48):
    """One car as a textured surface, x from -length/2 (back) to length/2."""
    yz, v = section()
    x = np.linspace(-length / 2, length / 2, nx)
    scale = np.ones(nx)
    for end, has in ((length / 2, nose_front), (-length / 2, nose_back)):
        if has:
            d = np.clip(1 - np.abs(end - x) / NOSE, 0, 1)  # 1 at the tip, 0 NOSE m in
            scale = np.minimum(scale, np.sqrt(1 - 0.75 * d ** 2))
    points = np.empty((nx, len(yz), 3))
    points[..., 0] = x[:, None]
    points[..., 1] = yz[None, :, 0] * scale[:, None]
    points[..., 2] = FLOOR + (yz[None, :, 1] - FLOOR) * scale[:, None]
    u = SIDE_U * (1 - (x + length / 2) / length)  # u = 0 at the front, as the image
    tcoords = np.stack(np.broadcast_arrays(u[:, None], v[None, :]), axis=-1)
    i, j = np.meshgrid(np.arange(nx - 1), np.arange(len(yz) - 1), indexing="ij")
    k = (i * len(yz) + j).ravel()
    quads = np.column_stack([np.full(k.size, 4), k, k + len(yz), k + len(yz) + 1, k + 1])
    body = pv.PolyData(points.reshape(-1, 3), quads.ravel())
    body.point_data["uv"] = tcoords.reshape(-1, 2)
    caps = []
    for end, cab in ((0, nose_back), (nx - 1, nose_front)):  # a flat cap at each end
        ring = np.vstack([points[end], points[end].mean(axis=0)])
        n = len(ring) - 1  # the section is open at the floor: the fan wraps round to close it
        cap = pv.PolyData(ring, np.column_stack([
            np.full(n, 3), np.arange(n), (np.arange(n) + 1) % n, np.full(n, n)]).ravel())
        if cab:  # the cab's face, spread over the end as seen from ahead
            span = np.ptp(ring[:, 1]) or 1
            cap.point_data["uv"] = np.column_stack([
                FACE_U + (1 - FACE_U) * (ring[:, 1] - ring[:, 1].min()) / span,
                0.97 * (ring[:, 2] - FLOOR) / (ring[:, 2].max() - FLOOR)])
        else:  # a gangway: the dark of the window band
            cap.point_data["uv"] = np.tile([SIDE_U / 2, 0.52], (len(ring), 1))
        caps.append(cap)
    return textured(body.append_polydata(*caps))


def build(side=None):
    """([(car mesh, length, offset of its centre behind the head)], texture)."""
    image = livery(side)
    print(f"train: {UNITS} units of {CARS} cars, texture {'from ' + str(side) if side else 'painted'} "
          f"{image.size[0]} x {image.size[1]}", flush=True)
    cars, behind = [], 0.0
    for _ in range(UNITS):
        for c in range(CARS):
            length = END_CAR if c in (0, CARS - 1) else MID_CAR
            mesh = car(length, nose_front=c == 0, nose_back=c == CARS - 1)
            cars.append((mesh, length, behind + length / 2))
            behind += length + GAP
    print(f"  {behind - GAP:.1f} m long, {sum(m.n_cells for m, _, _ in cars):,} cells", flush=True)
    return cars, pv.Texture(np.asarray(image))  # pv.Texture puts the image's top at v = 1


def place(cars, path, s, s_head):
    """The cars on the path, head at arc length s_head, each one a chord
    between its two bogies. Past either end of the path the cars run on along
    its end's direction, so a train can come in from beyond it."""
    placed = []
    first = (path[1] - path[0]) / (s[1] - s[0])
    last = (path[-1] - path[-2]) / (s[-1] - s[-2])

    def at(d):
        d = np.asarray(d, dtype=float)
        p = np.column_stack([np.interp(d, s, path[:, k]) for k in range(3)])
        p[d < s[0]] = path[0] + (d[d < s[0]] - s[0])[:, None] * first
        p[d > s[-1]] = path[-1] + (d[d > s[-1]] - s[-1])[:, None] * last
        return p

    for mesh, length, behind in cars:
        front, back = at([s_head - behind + BOGIE * length, s_head - behind - BOGIE * length])
        axis = (front - back) / np.linalg.norm(front - back)
        lateral = np.cross([0, 0, 1], axis)
        lateral /= np.linalg.norm(lateral)
        up = np.cross(axis, lateral)
        frame = np.column_stack([axis, lateral, up])
        moved = mesh.copy()
        moved.points = mesh.points @ frame.T + (front + back) / 2
        placed.append(moved)
    return textured(placed[0].append_polydata(*placed[1:]))


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) > 1:
        raise SystemExit(__doc__)
    cars, texture = build(argv[0] if argv else None)
    # a curved, climbing test track: the train has to bend and pitch on it
    theta = np.linspace(0, np.pi / 2, 400)
    path = np.column_stack([300 * np.sin(theta), 300 * (1 - np.cos(theta)), 8 * theta])
    s = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(path, axis=0), axis=1))])
    train = place(cars, path, s, s_head=300.0)

    plotter = pv.Plotter(off_screen=True, window_size=(1600, 900))
    plotter.add_mesh(train, texture=texture, ambient=0.35, diffuse=0.7)
    plotter.add_mesh(pv.Spline(path, 400).tube(radius=0.3), color="#444444")
    # from ahead of the head and off to its right, looking back along the train
    k = np.searchsorted(s, 300.0)
    head, ahead = path[k], (path[k + 1] - path[k - 1]) / np.linalg.norm(path[k + 1] - path[k - 1])
    right = np.cross(ahead, [0, 0, 1])
    plotter.set_background("#cfd8e3")
    plotter.camera_position = [tuple(head + 22 * ahead + 28 * right + [0, 0, 9]),
                               tuple(head - 30 * ahead + [0, 0, 2]), (0, 0, 1)]
    out = Path(__file__).with_name("train_preview.png")
    plotter.screenshot(out)
    print(f"wrote {out}", flush=True)


if __name__ == "__main__":
    main()
