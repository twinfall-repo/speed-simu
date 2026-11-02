# Open a shell inside the speed-simu image, with this repository
# bind-mounted at /workspace, so the cases and run_case.sh come straight from
# the host.
#
#     source apptainer/shell.sh          # the usual way
#     bash apptainer/shell.sh [options] [-- command ...]
#
# Options:
#   -i, --image PATH    image to use (default apptainer/speed.sif)
#   -o, --output PATH   host folder to mount as /workspace/output
#   -d, --data PATH     host folder to mount as /workspace/data
#   -b, --bind SRC:DST  extra bind, repeatable
#   -a, --apptainer BIN apptainer executable
#
# Or set these in the environment before sourcing:
#   APPTAINER_BIN   apptainer executable (default: apptainer on PATH, then
#                   /opt/mox/apptainer/bin/apptainer)
#   SPEED_IMAGE     image to use
#   SPEED_OUTPUT    host folder to expose as /workspace/output
#   SPEED_DATA      host folder to expose as /workspace/data, e.g. the output
#                   folder of dtm_voxelization, to run on the meshes it writes
#   SPEED_NP        MPI processes of run_case.sh, when it is not given -n
#   SPEED_THREADS   OpenMP threads of each MPI process (default 1)
#
# Runs with --containall --no-home --writable-tmpfs: nothing of the host is
# visible except the binds, and writes inside the image itself land in a
# throwaway tmpfs overlay that is both small and discarded on exit. Results
# MUST go to /workspace/output (or another bind) to survive the session.
#
# Written to be safe when sourced: no exec, no exit, no `set -e` leaking into
# your interactive shell.

speed_shell() {
    local here repo image output data apptainer_bin bind
    local -a extra_binds=() binds=() bind_args=() isolation=()

    here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
    repo=$(cd "${here}/.." && pwd)
    apptainer_bin="${APPTAINER_BIN:-}"
    image="${SPEED_IMAGE:-${here}/speed.sif}"
    output="${SPEED_OUTPUT:-${repo}/output}"
    data="${SPEED_DATA:-${repo}/data}"

    while [ $# -gt 0 ]; do
        case "$1" in
            -i|--image)     image=$2;  shift 2 ;;
            -o|--output)    output=$2; shift 2 ;;
            -d|--data)      data=$2;   shift 2 ;;
            -b|--bind)      extra_binds+=("$2"); shift 2 ;;
            -a|--apptainer) apptainer_bin=$2; shift 2 ;;
            -h|--help)      sed -n '2,32p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; return 0 ;;
            --)             shift; break ;;
            *)              echo "unknown option: $1 (use -- before a command)" >&2; return 1 ;;
        esac
    done

    if [ -z "${apptainer_bin}" ]; then
        if command -v apptainer >/dev/null 2>&1; then
            apptainer_bin=apptainer
        elif [ -x /opt/mox/apptainer/bin/apptainer ]; then
            apptainer_bin=/opt/mox/apptainer/bin/apptainer
        else
            echo "apptainer not found: put it on PATH, set APPTAINER_BIN, or pass -a" >&2
            return 1
        fi
    fi
    if [ ! -e "${image}" ]; then
        echo "image not found: ${image}" >&2
        echo "build it first: source apptainer/build.sh" >&2
        return 1
    fi
    if [ ! -d "${data}" ]; then
        echo "data folder not found: ${data}" >&2
        return 1
    fi

    mkdir -p "${output}" || {
        echo "cannot make the output folder ${output} -- is it somewhere you can write?" >&2
        return 1
    }
    output=$(cd "${output}" && pwd)
    data=$(cd "${data}" && pwd)

    binds=("${repo}:/workspace")
    # bind these separately only when they are not already inside the
    # repository bind, otherwise the nested mounts just shadow themselves
    [ "${output}" != "${repo}/output" ] && binds+=("${output}:/workspace/output")
    [ "${data}" != "${repo}/data" ] && binds+=("${data}:/workspace/data")
    for bind in ${extra_binds[@]+"${extra_binds[@]}"}; do
        binds+=("${bind}")
    done
    for bind in "${binds[@]}"; do
        bind_args+=(--bind "${bind}")
    done

    echo "runtime: ${apptainer_bin}"
    echo "image:   ${image}"
    echo "repo:    ${repo} -> /workspace"
    echo "output:  ${output} -> /workspace/output"
    echo "data:    ${data} -> /workspace/data"

    # --containall implies --cleanenv: what the run needs from the host
    # environment is passed back in by hand
    isolation=(--containall --no-home --writable-tmpfs --pwd /workspace)
    # the job's name for itself, which names the run folder of run_case.sh
    [ -n "${PBS_JOBID:-}" ] && isolation+=(--env "PBS_JOBID=${PBS_JOBID}")
    [ -n "${SPEED_NP:-}" ] && isolation+=(--env "SPEED_NP=${SPEED_NP}")
    isolation+=(--env "SPEED_THREADS=${SPEED_THREADS:-1}")
    echo "processes: ${SPEED_NP:-unset}, threads per process: ${SPEED_THREADS:-1}"

    if [ $# -eq 0 ]; then
        "${apptainer_bin}" shell "${isolation[@]}" "${bind_args[@]}" "${image}"
    else
        "${apptainer_bin}" exec "${isolation[@]}" "${bind_args[@]}" "${image}" "$@"
    fi
}

speed_shell "$@"
