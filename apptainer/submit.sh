#!/usr/bin/env bash
# Submit a PBS job that runs one command inside the speed-simu
# image through apptainer/run.sh, alone on one node of the cluster.
#
#     apptainer/submit.sh [run.sh options] [--] command ...
#     apptainer/submit.sh -- bash run_case.sh cases/rialba_source
#     apptainer/submit.sh -o $HOME/speed_runs -- bash run_case.sh cases/rialba_source
#
# The arguments go to apptainer/run.sh unchanged, so relative paths in the
# command are relative to the repository (/workspace in the container), and
# relative paths in the options are relative to the folder you submit from.
# The environment at submission (APPTAINER_BIN, SPEED_IMAGE, SPEED_OUTPUT, ...) is
# exported to the job (qsub -V). The job log, stdout and stderr together, is
# written to logs/<name>.<jobid>.log in the repository, with the node, its
# processors, memory and the threads at the start and the peak memory of the job at
# the end. logs/<name>.<jobid>.mem holds a single line, rewritten every 30
# seconds, with the current and the peak memory, which survives a job killed for
# exceeding its memory. At the end the job writes a summary in the queue shared by
# all the projects, ~/.job_notify/<name>.<jobid>.done, that ~/bin/job_notify.sh
# (apptainer/notify.sh of pg_paper) mails from the login node.
# Resources: SPEED_NCPUS (default 96) and SPEED_MEM_GB, memory in gigabytes
# (default 500), e.g. SPEED_MEM_GB=128 SPEED_NCPUS=16 apptainer/submit.sh ...
# The defaults are a whole node (two AMD EPYC 7413, 48 cores with two hardware
# threads each, that PBS counts as 96 ncpus, and 503 GB), reserved exclusively
# (place=excl) so that no other job changes the timings.
# SPEED_NODES (default 1) is the number of such nodes: SPEED_NCPUS and
# SPEED_MEM_GB are per node, and mpirun reaches the other nodes by ssh (see
# apptainer/shell.sh). The memory sampled is that of the first node only.
# SPEED_PPN is the MPI processes on each node (default SPEED_NCPUS / 2 /
# SPEED_THREADS, its physical cores): fewer than those, e.g. to compare 48
# processes on one node with 24 on each of two, still on whole nodes. Asking
# fewer SPEED_NCPUS instead lets PBS pick kurama, the GPU node, which fails.
# SPEED_NAME is the name of the job and of its log (default speed-simu).
# SPEED is hybrid MPI and OpenMP: SPEED_THREADS OpenMP threads (default 1) on
# each of SPEED_NP MPI processes, by default as many as fit on the physical
# cores, half of SPEED_NCPUS on each node, i.e.
# SPEED_NODES * SPEED_NCPUS / 2 / SPEED_THREADS. Both reach
# run_case.sh through apptainer/shell.sh, which uses SPEED_NP when not given -n.

set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo=$(cd "${here}/.." && pwd)

case "${1:-}" in
    -h|--help) sed -n '2,38p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    "")        echo "no command given" >&2; exit 1 ;;
esac

logs="${repo}/logs"
mkdir -p "${logs}"

name="${SPEED_NAME:-speed-simu}"
nodes="${SPEED_NODES:-1}"
ncpus="${SPEED_NCPUS:-96}"
export SPEED_THREADS="${SPEED_THREADS:-1}"
# the MPI processes on each node, which PBS writes in PBS_NODEFILE
per_node="${SPEED_PPN:-$(( ncpus / 2 / SPEED_THREADS ))}"
export SPEED_NP="${SPEED_NP:-$(( nodes * per_node ))}"
mem_gb="${SPEED_MEM_GB:-500}"

# The job script. What is expanded here is fixed at submission: the log folder,
# the submission folder and the command. What is escaped (\$) is expanded when the
# job runs: PBS_JOBID, the pids and the memory. The job writes its own log
# straight into logs/: the copy of the PBS output back to the submission host fails
# on this cluster (a "Post job file processing error" mail), so PBS keeps its
# output in the home on the node (-k oe), an empty <name>.o<jobid> that the job
# removes at the end. The job starts in the home directory, so it goes back to the
# submission folder.
# The command runs in the background, while the job samples the memory of the
# process tree of run.sh, the container included, and not of the other processes
# of the user on the node.
job=$(cat <<EOF
log=$(printf '%q' "${logs}")/${name}.\${PBS_JOBID}.log
exec > "\$log" 2>&1
mem_file=$(printf '%q' "${logs}")/${name}.\${PBS_JOBID}.mem
mkdir -p "\${HOME}/.job_notify"
done_file="\${HOME}/.job_notify/${name}.\${PBS_JOBID}.done"
start=\$(date +%s)
cd $(printf '%q' "${PWD}") || exit 1

# a memory in kB as MB, or as GB from 1 GB on, and a time in seconds as minutes and
# seconds, or as hours and minutes from 1 hour on
human_mem() {
    if (( \$1 >= 1048576 )); then
        awk -v kb="\$1" 'BEGIN { printf "%.1f GB", kb / 1048576 }'
    else
        echo "\$(( \$1 / 1024 )) MB"
    fi
}
human_time() {
    if (( \$1 >= 3600 )); then
        printf '%dh %02dm' \$(( \$1 / 3600 )) \$(( \$1 % 3600 / 60 ))
    else
        printf '%dm %02ds' \$(( \$1 / 60 )) \$(( \$1 % 60 ))
    fi
}

echo "node: \$(hostname)"
lscpu | grep -E "Model name|Socket|Core|Thread"
free -g | grep Mem
echo "nodes: \$(sort -u "\$PBS_NODEFILE" | paste -sd ' ')"
echo "processes: ${SPEED_NP}, threads per process: ${SPEED_THREADS}"

$(printf '%q ' "${here}/run.sh" "$@") &
run_pid=\$!

# the pids of the process tree rooted at \$1, comma separated
tree() {
    ps -e -o pid=,ppid= | awk -v root="\$1" '
        { parent[\$1] = \$2 }
        END {
            for (p in parent) {
                q = p
                while (q in parent && q != root && q > 1) q = parent[q]
                if (q == root && p != root) printf "%s,", p
            }
            print root
        }'
}

peak=0
while kill -0 "\$run_pid" 2>/dev/null; do
    pids=\$(tree "\$run_pid")
    total=\$(ps -o rss= -p "\$pids" | awk '{ s += \$1 } END { print s + 0 }')
    if (( total > peak )); then peak=\$total; fi
    echo "\$(date '+%F %T')  memory \$(human_mem "\$total"), peak \$(human_mem "\$peak")" > "\$mem_file"

    # wait 30 seconds, but stop as soon as the command ends
    for _ in \$(seq 30); do
        kill -0 "\$run_pid" 2>/dev/null || break
        sleep 1
    done
done

status=0
wait "\$run_pid" || status=\$?
echo "peak memory of the job: \$(human_mem "\$peak"), exit status \${status}"

# the summary for the mail: the subject on the first line, then the body; written
# aside and renamed, so that the notification script never reads it half written
end=\$(date +%s)
elapsed=\$(human_time \$(( end - start )))
outcome=finished
(( status == 0 )) || outcome=FAILED
{
    echo "[speed-simu] ${name} \${outcome}, exit \${status}, \${elapsed}"
    echo "job:         ${name} (\${PBS_JOBID})"
    echo "command:     $(printf '%q ' "$@")"
    echo "node:        \$(hostname)"
    echo "start:       \$(date -d "@\$start" '+%F %T')"
    echo "end:         \$(date -d "@\$end" '+%F %T')"
    echo "elapsed:     \${elapsed}"
    echo "exit status: \${status}"
    echo "peak memory: \$(human_mem "\$peak")"
    echo "log:         \$log"
    echo
    echo "last lines of the log:"
    tail -n 20 "\$log"
} > "\${done_file}.tmp" && mv "\${done_file}.tmp" "\$done_file"
rm -f "\${HOME}/${name}.o\${PBS_JOBID%%.*}"
exit "\${status}"
EOF
)

echo "name: ${name}"
echo "log:  ${logs}/${name}.<jobid>.log"
echo "resources: nodes=${nodes}, each ncpus=${ncpus}, mem=${mem_gb} GB, processes=${per_node};" \
    "in all processes=${SPEED_NP}, threads=${SPEED_THREADS}"
echo "${job}" | qsub -V -N "${name}" -l "select=${nodes}:ncpus=${ncpus}:mpiprocs=${per_node}:mem=${mem_gb}gb" \
    -l place=scatter:excl -j oe -k oe
