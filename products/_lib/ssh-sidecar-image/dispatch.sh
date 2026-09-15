#!/bin/bash
# The session dispatcher. sshd runs this as ForceCommand, so it sees the
# requested command in SSH_ORIGINAL_COMMAND and decides where the session
# lands: file transfer served from this image, a shell in the application
# container, a platform tool in the sidecar, or nothing at all. What is on
# offer follows from the declared session root and from nothing else (D1, D2).
# Port forwarding is a `direct-tcpip` channel and opens no session, so it never
# reaches this program (D3).
#
# The requested command is attacker-influenced input arriving at an
# authenticated boundary. This program never evaluates it. Where a command has
# to be interpreted, it is handed to a shell *in the target* as one quoted
# argument -- which is what sshd itself would do, so `ssh host 'ls | wc -l'`
# still behaves as expected, with the application container's shell doing the
# interpreting rather than anything here.
set -uo pipefail

# Set only when this program re-enters itself under the application's
# credentials (see below), to the process it identified. sshd passes nothing.
readonly entered_pid=${1:-}

readonly SESSION_ENV=/etc/freepod/session-env
readonly SHELLS=(/bin/bash /bin/sh /bin/ash /busybox/sh)

# Tools that live here and nowhere else. Membership is decided on the command
# itself, never on arguments a client controls.
readonly PLATFORM_COMMANDS=(psql pg_dump pg_dumpall pg_restore pg_isready)

say() { echo "freepod: $*" >&2; }
die() { say "$*"; exit 1; }

# --- configuration ---------------------------------------------------------
# sshd hands a session a sanitized environment, so the container's own
# variables are staged by the entrypoint in /proc/<pid>/environ's NUL-delimited
# form and read back here. NUL delimiting is what makes this safe for values
# holding newlines, quotes or spaces -- nothing is parsed or re-evaluated.
#
# Re-entered under an application's credentials, the file is unreadable, and
# nothing in it is needed again: it was exported before the switch.
if [[ -r $SESSION_ENV ]]; then
    while IFS= read -r -d '' entry; do
        [[ $entry =~ ^[A-Za-z_][A-Za-z0-9_]*= ]] && export "${entry?}"
    done < "$SESSION_ENV"
fi

case ${FREEPOD_SESSION_ROOT:-} in
    app-container) session_kind=app ;;
    volume:/*)     session_kind=volume; session_path=${FREEPOD_SESSION_ROOT#volume:} ;;
    *)             die "this deployment declares no session root, so there is nothing to serve. The sidecar was started without one; see the image README." ;;
esac
readonly session_kind

serve_transfer() {
    local root=$1 prefix=$2 start=$3
    local args=()

    # Every path below is spelled as the chrooted process will resolve it, so
    # what is checked here is what it will run.
    [[ -x ${root}${prefix}${FREEPOD_SFTP_LOADER} ]] \
        || die "file transfer cannot be served into this session root: ${prefix} is not reachable from inside it. The application container has no /proc mounted, which the platform's own images always do."
    [[ -c ${root}/dev/null ]] \
        || die "file transfer cannot be served into this session root: it has no /dev/null, which the transfer program opens before it does anything else."
    [[ -r ${root}/etc/passwd ]] \
        || die "file transfer cannot be served into this session root: it has no /etc/passwd, so the transfer program cannot resolve the user it runs as. Add one to the image to copy files into it."
    grep -q "^[^:]*:[^:]*:${EUID}:" "${root}/etc/passwd" \
        || die "file transfer cannot be served into this session root: its /etc/passwd has no entry for uid ${EUID}, the user the application runs as, so the transfer program cannot resolve the user it runs as. Add one to the image to copy files into it."

    is_readonly "$start" && args+=(-R)
    [[ -n $start ]] && args+=(-d "$start")

    exec chroot "$root" \
        "${prefix}${FREEPOD_SFTP_LOADER}" \
        --library-path "${prefix}${FREEPOD_SFTP_LIBPATH//:/:${prefix}}" \
        "${prefix}${FREEPOD_SFTP_SERVER}" "${args[@]}"
}

is_readonly() {
    local opts
    [[ -n $1 ]] || return 1
    opts=$(findmnt -n -o OPTIONS --target "$1" 2>/dev/null) || return 1
    [[ ,${opts}, == *,ro,* ]]
}

# --- banner ----------------------------------------------------------------
# Standard output is a protocol channel for file transfer and dump streams, so
# a banner written there corrupts the transfer and produces a data error far
# from its cause. It goes to standard error, and only when a terminal was
# allocated. The release identity comes from configuration: during a rollout
# two releases' pods both serve and the connection lands on one at random, so a
# developer must be told which one answered (D17).
#
# The number rather than the id, because it is the one the client shows: a
# banner naming a uuid tells a user which release answered in a spelling they
# cannot find in `freepod releases`. The id stays on the sidecar's startup line,
# where it is read alongside the log stream it keys.
[[ -t 2 && -z $entered_pid ]] && say "release ${FREEPOD_RELEASE_NUMBER:-unknown}"

# --- routing ---------------------------------------------------------------
command=${SSH_ORIGINAL_COMMAND:-}

# Word splitting on the requested command, with globbing off. This expansion
# yields words and nothing else -- no command substitution, no evaluation --
# which is what makes reading the first token safe.
set -f
# shellcheck disable=SC2086
set -- $command
set +f
verb=${1:-}

# A subsystem request arrives as its configured command name; modern scp and
# sftp both use it.
is_transfer=false
if [[ $verb == internal-sftp || $verb == sftp-server ]] && (( $# == 1 )); then
    is_transfer=true
fi
readonly is_transfer

is_platform_command=false
for platform_command in "${PLATFORM_COMMANDS[@]}"; do
    [[ $verb == "$platform_command" ]] && { is_platform_command=true; break; }
done
readonly is_platform_command

# --- a session rooted at a mounted path ------------------------------------
# File transfer within the session root, and nothing else. There is no code of
# the user's to run here and the mount is not theirs to execute in, so a shell,
# a remote command and the database tooling are each refused by name rather
# than left to surface as an execution failure.
if [[ $session_kind == volume ]]; then
    if $is_transfer; then
        serve_transfer "$FREEPOD_SESSION_JAIL" "$FREEPOD_SESSION_JAIL_PREFIX" "$session_path"
    fi
    if $is_platform_command; then
        die "this deployment's session is rooted at ${session_path}, a read-only view of its data, so '${verb}' is not served here. It offers file transfer and nothing else."
    fi
    [[ -z $command ]] \
        && die "this deployment's session is rooted at ${session_path}, a read-only view of its data. There is no shell to open in it; copy files with scp, sftp or 'freepod cp'."
    die "this deployment's session offers file transfer and nothing else."
fi

# --- the platform's database tooling ---------------------------------------
if $is_platform_command; then
    [[ -n ${PGHOST:-} ]] || die "this deployment has no database."
    exec /bin/sh -c "$command"
fi

# --- identify the application container ------------------------------------
# Candidates are grouped by cgroup. The dispatcher's own cgroup is excluded,
# and so is the pod's infrastructure process, which is the `pause` binary under
# every CRI. Exactly one cgroup must remain.
#
# Simpler rules are wrong in ways that matter: under Kubernetes with a shared
# process namespace PID 1 is the infrastructure container, while under the
# docker test harness there is no such process and the application *is* PID 1.
# Grouping by cgroup is correct in both, which is what lets the harness prove
# the production behavior rather than an approximation of it.
find_app_pid() {
    local self_cgroup pid cgroup status comm
    self_cgroup=$(< /proc/self/cgroup) || return 1

    local -A lowest=()
    for pid in /proc/[0-9]*; do
        pid=${pid#/proc/}
        [[ -r /proc/$pid/cgroup ]] || continue
        cgroup=$(< "/proc/$pid/cgroup") || continue
        [[ $cgroup == "$self_cgroup" ]] && continue
        # An address space is the honest check: kernel threads and reaped
        # zombies have none. The exe link would say the same, but reading it
        # is refused for a process of another user (see below), and every file
        # under /proc reports a size of zero, so a test for a non-empty cmdline
        # silently excludes everything.
        status=$(< "/proc/$pid/status") || continue
        [[ $status == *$'\nVmSize:'* ]] || continue
        comm=$(< "/proc/$pid/comm") || continue
        [[ $comm == pause ]] && continue                  # pod infrastructure
        [[ -z ${lowest[$cgroup]:-} || pid -lt ${lowest[$cgroup]} ]] && lowest[$cgroup]=$pid
    done

    case ${#lowest[@]} in
        0) return 1 ;;
        1) printf '%s\n' "${lowest[@]}" ;;
        *) return 2 ;;
    esac
}

# Only now, once the request is known not to be a platform tool: a developer
# reaches for psql precisely when the application is broken, so the toolbox
# must not depend on an application container being identifiable at all.
if [[ -z $entered_pid ]]; then
    app_pid=$(find_app_pid)
    case $? in
        1)  die "no application process is visible from the sidecar. The application container is not running, or the pod does not share a process namespace." ;;
        2)  die "more than one candidate application container is visible; refusing to guess which one to enter." ;;
    esac

    # --- take the application's credentials --------------------------------
    # Everything below reads the application container through /proc/<pid>,
    # which the kernel guards with a ptrace access check: root passes it for a
    # process of another uid or gid only by holding CAP_SYS_PTRACE, which Pod
    # Security `baseline` refuses. So the session takes the credentials of the
    # process it enters, and this program starts over under them, keeping
    # CAP_SYS_CHROOT -- the one capability entering needs -- as an ambient one.
    app_uid="" app_gid="" app_groups=""
    while read -r key fields; do
        case $key in
            Uid:)    read -r _ app_uid _ <<< "$fields" ;;
            Gid:)    read -r _ app_gid _ <<< "$fields" ;;
            Groups:) app_groups=${fields// /,} ;;
        esac
    done < "/proc/$app_pid/status"
    [[ -n $app_uid && -n $app_gid ]] \
        || die "the application process exited while the session was opening."
    groups_arg=--clear-groups
    [[ -n $app_groups ]] && groups_arg=--groups=$app_groups

    # The transfer program's paths are the sidecar's, which the application's
    # credentials cannot reach, so it is held open from here. The jail rather
    # than the sidecar's root, because the transfer keeps it open: the jail
    # holds the program and nothing else.
    if $is_transfer; then
        exec 3< "${FREEPOD_SESSION_JAIL}${FREEPOD_SESSION_JAIL_PREFIX}"
    fi

    exec setpriv --reuid="$app_uid" --regid="$app_gid" "$groups_arg" \
        --inh-caps=-all,+sys_chroot --ambient-caps=-all,+sys_chroot \
        -- "$0" "$app_pid"
fi
readonly app_pid=$entered_pid
readonly app_root=/proc/$app_pid/root

[[ -d $app_root/ ]] \
    || die "the application process (pid ${app_pid}, uid ${EUID}) cannot be entered: it changed its user without then starting a new program, which closes it to every other process. Start it as its final user, or exec after switching."

app_cwd=$(readlink "/proc/$app_pid/cwd" 2>/dev/null) || app_cwd=/

if $is_transfer; then
    serve_transfer "$app_root" /proc/self/fd/3 "$app_cwd"
fi

# --- enter the application container ---------------------------------------
# A symlink has to be resolved by hand, because an absolute target under
# /proc/<pid>/root resolves against the SIDECAR's root rather than the app's:
# `-x /proc/1/root/bin/sh` is false for Alpine's `/bin/sh -> /bin/busybox`,
# which chroot then runs perfectly well. Debian's relative `sh -> dash` never
# showed it.
app_executable() {
    local path=$1 target
    for _ in 1 2 3 4 5 6 7 8; do
        [[ -L $app_root$path ]] || { [[ -x $app_root$path ]]; return; }
        target=$(readlink "$app_root$path") || return 1
        [[ $target == /* ]] || target=${path%/*}/$target
        path=$target
    done
    return 1
}

app_shell=""
for candidate in "${SHELLS[@]}"; do
    app_executable "$candidate" && { app_shell=$candidate; break; }
done

if [[ -z $app_shell ]]; then
    # Reported, not crashed, and not redirected somewhere else. `docker exec`
    # and `kubectl exec` fail here too, the image is the user's own, and adding
    # a shell to it is a change they can make. Landing them in the sidecar
    # instead would have them debug a container that is not theirs.
    die "the application image provides no shell (looked for ${SHELLS[*]}), so no session can be opened in it. Add one to the image to use 'freepod shell'."
fi

# The application process's own environment, read from the sidecar rather than
# reconstructed. Read NUL-delimited so a value holding a newline -- a private
# key in a deployment var, say -- survives intact.
env_args=()
while IFS= read -r -d '' entry; do
    [[ $entry =~ ^[A-Za-z_][A-Za-z0-9_]*= ]] && env_args+=("$entry")
done < "/proc/$app_pid/environ"
[[ -n ${TERM:-} ]] && env_args+=("TERM=$TERM")

# Fixed script text with everything variable passed as a positional argument,
# so no part of the request is ever interpolated into the program being run.
readonly ENTER='cd "$1" 2>/dev/null || cd /; shift; if [ "$#" -eq 0 ]; then exec "$0" -l; else exec "$0" -c "$1"; fi'

if [[ -z $command ]]; then
    exec env -i "${env_args[@]}" chroot "$app_root" "$app_shell" -c "$ENTER" "$app_shell" "$app_cwd"
else
    exec env -i "${env_args[@]}" chroot "$app_root" "$app_shell" -c "$ENTER" "$app_shell" "$app_cwd" "$command"
fi
