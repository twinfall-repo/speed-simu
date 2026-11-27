# The Rialba movie

A train runs along the Lecco–Tirano railway under the towers of Rialba, over
the textured mountain and lake; the camera follows it, pulls back to the
whole mountain, and closes in on the towers as it passes beneath them. Once
the SPEED run with sources along the railway is done, its surface field goes
on the terrain.

The scene is built in [dtm_voxelization](https://github.com/compgeo-mox/dtm_voxelization)
(terrain, orthophoto, lake, railway, all in the DTM's frame, the frame of the
SPEED meshes) and rendered here. Paths below are relative to the folder
holding both repositories.

## 1. The scene (dtm_voxelization)

```bash
cd dtm_voxelization
python -m dtm_voxelization.railway cases/rialba.toml
python -m dtm_voxelization.pcn_orthophoto cases/rialba.toml
python -m dtm_voxelization.orthophoto cases/rialba.toml 0.5 data/orthophoto/rialba_pcn2012.tif
python -m dtm_voxelization.backdrop cases/rialba.toml
```

| step | writes, in `output/rialba/` | |
|---|---|---|
| `railway` | `railway.csv`, `railway.vtu` | the track from OpenStreetMap (ODbL), every 2 m, `s x y z kind`: kind 0 open, 1 avalanche gallery, 2 tunnel. The OSM answer is cached in `data/xyz/railway_osm.json`, so it runs offline. |
| `pcn_orthophoto` | `data/orthophoto/rialba_pcn2012.tif` (in the repository, JPEG-compressed: fetched once) | AGEA's 2012 orthophoto, 50 cm, over the whole DTM, from the Geoportale Nazionale's WMS (no access constraints stated; credit "Geoportale Nazionale – Ortofoto AGEA 2012"). |
| `orthophoto` | `orthophoto_0.5m.png`, `orthophoto_0.5m.vtp` | the photo, colour-graded against its blue haze, as one texture, and the terrain every 2 m with its texture coordinates |
| | `lake_0.5m.vtp`, `lake_water.png`, `lake_normal.png` | the lake's surface, flat at 198 m a.s.l. over the DTM's bathymetry, with a tile of water and a normal map of ripples |
| `backdrop` | `backdrop.png`, `backdrop.vtp`, `backdrop_lake.vtp` | the land and lake 6 km around the DTM, with a hole where it is: Regione Lombardia's DTM 5x5 (2015, bare ground, from its geoportal's ImageServer), joined to the DTM along its edge, under the same national photo at 1 m. Both are kept in `data/dem/rialba_backdrop_dtm5.tif` and `data/orthophoto/rialba_backdrop_pcn2012.tif`. The national WMS fails on a few spots (a broken file on its side), so the photo is fetched in 500 px pieces, split down to 125 px where it fails, and what still fails is left black and logged as `PHOTO MISSING`. `movie.py` takes the backdrop when it is there. |

0.5 m is the national photo's own resolution: a finer texture needs a finer
photo (AGEA 2021, 20 cm, on request from Regione Lombardia,
sit_rl@regione.lombardia.it; its public services do not export).

## 2. The train (here)

```bash
cd codes/speed-simu/movie
python train.py                       # train_preview.png: the train on a test curve
python train_series.py ../../../dtm_voxelization/output/rialba/railway.csv \
    ../../../dtm_voxelization/output/rialba/train
```

`train.py` builds the double trainset of the TTB-2D loads, two coupled units of five cars after Trenord's "Donizetti" (about 225 m),
low detail, with a painted livery texture; `python train.py side.png` uses a
side view of a real car instead. `train_series.py` writes the train running
along the railway at 80 km/h as `train_NNNN.vtu`, one every 0.2 s, with
`train.pvd`, the time series, and `train_texture.png`.

`catenary.py` builds the overhead line, which `movie.py` adds by itself: a
mast every 50 m on the open track, on the lake side, with its brackets, the
contact wire and the messenger wire sagging between masts (`python
catenary.py ../../../dtm_voxelization/output/rialba/railway.csv` for
`catenary_preview.png`). A likeness: the masts are not where the real ones are.

`galleries.py` builds, from the `kind` of `railway.csv`, the avalanche
galleries (kind 1: a wall on the mountain side, the roof, a pillar every 8 m
on the lake side), the tunnels (kind 2) as solid tubes that hide the train,
draped by `movie.py` in the orthophoto where the DTM leaves them in the open,
a portal at each of their mouths, and the two rails at standard gauge
outside the tunnels, which
`movie.py` adds too (`python galleries.py .../railway.csv` for
`galleries_preview.png`). In the galleries the wires hang from the roof: no
masts there.

## 3. Looking at it in ParaView

- **Terrain**: open `orthophoto_0.5m.vtp`, Coloring *Solid Color* (white),
  Properties > *Texture* > *Load…* `orthophoto_0.5m.png`, tick *Interpolate
  Textures*.
- **Lake**: open `lake_0.5m.vtp`, Coloring *Solid Color*, *Interpolation* PBR,
  *Texture* `lake_water.png`, *Normal Texture* `lake_normal.png`, Roughness
  about 0.15, Opacity about 0.9. Add a light facing the camera
  (*View > Light Inspector*) for the glints on the ripples.
- **Train**: open `train.pvd`, Coloring *Solid Color*, *Texture*
  `train_texture.png`, and press Play. For a look without the texture, colour
  by `rgb` with *Map Scalars* off. *Threshold* on `kind` < 2 hides the cars in
  a tunnel.
- **Railway**: open `railway.vtu`, colour by `kind`.

## 4. The movie

```bash
python movie.py ../../../dtm_voxelization/output/rialba OUT_DIR low            # laptop
python movie.py ../../../dtm_voxelization/output/rialba OUT_DIR high           # cluster
python movie.py ../../../dtm_voxelization/output/rialba OUT_DIR low 0 220 440  # check shots
```

`low` is 960 × 540 at 12 frames a second (450 frames, under 3 minutes on a
laptop), `high` 1920 × 1080 at 30. The frames go to `OUT_DIR/frames`, ffmpeg
makes `OUT_DIR/rialba_<quality>.mp4`. Given frame numbers, only those are
rendered, without the video.

The shots are keyed on the arc length of the train's head, constants at the
top of `movie.py`:

| from s (m) | shot |
|---|---|
| `S_START` 150 | abreast of the head of the train, out over the lake: the nose and the first cars |
| `S_OUT` 414 | eases (over `EASE` m) into `OVERVIEW`, the whole mountain, reached just as the next shot starts |
| `S_IN` 634 | as the train comes out of the long avalanche gallery, eases into `TOWERS`, the towers with the shore below, held to the end |

`OVERVIEW` and `TOWERS` are (camera, focal point) pairs in the DTM's frame;
`SUN` the light that makes the lake glint.

On the cluster, through the dtm_voxelization image (it has pyvista's vtk) or
any Python with pyvista and ffmpeg, off screen.

## 5. The movie of a SPEED run with the train loads

```bash
python movie/speed_movie.py RUN_DIR SCENE_DIR OUT_DIR low|high [FIELD] [log] [FRAME ...]
```

From the repository's root. `RUN_DIR` is a run of `cases/rialba_ttb` or
`cases/rialba_ttb_nb` (its `VTKOUT/` and `monitors/`, from `run_case.sh`),
`SCENE_DIR` the scene of step 1, `FIELD` one of `Disp_x` (the default) ...
`Vel_z`. The train runs as in the loads of `TTB2SPEED` (an axle is over a
load when it first reaches half its peak), the field spreads over the
orthophoto, and the five points over the towers move in a plot below,
marked in the view with the same colours. The field goes from the free
surface of the voxel mesh to a raster on the terrain, at 0.5 m (`SAMPLE`):
each node takes the value on the voxel top over it with SPEED's own
biquadratic basis on its 3 x 3 nodes (linear on slanted faces). Then, for
the picture, a Gaussian smoothing over half the element size under each
node (`SMOOTHING`), which rounds off the 4.7 m elements and the steps of the
staircase and leaves the 1.57 m ones nearly as they are, and a cubic
resampling to 0.25 m (`PIXEL`), drawn as the terrain's texture. The colours are linear, clear around zero, opaque towards
the 99.9 percentile of |value| over the run; with `log`, a signed log scale
over 3 decades. The movie runs 2x slower than the simulation (`SLOW`),
the field interpolated between snapshots. Constants at the top of the
script: `MONITORS`, `CAMERA`, `SLOW`, `CLIP`, `DECADES` (with `log`), `SAMPLE`, `PIXEL`, `SMOOTHING`; the shots
`FOLLOW`, `FAR`, `HOLD`, `EASE`, `SMOOTH`; `FONT` of the labels.

The solution is too heavy to bring home: render on the cluster, with the
SPEED image (pyvista, matplotlib and ffmpeg are in it, off screen through
Mesa's software EGL), the scene copied there once:

```bash
scp -r dtm_voxelization/output/rialba/{orthophoto_0.5m.*,lake*,backdrop*,railway.csv} CLUSTER:SCENE_DIR/
SPEED_NODES=1 SPEED_WALLTIME=04:00:00 apptainer/submit_slurm.sh -- \
    python3 movie/speed_movie.py RUN_DIR SCENE_DIR OUT_DIR high
```

Or at the end of the run itself, after `surface.py`: with `SPEED_MOVIE` the
scene folder, relative to the repository, `run_case.sh` writes
`RUN_DIR/movie/speed_high_Disp_x.mp4` (log in `movie.log`):

```bash
SPEED_MOVIE=scene SPEED_NODES=20 apptainer/submit_slurm.sh -- bash run_case.sh cases/rialba_ttb_nb
```

## Still to do

- The SPEED run with sources along the railway, then its surface field on the
  terrain in `movie.py`, frame by frame at the train's time.
- AGEA 2021 at 20 cm, when Regione Lombardia sends it: `orthophoto` takes it
  as is, at `PIXEL` 0.2.
