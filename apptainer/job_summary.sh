#!/usr/bin/env bash
# The summary of a SLURM job of submit_slurm.sh, written at its end to
# logs/<name>.<jobid>.summary and mailed to SPEED_MAIL:
#
#     apptainer/job_summary.sh STATUS START PEAK_KB LOG [NOTE]
#
# STATUS the exit status of the command, START its start (epoch seconds),
# PEAK_KB the peak memory of the first node's process tree, LOG the job log,
# NOTE e.g. why it was killed. The run of run_case.sh, if any, is
# output/<case>/<jobid> under SPEED_OUTPUT (default output/ of the repository).

set -uo pipefail

status=$1 start=$2 peak_kb=$3 log=$4 note=${5:-}
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo=$(cd "${here}/.." && pwd)
id=${SLURM_JOB_ID:?not in a SLURM job}
name=${SLURM_JOB_NAME:-speed-simu}
summary="${log%.log}.summary"
end=$(date +%s)

hm() { printf '%dh %02dm' $(( $1 / 3600 )) $(( $1 % 3600 / 60 )); }
gb() { awk -v kb="$1" 'BEGIN { printf "%.1f GB", kb / 1048576 }'; }

nodes=${SLURM_JOB_NUM_NODES:-1}
ncpus=$(( nodes * ${SLURM_CPUS_ON_NODE:-48} ))
elapsed=$(( end - start ))
core_h=$(awk -v s="${elapsed}" -v c="${ncpus}" 'BEGIN { printf "%.0f", s * c / 3600 }')
submit=$(sacct -n -X -j "${id}" --format=Submit 2>/dev/null | head -1 | tr -d ' ')
wait_s=""
[ -n "${submit}" ] && wait_s=$(( start - $(date -d "${submit}" +%s) ))
limit=$(squeue -h -j "${id}" -o %l 2>/dev/null)
limit_s=$(echo "${limit}" | awk -F'[-:]' '{ n = NF; s = $n + 60 * $(n-1) + 3600 * (n > 2 ? $(n-2) : 0) + 86400 * (n > 3 ? $(n-3) : 0); print s }')

outcome=finished
(( status == 0 )) || outcome=FAILED
[ -n "${note}" ] && outcome="KILLED (${note})"

run_dir=$(ls -d "${SPEED_OUTPUT:-${repo}/output}"/*/"${id}" 2>/dev/null | head -1)

{
echo "job:          ${name} (${id}), ${outcome}, exit ${status}"
echo "command:      ${SPEED_COMMAND:-?}"
echo "nodes:        ${nodes} (${SLURM_JOB_NODELIST:-?}), ${ncpus} cores, ${SPEED_NP:-?} MPI processes x ${SPEED_THREADS:-1} threads"
echo "account:      ${SLURM_JOB_ACCOUNT:-?}, partition ${SLURM_JOB_PARTITION:-?}"
echo "submitted:    ${submit:-?}"
echo "started:      $(date -d "@${start}" '+%F %T')$([ -n "${wait_s}" ] && echo ", after $(hm "${wait_s}") in the queue")"
echo "ended:        $(date -d "@${end}" '+%F %T')"
echo "elapsed:      $(hm "${elapsed}")$([ -n "${limit_s}" ] && [ "${limit_s}" -gt 0 ] && awk -v e="${elapsed}" -v l="${limit_s}" -v w="${limit}" 'BEGIN { printf ", %.0f%% of the walltime %s", 100 * e / l, w }')"
echo "core hours:   ${core_h} (${ncpus} cores x elapsed)"
echo "peak memory:  $(gb "${peak_kb}") on the first node ($(hostname -s)), of $(free -g | awk '/Mem/ { print $2 }') GB"
if command -v saldo >/dev/null 2>&1; then
    saldo -b 2>/dev/null | awk -v a="${SLURM_JOB_ACCOUNT:-}" -v j="${core_h}" '$1 == a {
        printf "budget:       %s: %s of %s core hours used (%s%%), %s left before this job, %s after it (saldo is updated daily); this month %s of %s\n",
            $1, $6, $4, $7, $4 - $6, $4 - $6 - j, $9, $8 }'
fi

if [ -n "${run_dir}" ]; then
    case=$(basename "$(dirname "${run_dir}")")
    stop=$(awk '$1 == "STOPTIME" { print $2 }' "${run_dir}/SPEED.input" 2>/dev/null)
    t=$(grep 'TIME =' "${run_dir}/speed.out" 2>/dev/null | tail -1 | awk '{ print $3 }')
    setup=$(grep -m1 'Set-up time' "${run_dir}/speed.out" 2>/dev/null | awk '{ print $4 }')
    echo
    echo "case:         ${case}"
    grep -E '^(speed|vtk|cfl|timestep):' "${run_dir}/run_info.txt" 2>/dev/null
    echo "simulated:    ${t:-none} of ${stop:-?} s"
    if [ -n "${t}" ] && [ -n "${setup}" ] && [ -f "${run_dir}/speed_setup.out" ]; then
        loop=$(( $(stat -c %Y "${run_dir}/speed.out") - $(stat -c %Y "${run_dir}/speed_setup.out") ))
        awk -v t="${t}" -v l="${loop}" -v s="${setup}" -v c="${ncpus}" 'BEGIN {
            m = (l - s) / 60 / t
            printf "setup:        %.0f s\n", s
            printf "rate:         %.1f min per simulated second on %d cores, %.0f core hours per simulated second\n", m, c, m * c / 60
            printf "25 s would:   take about %.1f h and %.0f core hours on these %d cores\n", (s / 60 + 25 * m) / 60, (s / 60 + 25 * m) * c / 60, c }'
    fi
    instab=$(grep -c -i 'instability' "${run_dir}/speed.out" 2>/dev/null)
    [ "${instab:-0}" -gt 0 ] && echo "WARNING:      ${instab} lines about instability in speed.out"
    echo "snapshots:    $(ls "${run_dir}/VTKOUT" 2>/dev/null | grep -c '^Disp_') in VTKOUT"
    echo "results:      ${run_dir} ($(du -sh "${run_dir}" | cut -f1))"
    if [ -f "${run_dir}.tar.zst" ]; then
        echo "archive:      ${run_dir}.tar.zst ($(du -h "${run_dir}.tar.zst" | cut -f1))"
        echo
        echo "to download it, on the laptop:"
        echo "    SSH_AUTH_SOCK=\$XDG_RUNTIME_DIR/cineca-agent.sock scp ${USER}@login.g100.cineca.it:${run_dir}.tar.zst ."
        echo "    tar -I zstd -xf $(basename "${run_dir}").tar.zst"
    else
        echo "archive:      none (run_case.sh did not get to it)"
        echo
        echo "to download the folder, on the laptop:"
        echo "    SSH_AUTH_SOCK=\$XDG_RUNTIME_DIR/cineca-agent.sock rsync -av ${USER}@login.g100.cineca.it:${run_dir} ."
    fi
fi
echo
echo "log:          ${log}"
if (( status != 0 )) || [ -n "${note}" ]; then
    echo
    echo "last lines of the log:"
    tail -n 25 "${log}"
fi
} > "${summary}" 2>&1

subject="[speed-simu] ${name} ${outcome}, $(hm "${elapsed}"), ${core_h} core h"
echo "summary: ${summary}"
if [ -z "${SPEED_MAIL:-}" ]; then
    echo "summary: not mailed, SPEED_MAIL unset"
elif command -v mail >/dev/null 2>&1; then
    mail -s "${subject}" "${SPEED_MAIL}" < "${summary}" && echo "summary: mailed to ${SPEED_MAIL} with mail"
elif [ -x /usr/sbin/sendmail ]; then
    { echo "To: ${SPEED_MAIL}"; echo "Subject: ${subject}"; echo; cat "${summary}"; } \
        | /usr/sbin/sendmail -t && echo "summary: mailed to ${SPEED_MAIL} with sendmail"
else
    echo "summary: NOT MAILED, no mail nor sendmail on $(hostname -s)" >&2
fi
