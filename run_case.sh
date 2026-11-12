#!/usr/bin/env bash
# Run SPEED on one case, inside the container, in a run folder of its own:
#
#     bash run_case.sh [-n NP] [-m MESH] [-c FRACTION] CASE_DIR
#     source apptainer/shell.sh -- bash run_case.sh -n 4 cases/rialba_source
#     apptainer/submit.sh -- bash run_case.sh cases/rialba_source
#     apptainer/submit.sh -d ../dtm_voxelization/output -- \
#         bash run_case.sh -m data/rialba/speed/rialba.mesh cases/rialba_source
#
# A case is a folder with SPEED.input and everything it names (the .mate, an
# LS.input with MLST, ...) and, usually, the mesh <GRIDFILE>.mesh as a relative symlink
# into data/. -m MESH runs the case on another mesh instead, any path visible
# in the container (data/ is whatever apptainer/shell.sh -d bound there).
# A mesh <name>.mesh.zst, as in the submodule data/meshes, is unpacked first.
#
# Options:
#   -n NP     MPI processes (default: $SPEED_NP, then 1)
#   -m MESH   mesh to use instead of the case's <GRIDFILE>.mesh
#   -c FRACTION
#             time step at FRACTION (0 < FRACTION <= 1) of SPEED's deltat CFL,
#             instead of the case's TIMESTEP (default 0.24); -c case keeps the
#             case's TIMESTEP
#
# SPEED's deltat CFL is h_min / vp, h_min the smallest distance between two GLL
# nodes of an element: Courant number 1 on the GLL spacing, above the
# stability limit of the leap-frog scheme. Unless -c case, SPEED runs first up to the
# end of its setup (SETUPONL T, output in speed_setup.out), reads deltat CFL
# there and writes TIMESTEP = FRACTION * deltat CFL in the SPEED.input of the run
# (the case's own is kept as SPEED.input.case), then runs SPEED. The default
# 0.24 is the largest that SPEED does not warn about: above 25% it warns that the
# absorbing boundaries may not work well, and its deltat CFL has 4 digits only.
#
# The case folder is never written: its files are copied to
# output/<case>/<run>, with the mesh linked as <GRIDFILE>.mesh, and SPEED runs
# there. <run> is the PBS job id when there is one, the time otherwise. The
# run folder holds run_info.txt (what was run, on what, with which SPEED),
# speed.out (SPEED's own output) and the results, and ends up archived in
# output/<case>/<run>.tar.zst, a single file to copy off the cluster
# (tar -I zstd -xf to unpack). zstd runs on all the cores the run had: gzip,
# on one core, took longer than SPEED itself on the binary VTK output.
# In a PBS job SPEED runs on the nodes of the job, SPEED_HOSTS, with orted
# started on the other nodes by SPEED_LAUNCH_AGENT (both from apptainer/shell.sh).
# SPEED_THREADS (default 1) is the OpenMP threads of each MPI process.
# The format of the VTKWRITE output is on its line of SPEED.input, e.g.
# VTKWRITE T 100 XDMF NOSTRAIN (see apptainer/speed.def).

set -euo pipefail

np="${SPEED_NP:-1}"
mesh=
cfl_fraction=0.24
while [ $# -gt 0 ]; do
    case "$1" in
        -n) np=$2; shift 2 ;;
        -m) mesh=$2; shift 2 ;;
        -c) cfl_fraction=$2; shift 2 ;;
        -h|--help) sed -n '2,45p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
        -*) echo "unknown option: $1" >&2; exit 1 ;;
        *)  break ;;
    esac
done
if [ $# -ne 1 ]; then
    echo "usage: bash run_case.sh [-n NP] [-m MESH] [-c FRACTION] CASE_DIR" >&2
    exit 1
fi
if ! [[ "${np}" =~ ^[1-9][0-9]*$ ]]; then
    echo "the number of MPI processes must be a positive integer, not '${np}'" >&2
    exit 1
fi
if [ "${cfl_fraction}" != case ] && ! awk -v f="${cfl_fraction}" 'BEGIN { exit !(f + 0 == f && f > 0 && f <= 1) }'; then
    echo "the fraction of deltat CFL must be a number in (0, 1] or case, not '${cfl_fraction}'" >&2
    exit 1
fi
threads="${SPEED_THREADS:-1}"

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
case_dir=$(cd "$1" && pwd)
case_name=$(basename "${case_dir}")
header="${case_dir}/SPEED.input"
if [ ! -f "${header}" ]; then
    echo "no SPEED.input in ${case_dir}" >&2
    exit 1
fi

# the names SPEED.input gives to the mesh and to the folders SPEED writes into
keyword() { awk -v key="$1" '$1 == key { print $2; exit }' "${header}"; }
gridfile=$(keyword GRIDFILE)
mpifile=$(keyword MPIFILE)
monfile=$(keyword MONFILE)
if [ -z "${gridfile}" ]; then
    echo "no GRIDFILE in ${header}" >&2
    exit 1
fi

if [ -n "${mesh}" ]; then
    echo "mesh:    ${mesh} (from -m)"
else
    mesh="${case_dir}/${gridfile}.mesh"
    echo "mesh:    ${mesh} (the case's own)"
fi

# a mesh kept compressed, as in the meshes submodule data/meshes, is unpacked
# next to its .zst: once, and again when the .zst is newer (a pulled mesh).
# Written aside and renamed, so that two runs starting together never read it half written
target=$(realpath -m "${mesh}")
if [ -f "${target}.zst" ]; then
    if head -c 100 "${target}.zst" | grep -q '^version https://git-lfs'; then
        echo "${target}.zst is a Git LFS pointer, not the mesh: install git-lfs, then" \
            "git lfs install && git submodule update --init" >&2
        exit 1
    fi
    if [ ! -f "${target}" ] || [ "${target}.zst" -nt "${target}" ]; then
        echo "unpack:  ${target}.zst ($(du -h "${target}.zst" | cut -f1)) -> ${target}"
        started=$(date +%s)
        zstd -d -q -f "${target}.zst" -o "${target}.tmp.$$"
        mv "${target}.tmp.$$" "${target}"
        echo "unpack:  $(du -h "${target}" | cut -f1), $(( $(date +%s) - started ))s"
    else
        echo "unpack:  not needed, ${target} is up to date with its .zst"
    fi
fi
if [ ! -f "${mesh}" ]; then
    echo "mesh not found: ${mesh} -- a dangling symlink? data/meshes is a submodule" \
        "(git submodule update --init), data/ is what apptainer/shell.sh -d bound" >&2
    exit 1
fi
mesh=$(realpath "${mesh}")

run_id="${PBS_JOBID:-$(date '+%Y%m%d_%H%M%S')}"
run_dir="${here}/output/${case_name}/${run_id}"
if [ -e "${run_dir}" ]; then
    echo "run folder already there: ${run_dir}" >&2
    exit 1
fi
mkdir -p "${run_dir}"

# every file of the case but the meshes, which are linked: they can be large.
# -xtype also takes the symlinks to files, which cp copies as files
find "${case_dir}" -maxdepth 1 -xtype f ! -name '*.mesh' -exec cp {} "${run_dir}/" \;
find "${case_dir}" -mindepth 1 -maxdepth 1 -type d -exec cp -r {} "${run_dir}/" \;
ln -s "${mesh}" "${run_dir}/${gridfile}.mesh"
cd "${run_dir}"
mkdir -p VTKOUT POST-PROC ${mpifile:+"${mpifile}"} ${monfile:+"${monfile}"}

{
    echo "case:      ${case_dir}"
    echo "run:       ${run_dir}"
    echo "mesh:      ${mesh} ($(du -hL "${mesh}" | cut -f1))"
    if [ -f /opt/speed-commit.txt ]; then
        echo "speed:     $(paste -sd ';' /opt/speed-commit.txt)"
    else
        echo "speed:     unknown, /opt/speed-commit.txt not there: not in the image?"
    fi
    echo "vtk:       $(grep -m1 '^ *VTKWRITE' "${header}" || echo 'none, no VTKWRITE line')"
    echo "host:      $(hostname)"
    echo "nodes:     ${SPEED_HOSTS:-this one only, not a PBS job}"
    echo "processes: ${np}"
    echo "threads:   ${threads} per process"
    echo "start:     $(date '+%F %T')"
    echo "files:     $(ls | tr '\n' ' ')"
} | tee run_info.txt

# on the nodes of the job: a single one is this one, more are reached by ssh
hosts=()
if [ -n "${SPEED_HOSTS:-}" ]; then
    hosts=(--host "${SPEED_HOSTS}" --launch-agent "${SPEED_LAUNCH_AGENT}")
fi
echo "mpirun:    -np ${np} ${hosts[*]-}" | tee -a run_info.txt
speed() { mpirun --display-map -np "${np}" ${hosts[@]+"${hosts[@]}"} -x OMP_NUM_THREADS="${threads}" SPEED; }

if [ "${cfl_fraction}" = case ]; then
    echo "cfl:       TIMESTEP of the case, $(awk '$1 == "TIMESTEP" { print $2; exit }' SPEED.input) (-c case)" \
        | tee -a run_info.txt
else
    # the setup run: no FAILCFL, which would stop it on the case's own TIMESTEP
    mv SPEED.input SPEED.input.case
    { grep -vE '^(SETUPONL|FAILCFL)' SPEED.input.case; echo "SETUPONL T"; } > SPEED.input
    started=$(date +%s)
    speed > speed_setup.out 2>&1 || true
    dt_cfl=$(sed -n 's/.*deltat CFL = *\([0-9.Ee+-]*\).*/\1/p' speed_setup.out | head -n 1)
    if ! grep -q 'Set-up ended' speed_setup.out || [ -z "${dt_cfl}" ]; then
        echo "the setup run for -c did not give deltat CFL; last lines of ${run_dir}/speed_setup.out:" >&2
        tail -n 30 speed_setup.out >&2
        exit 1
    fi
    dt=$(awk -v c="${dt_cfl}" -v f="${cfl_fraction}" 'BEGIN { printf "%.6e", c * f }')
    awk -v dt="${dt}" '$1 == "TIMESTEP" { $0 = "TIMESTEP   " dt; done = 1 } { print }
        END { if (!done) print "TIMESTEP   " dt }' SPEED.input.case > SPEED.input
    echo "cfl:       deltat CFL ${dt_cfl}, fraction ${cfl_fraction}: TIMESTEP ${dt}" \
        "(case's own $(awk '$1 == "TIMESTEP" { print $2; exit }' SPEED.input.case)), setup run $(( $(date +%s) - started ))s" \
        | tee -a run_info.txt
fi

started=$(date +%s)
status=0
speed > speed.out 2>&1 || status=$?
elapsed=$(( $(date +%s) - started ))
{
    # where the ranks ran, from the map mpirun writes at the top of speed.out
    grep 'Data for node:' speed.out | awk '!seen[$4]++ { printf "ranks:     %s on %s\n", $NF, $4 }' \
        || echo "ranks:     no map of mpirun in speed.out: it never launched"
    # SPEED replaces the time step it was given in some cases (see GET_CFL.f90)
    grep -m 1 'deltat chosen' speed.out | sed 's/^ */timestep:  SPEED REPLACED THE TIME STEP: /' || true
    echo "end:       $(date '+%F %T')"
    echo "elapsed:   ${elapsed}s"
    echo "exit:      ${status}"
} | tee -a run_info.txt

if [ "${status}" -ne 0 ]; then
    echo "SPEED FAILED with exit status ${status}; last lines of ${run_dir}/speed.out:" >&2
    tail -n 30 speed.out >&2
fi

# also after a failure: what SPEED did write is what tells why
archive="${run_dir}.tar.zst"
started=$(date +%s)
tar -I 'zstd -T0' -cf "${archive}" -C "$(dirname "${run_dir}")" "${run_id}"
size=$(du -sk "${run_dir}" | cut -f1)
packed=$(du -k "${archive}" | cut -f1)
echo "archive:   ${archive} ($(du -h "${archive}" | cut -f1) from $(du -sh "${run_dir}" | cut -f1)," \
    "ratio $(awk -v a="${size}" -v b="${packed}" 'BEGIN { printf "%.2f", a / b }')," \
    "$(( $(date +%s) - started ))s)" | tee -a run_info.txt
exit "${status}"
