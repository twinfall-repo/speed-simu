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
| `backdrop` | `backdrop.png`, `backdrop.vtp`, `backdrop_lake.vtp` | the land and lake 6 km around the DTM, with a hole where it is: the Copernicus DEM GLO-30 (30 m, open data), joined to the DTM along its edge, under the same national photo at 1 m. `movie.py` takes it when it is there. |

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

`train.py` builds a five-car train after Trenord's "Donizetti" (about 112 m),
low detail, with a painted livery texture; `python train.py side.png` uses a
side view of a real car instead. `train_series.py` writes the train running
along the railway at 80 km/h as `train_NNNN.vtu`, one every 0.2 s, with
`train.pvd`, the time series, and `train_texture.png`.

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
| `S_START` 150 | abreast of the train, out over the lake |
| `S_OUT` 420 | eases (over `EASE` m) into `OVERVIEW`, the whole mountain |
| `S_IN` 700 | eases into `TOWERS`, the towers with the shore below |
| `S_BACK` 1180 | while the train is in the north-western tunnel, eases back abreast of it, to see it come out and run to the end of the domain |

`OVERVIEW` and `TOWERS` are (camera, focal point) pairs in the DTM's frame;
`SUN` the light that makes the lake glint.

On the cluster, through the dtm_voxelization image (it has pyvista's vtk) or
any Python with pyvista and ffmpeg, off screen.

## Still to do

- The SPEED run with sources along the railway, then its surface field on the
  terrain in `movie.py`, frame by frame at the train's time.
- AGEA 2021 at 20 cm, when Regione Lombardia sends it: `orthophoto` takes it
  as is, at `PIXEL` 0.2.
