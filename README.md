# speed-simu

Runs of [SPEED](https://bitbucket.org/ilmaz/speed) on the cluster, through an
Apptainer image with SPEED compiled in it. Cases are in `cases/`; meshes are in
the submodule `data/meshes` ([speed-meshes](https://github.com/twinfall-repo/speed-meshes),
zstd-compressed in Git LFS, unpacked by `run_case.sh` when a run needs them).
Every script prints its options with `-h`.

## Clone and pull

Needs `git-lfs` (`git lfs install` once).

```bash
git clone --recurse-submodules git@github.com:twinfall-repo/speed-simu.git
git pull --recurse-submodules        # a plain git pull leaves the meshes as they were
git submodule update --init          # data/meshes empty: a clone without the submodule
```

## Build the image (once, and for every new SPEED)

```bash
source apptainer/build.sh            # -> apptainer/speed.sif
source apptainer/build.sh -f         # rebuild with the latest SPEED
```

## Run the test case

```bash
source apptainer/shell.sh -- bash run_case.sh -n 4 cases/rialba_source   # here, 4 processes
apptainer/submit.sh -- bash run_case.sh cases/rialba_source               # PBS job, a whole node
SPEED_NODES=2 apptainer/submit.sh -- bash run_case.sh cases/rialba_source # PBS job, two whole nodes
```

On more nodes, `mpirun` in the container reaches the others by ssh, which
must work without a password between the nodes (once, on the cluster):

```bash
ls ~/.ssh/id_ed25519 || ssh-keygen -t ed25519 -N '' -f ~/.ssh/id_ed25519
cat ~/.ssh/id_ed25519.pub >> ~/.ssh/authorized_keys
ssh-keyscan node{1..10} >> ~/.ssh/known_hosts
ssh -o BatchMode=yes node2 hostname
```

The time step is 24% of SPEED's deltat CFL, the most it takes without
warnings, found by a first setup-only run: `-c FRACTION` for another fraction,
`-c case` for the case's own `TIMESTEP` (see `bash run_case.sh -h`).

The run is in `output/rialba_source/<run>/` and archived in
`output/rialba_source/<run>.tar.zst`; `run_info.txt` there says what was run,
`speed.out` is SPEED's output. The PBS log is in `logs/`.

## A new case

```bash
mkdir cases/my_case
cp cases/rialba_source/{SPEED.input,*.mate} cases/my_case/                 # GRIDFILE my_mesh
ln -s ../../data/meshes/my_mesh.mesh cases/my_case/my_mesh.mesh
```

with `my_mesh.mesh.zst` added to speed-meshes (see its README).
