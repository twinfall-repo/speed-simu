# Build the speed-simu image: the toolchain plus SPEED, cloned and compiled
# inside.
#
#     source apptainer/build.sh          # the usual way
#     bash apptainer/build.sh [options] [image]
#
# Options:
#   -f, --force         overwrite an existing image without asking
#   -s, --sandbox       build a writable sandbox DIRECTORY instead of a .sif
#   -a, --apptainer BIN apptainer executable
#
# Or set these in the environment before sourcing:
#   APPTAINER_BIN   apptainer executable (default: apptainer on PATH, then
#                   /opt/mox/apptainer/bin/apptainer)
#   SPEED_IMAGE     image to write (default apptainer/speed.sif)
#   APPTAINER_ARGS  extra flags passed straight to `apptainer build`
#
# SPEED is cloned from the default branch at build time: rebuild (-f) to pick
# up its latest commit. The compiled commit is printed during the build and is
# in /opt/speed-commit.txt inside the image.
#
# Prefer the default .sif on a cluster: it is a single file, while a sandbox
# is a directory of ~100k small files, which parallel filesystems handle
# badly and some sites forbid. Build a sandbox only to modify it in place.
#
# On a cluster the build unpacks layers into TMPDIR, often a small tmpfs on
# the login node. If it dies with "no space left on device":
#     export APPTAINER_TMPDIR=/scratch/$USER/apptainer_tmp
#     export APPTAINER_CACHEDIR=/scratch/$USER/apptainer_cache
#
# Written to be safe when sourced: no exec, no exit, no `set -e` leaking into
# your interactive shell.

speed_build() {
    local here definition image apptainer_bin privilege scratch value
    local -a build_flags=()

    here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
    definition="${here}/speed.def"
    apptainer_bin="${APPTAINER_BIN:-}"

    while [ $# -gt 0 ]; do
        case "$1" in
            -f|--force)     build_flags+=(--force); shift ;;
            -s|--sandbox)   build_flags+=(--sandbox); shift ;;
            -a|--apptainer) apptainer_bin=$2; shift 2 ;;
            -h|--help)      sed -n '2,32p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; return 0 ;;
            *)              break ;;
        esac
    done
    image="${1:-${SPEED_IMAGE:-${here}/speed.sif}}"

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
    if [ ! -f "${definition}" ]; then
        echo "definition not found: ${definition}" >&2
        return 1
    fi

    privilege=--fakeroot
    [ "$(id -u)" -eq 0 ] && privilege=

    for scratch in APPTAINER_TMPDIR APPTAINER_CACHEDIR; do
        eval "value=\${${scratch}:-}"
        [ -n "${value}" ] && mkdir -p "${value}" && echo "${scratch}=${value}"
    done

    echo "building ${image}"
    echo "  from    ${definition}"
    echo "  with    ${apptainer_bin}"
    # shellcheck disable=SC2086
    "${apptainer_bin}" build ${privilege} ${build_flags[@]+"${build_flags[@]}"} \
        ${APPTAINER_ARGS:-} "${image}" "${definition}" || return $?
    echo "done: ${image}"
}

speed_build "$@"
