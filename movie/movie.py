"""The movie: the train along the lake, the whole mountain, then the towers:

    python movie/movie.py SCENE_DIR OUT_DIR low|high [FRAME ...]

SCENE_DIR is dtm_voxelization's output of the case (output/rialba): the
textured terrain and lake of `orthophoto`, the railway of `railway` and, if
there, the land and lake around them of `backdrop`; the overhead line of
catenary.py and the galleries, tunnel portals and rails of galleries.py
along the railway. The
train of train.py runs along the railway at SPEED, real time, and the camera
goes through its shots, keyed on where the head of the train is:

  follow    from S_START, abreast of the head of the train, out over the lake
  overview  from S_OUT the camera pulls back to the whole mountain
  towers    from S_IN, as the train comes out of the long avalanche gallery,
            it closes in on the towers of Rialba, and holds them to the end,
            as the train passes beneath and into its tunnel

between which it eases smoothly. low is 960 x 540 at 12 frames a second,
for a laptop; high 1920 x 1080 at 30, for the cluster. Frames go to
OUT_DIR/frames, then ffmpeg makes OUT_DIR/rialba_<quality>.mp4. Given FRAME
numbers, only those are rendered, and no video: to check a shot.

The SPEED solution is not in yet: when it is, its surface displacement at
each frame's time goes on the terrain the same way.
"""

import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pyvista as pv

import catenary
import galleries
from train import build, place

SPEED = 80 / 3.6  # m/s, as train_series.py
EASE = 220.0  # m of the train's run over which one shot eases into the next
S_IN = 634.0  # m along the railway, where the long gallery ends
S_START, S_OUT = 150.0, S_IN - EASE  # the overview reached just as the zoom in starts
OVERVIEW = ((-600.0, -4200.0, 1900.0), (0.0, 200.0, -150.0))  # camera, focal point
TOWERS = ((-720.0, -560.0, -80.0), (-240.0, 40.0, -170.0))
QUALITY = {"low": ((960, 540), 12), "high": ((1920, 1080), 30)}
SUN = ((-150.0, 300.0, 400.0), (-350.0, -300.0, -277.0))  # behind the towers, over the lake


def smooth(a, b, x):
    """0 before a, 1 after b, a smoothstep between."""
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


def follow(path, s, head):
    """Camera and focal point abreast of the head of the train, out over the
    lake, with the mountain behind it: the nose and the first cars in view."""
    k = np.searchsorted(s, head)
    ahead = path[min(k + 10, len(s) - 1)] - path[max(k - 10, 0)]
    ahead[2] = 0
    ahead /= np.linalg.norm(ahead)
    lake = -np.cross(ahead, [0, 0, 1])  # the lake lies left of the train running north-west
    front = np.array([np.interp(head - 15, s, path[:, i]) for i in range(3)])
    return front + 50 * ahead + 70 * lake + [0, 0, 22], front + [0, 0, 4]


def camera(path, s, head):
    """The camera at the head's arc length, eased between the three shots."""
    cam, focal = (np.array(v) for v in follow(path, s, head))
    out = smooth(S_OUT, S_OUT + EASE, head)
    cam, focal = (1 - out) * cam + out * np.array(OVERVIEW[0]), \
        (1 - out) * focal + out * np.array(OVERVIEW[1])
    closer = smooth(S_IN, S_IN + EASE, head)
    cam, focal = (1 - closer) * cam + closer * np.array(TOWERS[0]), \
        (1 - closer) * focal + closer * np.array(TOWERS[1])
    return cam, focal


def scene(scene_dir, size):
    plotter = pv.Plotter(off_screen=True, window_size=size)
    plotter.set_background("#b9cde0", top="#6f97c2")
    terrain = pv.read(scene_dir / "orthophoto_0.5m.vtp")
    photo = pv.read_texture(scene_dir / "orthophoto_0.5m.png")
    photo.interpolate = True  # bilinear, or close up the 0.5 m pixels show as blocks
    plotter.add_mesh(terrain, texture=photo, ambient=0.35, diffuse=0.7)
    water = pv.read_texture(scene_dir / "lake_water.png")
    water.repeat = True
    water.SetUseSRGBColorSpace(True)  # a PBR base colour has to be sRGB
    normal = pv.read_texture(scene_dir / "lake_normal.png")
    normal.repeat = True
    lakes = ["lake_0.5m.vtp"]
    backdrop = scene_dir / "backdrop.vtp"
    if backdrop.exists():  # the land and lake around the case, from dtm_voxelization
        around = pv.read_texture(scene_dir / "backdrop.png")
        around.interpolate = True
        plotter.add_mesh(pv.read(backdrop), texture=around, ambient=0.35, diffuse=0.7)
        lakes.append("backdrop_lake.vtp")
    for name in lakes:
        lake = plotter.add_mesh(pv.read(scene_dir / name), pbr=True, metallic=0.0,
                                roughness=0.15, opacity=0.92)
        lake.prop.SetBaseColorTexture(water)
        lake.prop.SetNormalTexture(normal)
    plotter.add_light(pv.Light(position=SUN[0], focal_point=SUN[1], intensity=1.5,
                               light_type="scene light"))
    print(f"scene {scene_dir}: terrain {terrain.n_cells:,} triangles, "
          f"{'with' if backdrop.exists() else 'no'} backdrop, lake, sun", flush=True)
    return plotter


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) < 3 or argv[2] not in QUALITY:
        raise SystemExit(__doc__)
    scene_dir, out, quality = Path(argv[0]), Path(argv[1]), argv[2]
    only = [int(f) for f in argv[3:]]
    size, fps = QUALITY[quality]
    frames_dir = out / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    track = np.loadtxt(scene_dir / "railway.csv")
    s, path = track[:, 0], track[:, 1:4]
    heads = np.arange(S_START, s[-1], SPEED / fps)  # to the end of the domain
    print(f"{quality}: {size[0]} x {size[1]} at {fps} fps, {len(heads)} frames, "
          f"{len(heads) / fps:.1f} s; head from s {S_START:g} to {s[-1]:.0f} m at "
          f"{SPEED * 3.6:.0f} km/h; shots follow, overview from s {S_OUT:g}, towers from "
          f"s {S_IN:g} to the end", flush=True)

    plotter = scene(scene_dir, size)
    concrete, openings, tunnels = galleries.build(track)
    plotter.add_mesh(galleries.rails(track), color="#6b6660", specular=0.6, ambient=0.35, diffuse=0.7)
    terrain = plotter.meshes[0]  # the orthophoto's uv is affine in x, y: the tunnels take it too
    xy1 = lambda points: np.column_stack([points[:, :2], np.ones(len(points))])
    affine = np.linalg.lstsq(xy1(terrain.points), terrain.point_data["uv"], rcond=None)[0]
    tunnels.point_data["uv"] = xy1(tunnels.points) @ affine
    tunnels.active_texture_coordinates = tunnels.point_data["uv"]
    photo = pv.read_texture(scene_dir / "orthophoto_0.5m.png")
    photo.interpolate = True
    plotter.add_mesh(tunnels, texture=photo, ambient=0.35, diffuse=0.7)
    plotter.add_mesh(concrete, color="#a29e94", ambient=0.35, diffuse=0.7)
    plotter.add_mesh(openings, color="#151515", ambient=0.35, diffuse=0.7)
    masts, wires = catenary.build(track)
    plotter.add_mesh(masts, color="#8a8f94", ambient=0.35, diffuse=0.7)
    plotter.add_mesh(wires, color="#3a3a3a", line_width=size[0] / 960)  # a pixel wide in low, two in high
    cars, texture = build()
    train = place(cars, path, s, heads[0])
    plotter.add_mesh(train, texture=texture, ambient=0.35, diffuse=0.7)

    t0 = time.perf_counter()
    for n in only or range(len(heads)):
        train.points = place(cars, path, s, heads[n]).points
        cam, focal = camera(path, s, heads[n])
        plotter.camera_position = [tuple(cam), tuple(focal), (0, 0, 1)]
        plotter.camera.clipping_range = (1.0, 12000.0)
        plotter.render()  # off screen, a screenshot does not render by itself
        frame = frames_dir / f"frame_{n:05d}.png"
        plotter.screenshot(frame)
        if only or n % 50 == 0:
            print(f"  frame {n}: head at s {heads[n]:.0f} m, camera {cam.round(0)} -> "
                  f"{focal.round(0)}, {time.perf_counter() - t0:.0f}s so far", flush=True)
    plotter.close()
    if only:
        return

    video = out / f"rialba_{quality}.mp4"
    command = ["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(fps),
               "-i", str(frames_dir / "frame_%05d.png"), "-c:v", "libx264", "-crf", "18",
               "-pix_fmt", "yuv420p", str(video)]
    print(f"  {' '.join(command)}", flush=True)
    subprocess.run(command, check=True)
    print(f"wrote {video}: {video.stat().st_size / 1024**2:.1f} MB", flush=True)


if __name__ == "__main__":
    main()
