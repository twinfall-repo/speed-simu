# rialba_ttb_nb — whole Rialba mesh + TTB-2D train loads, NORTHBOUND (2026-11-24)

Run (professor, PBS):  `apptainer/submit.sh -- bash run_case.sh -n NP cases/rialba_ttb_nb`
(same setup as `cases/rialba_ttb`; default `-c 0.24`).

- **Mesh** `rialba.mesh` -> `../../data/meshes/rialba.mesh` (unpacked by run_case.sh from `rialba.mesh.zst`).
- **Materials** `rialba_ttb_nb.mate`: MATE blocks 1-5, ABSO 6, FMAX 40, EXPN 0.0, identical to `rialba_ttb.mate` (2026-11-22).
- **Train** 2 x ETR 425 (double composition, 10 cars), MVO = empty (160 t per unit), 80 km/h, travelling
  SOUTH -> NORTH (Lecco -> Colico). TTB-2D (09_TRAIN_INPUT/TTB2D_ETR425_simulation: A00_Run_TWINFALL,
  parameters of 2026-11-24, Jacobs bogies as two half-bogies), FRA class 6 irregularity down to 0.2 m
  wavelength, FIXED profile (Profile_FRA6_min0.2m_seed1.mat).
- **Source** 498 vertical point loads PLOZ 1001-1498 (ordered S -> N), time histories
  `TTB2SPEED/F00001.txt ... F00498.txt` (FUNC type 3: 22992 samples, dt 1 ms, 0-22.99 s).
  Total force non-zero from ~1.5 s to ~21.9 s; minimum of the summed force -3165 kN (= weight of 2 x 160 t).
- **Load positions** fixed grid on railway.csv, s_rail = 730.35 ... 1028.55 m every 0.6 m
  (315 points open track, 107 avalanche gallery, 76 tunnel); stations face s = 850.2 (T109) ... 908.7 (T108),
  119.6 m of loaded track before T109 and after T108. x, y from railway.csv; z = surface of rialba.mesh
  + 0.05 m (`sleepers_meshZ_s730-1029.csv`, same method as rialba_ttb/z_check). The mesh surface is a
  staircase (voxel hexahedra 1.55 m near the stations, 4.64 m further away), so z jumps by one element
  where the track crosses a step; the mesh has no tunnel, tunnel loads are on the surface above it.
  No load point is missing (the 1.2 m TTB-2D "bridge" is outside the exported range).
- **Monitors** `LS.input`, 16 points (2026-11-26): 1-7 Geobit stations from north to south (T108, T106, T110, T107, T104, T105, T109; reordered, upstream rialba_ttb has 1-7 = T107, T104, T105, T109, T108, T106, T110), 8-11 tops of Towers 1-4, 12 the rock mass behind Tower 4 (fracture planes torrione1-2 ... 4-5 lie between consecutive points), 13-16 Trillium TR16, TR18, TR17, TR12 (top -> bottom; TR15 left out, no time sync). x, y = GPS UTM 32N - (527837.393, 5082191.470); z = mesh surface of the point's column (GPS heights are ~516.8 m above it, up to +-5 m on the steep Trillium line). All 16 found in place with MLST -500 0.
- **Southbound** uses EXACTLY the same PLOZ points; only the force files change (B72_MapToRailway with
  direction = 'southbound').
- **SPEED.input** as upstream rialba_ttb (2026-11-25), with MATFILE rialba_ttb_nb, STOPTIME 16.5, OPTIOUT 1 1 0 0 0 0 (displacement, velocity), MLST -500 0 (SPEED searches monitor nodes only with z > DEPTH; the stations are at z = -244 ... -239 m, so 0 would move them above z = 0). `TTB_loads_rail_northbound_summary.csv`:
  label, s_rail, X, Y, Z, kind, s_TTB, force file of every load.
