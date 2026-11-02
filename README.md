# speed-simu

Runs of [SPEED](https://bitbucket.org/ilmaz/speed) on the cluster, through an
Apptainer image. The image holds only the toolchain (gfortran, OpenMPI, METIS)
and SPEED, compiled in `/opt/speed`; the cases, the meshes and the run script
are in this repository, bind-mounted at `/workspace` when the container runs.
A new case or a new mesh needs no rebuild, only a new SPEED does.

The pre- and post-processing scripts (monitors, DTM resampling, ...) stay in
`speed-repo`; the meshes come from `dtm_voxelization`.

## Layout

```
apptainer/
  speed.def        the image: SPEED cloned and compiled at build time
  build.sh         build it              -> apptainer/speed.sif
  shell.sh         shell in the image, repo at /workspace
  run.sh           one command in the image, non-interactively
  submit.sh        one command as a PBS job, through run.sh
run_case.sh        run SPEED on one case (inside the container)
cases/<case>/      SPEED.input, .mate, LS.input, <GRIDFILE>.mesh -> ../../data/...
data/meshes/       small meshes kept in the repository
output/            the runs, not tracked: output/<case>/<run>[.tar.gz]
logs/              the PBS job logs, not tracked
```

## Build (once, and for every new SPEED)

```bash
source apptainer/build.sh           # -> apptainer/speed.sif
source apptainer/build.sh -f        # rebuild, with the latest SPEED
```

The compiled SPEED commit is printed by the build and is in
`/opt/speed-commit.txt` in the image; every run copies it into its
`run_info.txt`. SPEED's Makefile leaves `OPT_FLAGS` undefined: the image
compiles with `OPT_FLAGS=-O3`. If the build dies with "no space left on
device":

```bash
export APPTAINER_TMPDIR=/scratch/$USER/apptainer_tmp
export APPTAINER_CACHEDIR=/scratch/$USER/apptainer_cache
```

## Run a case

Interactively, e.g. on a laptop or for a short test:

```bash
source apptainer/shell.sh -- bash run_case.sh -n 4 cases/rialba_case1
source apptainer/shell.sh                      # or a shell, then the same inside
```

As a PBS job, a whole node by default (96 ncpus, i.e. 48 physical cores, 500 GB,
exclusive):

```bash
apptainer/submit.sh -- bash run_case.sh cases/rialba_case1
SPEED_NCPUS=32 SPEED_MEM_GB=64 apptainer/submit.sh -- bash run_case.sh cases/rialba_case1
SPEED_NAME=rialba_case1 apptainer/submit.sh -- bash run_case.sh cases/rialba_case1
```

SPEED is hybrid MPI and OpenMP: `SPEED_THREADS` OpenMP threads (default 1) on
each of `SPEED_NP` MPI processes, which `submit.sh` sets by default to
`SPEED_NCPUS / 2 / SPEED_THREADS`, and `-n` of `run_case.sh` overrides. MPI runs
inside the container, so a run is on one node.

`run_case.sh` never writes in the case folder: it copies the case files to
`output/<case>/<run>` (`<run>` is the PBS job id, or the time), links the mesh
there as `<GRIDFILE>.mesh`, runs SPEED with its output in `speed.out`, writes
what was run in `run_info.txt` and archives the whole folder in
`output/<case>/<run>.tar.gz`.

### Other data and other output folders

`data/` and `output/` in the container are the repository's own, unless bound
elsewhere with `-d` and `-o` (the same for `shell.sh`, `run.sh` and
`submit.sh`), or with `SPEED_DATA` and `SPEED_OUTPUT`. To run a case on a mesh
written by dtm_voxelization, bind its output as data and pick the mesh with
`-m`:

```bash
apptainer/submit.sh -d ../dtm_voxelization/output -o /scratch/$USER/speed -- \
    bash run_case.sh -m data/rialba/speed/rialba.mesh cases/rialba_case1
```

The output folder of `run_case.sh` is `output/` of the repository *inside*
the container, i.e. whatever `-o` bound there.

## A new case

```bash
mkdir cases/my_case
cp cases/rialba_case1/{SPEED.input,LS.input,*.mate} cases/my_case/
ln -s ../../data/meshes/my_mesh.mesh cases/my_case/my_mesh.mesh   # GRIDFILE my_mesh
```

Small meshes go in `data/meshes/`; large ones stay outside the repository and
come in with `-d` (the symlink then resolves into the bound folder) or `-m`.

## Mail at the end of a job

`submit.sh` writes a summary of every finished job in `~/.job_notify/`, the
queue shared with pg_paper and dtm_voxelization; `~/bin/job_notify.sh`, set up
once from `apptainer/notify.sh` of pg_paper, mails them from the login node.
