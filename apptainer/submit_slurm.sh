#!/usr/bin/env bash
# Submit a SLURM job (CINECA's Galileo100) that runs one command inside the
# speed-simu image through apptainer/run.sh, on whole nodes: the SLURM twin
# of submit.sh.
#
#     apptainer/submit_slurm.sh [run.sh options] [--] command ...
#     SPEED_NODES=2 apptainer/submit_slurm.sh -- bash run_case.sh cases/rialba
#
# The log, stdout and stderr together, is logs/<name>.<jobid>.log in the
# repository. The environment at submission is exported to the job.
# SPEED_ACCOUNT    budget account (default pMI25_DMAT; see `saldo -b`)
# SPEED_PARTITION  partition (default g100_usr_prod: 1 to 32 nodes, 24 h)
# SPEED_QOS        QOS, e.g. g100_qos_lprod (1 to 2 nodes, 4 days); none by default
# SPEED_NODES      nodes (default 1)
# SPEED_PPN        MPI processes on each node (default 48 / SPEED_THREADS, the cores)
# SPEED_THREADS    OpenMP threads of each process (default 1)
# SPEED_WALLTIME   walltime (default 24:00:00)
# SPEED_NAME       name of the job and of its log (default speed-simu)
# APPTAINER_BIN    container runtime (default singularity)
# SPEED_IMAGE      the image (default apptainer/speed.sif)
# On more nodes mpirun in the container reaches the others by ssh, with the
# keys in ~/.ssh: as on kami, a key of your own in ~/.ssh/authorized_keys.

set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo=$(cd "${here}/.." && pwd)

case "${1:-}" in
    -h|--help) sed -n '2,22p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    "")        echo "no command given" >&2; exit 1 ;;
esac

logs="${repo}/logs"
mkdir -p "${logs}"

name="${SPEED_NAME:-speed-simu}"
nodes="${SPEED_NODES:-1}"
export SPEED_THREADS="${SPEED_THREADS:-1}"
per_node="${SPEED_PPN:-$(( 48 / SPEED_THREADS ))}"
export SPEED_NP="${SPEED_NP:-$(( nodes * per_node ))}"
export APPTAINER_BIN="${APPTAINER_BIN:-singularity}"
qos=()
[ -n "${SPEED_QOS:-}" ] && qos=(--qos "${SPEED_QOS}")

echo "name: ${name}"
echo "log:  ${logs}/${name}.<jobid>.log"
echo "account: ${SPEED_ACCOUNT:-pMI25_DMAT}, partition: ${SPEED_PARTITION:-g100_usr_prod}," \
    "qos: ${SPEED_QOS:-none}, walltime: ${SPEED_WALLTIME:-24:00:00}"
echo "resources: nodes=${nodes}, processes per node=${per_node}, in all processes=${SPEED_NP}," \
    "threads=${SPEED_THREADS}, runtime=${APPTAINER_BIN}"

sbatch --job-name "${name}" --account "${SPEED_ACCOUNT:-pMI25_DMAT}" \
    --partition "${SPEED_PARTITION:-g100_usr_prod}" ${qos[@]+"${qos[@]}"} \
    --nodes "${nodes}" --ntasks-per-node "${per_node}" --cpus-per-task "${SPEED_THREADS}" \
    --exclusive --mem 0 --time "${SPEED_WALLTIME:-24:00:00}" \
    --output "${logs}/${name}.%j.log" --export ALL --chdir "${PWD}" \
    --wrap "echo \"nodes: \${SLURM_JOB_NODELIST}\"; $(printf '%q ' "${here}/run.sh" "$@")"
