#!/usr/bin/env bash
# Run SPEED on one case, inside the container, in a run folder of its own:
#
#     bash run_case.sh [-n NP] [-m MESH] CASE_DIR
#     source apptainer/shell.sh -- bash run_case.sh -n 4 cases/rialba_source
#     apptainer/submit.sh -- bash run_case.sh cases/rialba_source
#     apptainer/submit.sh -d ../dtm_voxelization/output -- \
#         bash run_case.sh -m data/rialba/speed/rialba.mesh cases/rialba_source
#
# A case is a folder with SPEED.input and everything it names (the .mate, an
# LS.input with MLST, ...) and, usually, the mesh <GRIDFILE>.mesh as a relative symlink
# into data/. -m MESH runs the case on another mesh instead, any path visible
# in the container (data/ is whatever apptainer/shell.sh -d bound there).
#
# Options:
#   -n NP     MPI processes (default: $SPEED_NP, then 1)
#   -m MESH   mesh to use instead of the case's <GRIDFILE>.mesh
#
# The case folder is never written: its files are copied to
# output/<case>/<run>, with the mesh linked as <GRIDFILE>.mesh, and SPEED runs
# there. <run> is the PBS job id when there is one, the time otherwise. The
# run folder holds run_info.txt (what was run, on what, with which SPEED),
# speed.out (SPEED's own output) and the results, and ends up archived in
# output/<case>/<run>.tar.gz, a single file to copy off the cluster.
# SPEED_THREADS (default 1) is the OpenMP threads of each MPI process;
# SPEED_VTK_FORMAT and SPEED_VTK_STRAIN the output of VTKWRITE (see
# apptainer/speed.def).

set -euo pipefail

np="${SPEED_NP:-1}"
mesh=
while [ $# -gt 0 ]; do
    case "$1" in
        -n) np=$2; shift 2 ;;
        -m) mesh=$2; shift 2 ;;
        -h|--help) sed -n '2,27p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
        -*) echo "unknown option: $1" >&2; exit 1 ;;
        *)  break ;;
    esac
done
if [ $# -ne 1 ]; then
    echo "usage: bash run_case.sh [-n NP] [-m MESH] CASE_DIR" >&2
    exit 1
fi
if ! [[ "${np}" =~ ^[1-9][0-9]*$ ]]; then
    echo "the number of MPI processes must be a positive integer, not '${np}'" >&2
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
if [ ! -f "${mesh}" ]; then
    echo "mesh not found: ${mesh} -- a dangling symlink? data/ is what apptainer/shell.sh -d bound" >&2
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
    echo "vtk:       format ${SPEED_VTK_FORMAT:-unset (xdmf)}, strain ${SPEED_VTK_STRAIN:-unset (1)}"
    echo "host:      $(hostname)"
    echo "processes: ${np}"
    echo "threads:   ${threads} per process"
    echo "start:     $(date '+%F %T')"
    echo "files:     $(ls | tr '\n' ' ')"
} | tee run_info.txt

started=$(date +%s)
status=0
mpirun -np "${np}" -x OMP_NUM_THREADS="${threads}" SPEED > speed.out 2>&1 || status=$?
elapsed=$(( $(date +%s) - started ))
{
    echo "end:       $(date '+%F %T')"
    echo "elapsed:   ${elapsed}s"
    echo "exit:      ${status}"
} | tee -a run_info.txt

if [ "${status}" -ne 0 ]; then
    echo "SPEED FAILED with exit status ${status}; last lines of ${run_dir}/speed.out:" >&2
    tail -n 30 speed.out >&2
fi

# also after a failure: what SPEED did write is what tells why
archive="${run_dir}.tar.gz"
tar -czf "${archive}" -C "$(dirname "${run_dir}")" "${run_id}"
echo "archive:   ${archive} ($(du -h "${archive}" | cut -f1))"
exit "${status}"
