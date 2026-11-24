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

On CINECA's Galileo100 (SLURM, Singularity 3.8, 48 cores a node) the same
image runs through `apptainer/submit_slurm.sh`, with `APPTAINER_BIN=singularity`
by default. The image cannot be built there (no root): copy `speed.sif` over.

```bash
apptainer/submit_slurm.sh -- bash run_case.sh cases/rialba_source               # a whole node
SPEED_NODES=2 apptainer/submit_slurm.sh -- bash run_case.sh cases/rialba_source # two
SPEED_QOS=g100_qos_lprod SPEED_WALLTIME=4-00:00:00 apptainer/submit_slurm.sh -- bash run_case.sh cases/rialba
```

`SPEED_ACCOUNT` is the budget (`saldo -b`), `SPEED_PARTITION` defaults to
`g100_usr_prod` (1 to 32 nodes, 24 h); `apptainer/submit_slurm.sh -h` lists
the rest. With `SPEED_MAIL` set (e.g. in `~/.bashrc`) the job mails, at its
end or when killed, the summary of `apptainer/job_summary.sh`, also kept as
`logs/<name>.<jobid>.summary`: queue wait, time and share of the walltime,
cores, peak memory of the first node, core hours and the budget left, SPEED's
progress, minutes and core hours per simulated second, what 25 s would cost,
the results and the scp that fetches them. Keep the runs under `$WORK`: `$CINECA_SCRATCH` deletes files older
than 40 days.

The time step is 24% of SPEED's deltat CFL, the most it takes without
warnings, found by a first setup-only run: `-c FRACTION` for another fraction,
`-c case` for the case's own `TIMESTEP` (see `bash run_case.sh -h`).

The run is in `output/rialba_source/<run>/` and archived in
`output/rialba_source/<run>.tar.zst`; `run_info.txt` there says what was run,
`speed.out` is SPEED's output. The PBS log is in `logs/`.

The Rialba cases write, every `VTKWRITE` steps, `VTKOUT/SPEED.xmf` for
ParaView with the displacement `Disp`, the velocity `Vel` at that step and
`VelVV`, the mean of v v^T over the steps since the previous snapshot (xx yy
zz xy yz zx): the snapshots are far sparser than the steps, so `Vel` aliases
what is faster than them, `VelVV` does not. √(eᵀ VelVV e) is the RMS velocity
along a direction e, √(tr VelVV) its magnitude. The three take 12 float32 per
GLL node and snapshot, four times the displacement alone; `NODISP` on the
`VTKWRITE` line leaves `Disp` out. The image builds SPEED's branch
`vtkwrite-velocity`, which has these words, until they are in master.

The points of the case's `LS.input` (the seven surveyed points and the five
towers, for the Rialba cases) are written by SPEED every `TMONITOR` steps
into `MONITOR/`, as raw binary split by MPI process. At the end of the run,
before the archive, `run_case.sh` gathers them with `monitors.py` into
`output/rialba/<run>/monitors/point_NN.txt`, one per point of `LS.input`:
time, then displacement, velocity, acceleration, stress, strain and rotation,
as many as `OPTIOUT` asks for. `run_info.txt` says how many points it wrote;
a failure is reported there and does not stop the archive. It needs the
image's python3 and numpy: an older image says so and leaves the gathering
to be done by hand, with Python and numpy anywhere:

```bash
python monitors.py output/rialba/<run>
```

## A new case

```bash
mkdir cases/my_case
cp cases/rialba_source/{SPEED.input,*.mate} cases/my_case/                 # GRIDFILE my_mesh
ln -s ../../data/meshes/my_mesh.mesh cases/my_case/my_mesh.mesh
```

with `my_mesh.mesh.zst` added to speed-meshes (see its README).
