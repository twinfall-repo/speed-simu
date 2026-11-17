"""A low-detail textured train that runs along a path, for the movies:

    python movie/train.py [SIDE.png]        # writes movie/train_preview.png

Five cars after the Trenord "Donizetti" (Alstom Coradia Stream) that serve
the Lecco-Tirano line: about 110 m, 2.9 m wide, 4 m over the rail. The
dimensions are a likeness, not a drawing, and so is the livery, painted here
in a texture: white body, dark window band, green and blue stripes, a cab
face with a dark windscreen and two headlights. Any side view of a car can
replace the painted side, given as SIDE.png and stretched over both sides of
every car (its left edge goes to the car's front); the cabs keep their
painted face.

Each car is a cross-section swept along the car, with the texture's u along
the car and its v around the section, bottom of one side to the bottom of the
other over the roof. The two end cars taper into a nose over NOSE metres and
end in a cap carrying the cab's face; between cars the caps are dark, as a
gangway.

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
CARS = 5
WIDTH, HEIGHT, FLOOR = 2.90, 4.00, 0.45  # m, body width, roof over the rail, body bottom
NOSE = 3.5  # m over which an end car narrows into its nose
BOGIE = 0.35  # bogie centres at this fraction of the car length from its centre
WHITE, BAND, GREEN, BLUE, GREY, DARK, ROOF = (
    (238, 240, 240), (40, 44, 52), (0, 150, 70), (0, 75, 145), (120, 124, 128), (30, 30, 34),
    (185, 188, 192))
SIDE_U, FACE_U = 0.88, 0.90  # the texture's sides end at SIDE_U, a cab's face starts at FACE_U


def livery(side=None, width=2048, height=512):
    """The texture: the side of a car, front to the left, over u 0..SIDE_U
    (painted, or SIDE stretched there), and the face of a cab past FACE_U."""
    image = Image.new("RGB", (width, height), WHITE)
    draw = ImageDraw.Draw(image)
    y = lambda frac: int(height * (1 - frac))  # frac of the height, from the bottom
    x = lambda frac: int(width * frac)  # frac of the width, from the left
    end = x(SIDE_U)
    draw.rectangle([0, y(0.12), width, height], fill=DARK)  # underframe, cab too
    draw.rectangle([0, y(0.20), width, y(0.12)], fill=GREEN)  # skirt stripes, cab too
    draw.rectangle([0, y(0.23), width, y(0.20)], fill=BLUE)
    draw.rectangle([0, y(0.62), end, y(0.42)], fill=BAND)  # windows
    for door in (0.22, 0.78):  # two pairs of doors per car
        draw.rectangle([x(SIDE_U * (door - 0.035)), y(0.60), x(SIDE_U * (door + 0.035)), y(0.13)],
                       fill=GREY, outline=DARK, width=4)
    draw.rectangle([0, y(1.0), end, y(0.88)], fill=ROOF)
    if side:
        image.paste(Image.open(side).convert("RGB").resize((end, height)), (0, 0))
    face = x(FACE_U)
    draw.rectangle([face, y(0.88), width, y(0.52)], fill=BAND)  # windscreen
    for lamp in (0.2, 0.8):  # headlights
        cx = face + (width - face) * lamp
        draw.ellipse([cx - 8, y(0.33) - 8, cx + 8, y(0.33) + 8], fill=(255, 250, 220))
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
        cap = pv.PolyData(ring, np.column_stack([
            np.full(len(ring) - 2, 3), np.arange(len(ring) - 2), np.arange(1, len(ring) - 1),
            np.full(len(ring) - 2, len(ring) - 1)]).ravel())
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
    print(f"train: {CARS} cars, texture {'from ' + str(side) if side else 'painted'} "
          f"{image.size[0]} x {image.size[1]}", flush=True)
    cars, behind = [], 0.0
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
