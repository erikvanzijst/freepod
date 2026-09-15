#!/bin/bash
# Validate the runtime configuration, render the server configuration from it,
# and only then start sshd. A misconfiguration must be a container that exits
# with an explanation, not one that runs and refuses every connection: the
# second is indistinguishable from a network fault and gets diagnosed as one.
set -euo pipefail

readonly PORT=2222
readonly AUTHORIZED_KEYS=/etc/ssh/authorized_keys
readonly SSHD_CONFIG=/etc/ssh/sshd_config
readonly SESSION_ENV=/etc/freepod/session-env
readonly HOST_KEY=/etc/ssh/ssh_host_ed25519_key

die() {
    echo "ssh-sidecar: $*" >&2
    exit 1
}

require() {
    local name=$1
    [[ -n ${!name:-} ]] || die "$name is not set. It is required; see the image README."
}

# --- trusted keys ----------------------------------------------------------
require FREEPOD_AUTHORIZED_KEYS

install -m 0600 /dev/null "$AUTHORIZED_KEYS"
keys=0
while IFS= read -r line; do
    [[ -n ${line//[[:space:]]/} ]] || continue
    [[ ${line#"${line%%[![:space:]]*}"} != \#* ]] || continue
    # ssh-keygen is the only authority on what sshd will accept. Parsing the
    # line ourselves would accept things sshd then silently ignores, leaving a
    # container that starts with a trust set nobody can use.
    if ! printf '%s\n' "$line" | ssh-keygen -l -f /dev/stdin >/dev/null 2>&1; then
        die "FREEPOD_AUTHORIZED_KEYS contains a line that is not a valid SSH public key."
    fi
    printf '%s\n' "$line" >> "$AUTHORIZED_KEYS"
    keys=$((keys + 1))
done <<< "$FREEPOD_AUTHORIZED_KEYS"

(( keys > 0 )) || die "FREEPOD_AUTHORIZED_KEYS contains no public key. Refusing to start a server nobody can authenticate to."

require FREEPOD_SESSION_ROOT

# The jail and the paths of the file-transfer program inside it, resolved from
# `ldd` when the image was built (D3).
# shellcheck source=/dev/null
. /etc/freepod/sftp-server.env

case $FREEPOD_SESSION_ROOT in
    app-container)
        session_root_note="the application container"
        ;;
    volume:/*)
        session_path=${FREEPOD_SESSION_ROOT#volume:}
        session_path=${session_path%/}
        if [[ $session_path == *//* || $session_path == */../* || $session_path == */.. ]]; then
            die "FREEPOD_SESSION_ROOT path '${session_path}' is not a plain absolute path."
        fi
        # The chart mounts the product's volume inside the jail, so the session
        # is chrooted into the jail and started here. A missing directory means
        # the chart declared one path and mounted another, which would otherwise
        # surface as an empty session that looks like missing data.
        mount_point=${FREEPOD_SESSION_JAIL}${session_path}
        [[ -d $mount_point ]] \
            || die "FREEPOD_SESSION_ROOT is '${FREEPOD_SESSION_ROOT}', but ${mount_point} is not a directory. The chart must mount the product's volume there."
        session_root_note="${session_path} (mounted)"
        ;;
    volume:*)
        die "FREEPOD_SESSION_ROOT '${FREEPOD_SESSION_ROOT}' names a relative path. A volume session root is absolute, as in 'volume:/data'."
        ;;
    *)
        die "FREEPOD_SESSION_ROOT '${FREEPOD_SESSION_ROOT}' is not a session root. It is 'app-container' or 'volume:/<path>'; there is no default."
        ;;
esac

# --- forward allowlist -----------------------------------------------------
# Optional. A deployment with no forwardable endpoint gets a server that refuses
# every forward -- which is `PermitOpen none`, written explicitly below. What it
# must never get is the directive omitted: sshd's default is to permit
# forwarding to anywhere, so silence would turn "nothing to allow" into "allow
# everything", from a host with tenant egress to the public internet.
permit_open=()
while read -r dest; do
    [[ -n $dest ]] || continue
    # host:port, or [v6addr]:port. No wildcard port: an allowlist entry that
    # opens every port on a host is not an allowlist (D6).
    if [[ ! $dest =~ ^(\[[0-9A-Fa-f:]+\]|[A-Za-z0-9._-]+):([0-9]{1,5})$ ]]; then
        die "FREEPOD_PERMIT_OPEN entry '$dest' is not host:port. Ports must be numeric; wildcards are not accepted."
    fi
    port=${BASH_REMATCH[2]}
    if (( port < 1 || port > 65535 )); then
        die "FREEPOD_PERMIT_OPEN entry '$dest' has a port outside 1-65535."
    fi
    permit_open+=("$dest")
done < <(tr ',[:space:]' '\n\n' <<< "${FREEPOD_PERMIT_OPEN:-}")

# --- login account ---------------------------------------------------------
# The SSH edge authenticates the upstream leg as the *deployment name*, because
# that is the one username convention it has: on the `sftp` profile the account
# atmoz creates IS the release name, and the edge is deliberately ignorant of
# which profile it is talking to (see ssh-auth/README.md).
#
# This server needs uid 0 -- the dispatcher reads another container's process
# filesystem and enters it -- so the deployment name is added as a second uid-0
# account rather than the edge being taught a second convention. `root` stays
# first in /etc/passwd, so getpwuid(0) still resolves to "root" and `whoami`,
# `ls -l` and friends are unchanged; this name only exists to be logged in as.
require FREEPOD_LOGIN_USER

[[ $FREEPOD_LOGIN_USER =~ ^[a-z_][a-z0-9_-]{0,31}$ ]] \
    || die "FREEPOD_LOGIN_USER '${FREEPOD_LOGIN_USER}' is not a valid POSIX user name."

if [[ $FREEPOD_LOGIN_USER != root ]]; then
    # -o permits the duplicate uid; -M because /root already exists and is the
    # home both accounts share.
    #
    # `-p '*'` is load-bearing. It means "no password will ever match", which is
    # what root's own entry carries. What it must NOT be is `!`, the LOCKED
    # marker `useradd` writes by default: with `UsePAM no`, sshd's allowed_user()
    # refuses a locked account before it ever looks at a key, so the account
    # would exist and every publickey attempt would still be denied. `*` and `!`
    # both mean "no password login" and only one of them permits keys.
    useradd -o -u 0 -g 0 -M -d /root -s /bin/bash -p '*' "$FREEPOD_LOGIN_USER" \
        || die "could not create the login account '${FREEPOD_LOGIN_USER}'."
fi

# --- release identity ------------------------------------------------------
# Both required rather than optional: the banner exists so a developer
# investigating a broken release is not shown a working one during a rollout
# (D17), and a banner that cannot name its release is the failure it was added
# to prevent.
#
# Two spellings because they answer to different readers. The number is what
# `freepod releases` shows and the only one a user can act on, so it is what the
# session banner reports; the id is globally unique and is what the log pipeline
# keys a stream on, so it is what the startup line below records. Neither
# substitutes for the other, and a pod that had only one would leave either a
# banner naming a release the user cannot find or a log stream nothing can be
# correlated against.
require FREEPOD_RELEASE_ID
require FREEPOD_RELEASE_NUMBER

# --- database connection details -------------------------------------------
# These reach the toolbox from the sidecar's own environment, never from the
# application process: a developer connects precisely when the application is
# broken, and details read from a crash-looping process are unavailable then.
#
# Optional as a set. The toolbox is a facility this server offers, not a reason
# it exists: a deployment with no database still wants a shell in its
# application container, and refusing to start over a missing extra would deny
# the whole session to get it. Products without relational storage run this
# image unchanged; the dispatcher declines the database tools by name.
#
# A partial set is not an absent one. It means the projection that should have
# supplied them is broken, and a container that started anyway would surface
# that as a connection error inside psql, at the moment someone needed the
# database and furthest from the cause.
pg_present=()
pg_absent=()
for var in PGHOST PGPORT PGUSER PGPASSWORD PGDATABASE; do
    if [[ -n ${!var:-} ]]; then pg_present+=("$var"); else pg_absent+=("$var"); fi
done

if (( ${#pg_present[@]} == 0 )); then
    database="none"
elif (( ${#pg_absent[@]} > 0 )); then
    die "the database configuration is incomplete: ${pg_present[*]} set, ${pg_absent[*]} missing. Supply all five or none."
else
    [[ $PGPORT =~ ^[0-9]{1,5}$ ]] || die "PGPORT is not a port number."
    database="${PGUSER}@${PGHOST}:${PGPORT}/${PGDATABASE}"
fi

# sshd hands a session a sanitized environment, so the container's own
# variables do not reach the dispatcher on their own. They are staged here in
# the same NUL-delimited form as /proc/<pid>/environ, which the dispatcher can
# read back without quoting or re-evaluating anything.
#
# The transfer program's paths travel the same way. A session in an application
# that runs as another user continues under that user's credentials, which read
# nothing under /etc/freepod, so the dispatcher exports all of it before then.
install -m 0600 /dev/null "$SESSION_ENV"
for var in PGHOST PGPORT PGUSER PGPASSWORD PGDATABASE PGSSLMODE PGAPPNAME \
    FREEPOD_RELEASE_ID FREEPOD_RELEASE_NUMBER FREEPOD_SESSION_ROOT \
    FREEPOD_SFTP_LOADER FREEPOD_SFTP_LIBPATH FREEPOD_SFTP_SERVER \
    FREEPOD_SESSION_JAIL FREEPOD_SESSION_JAIL_PREFIX; do
    [[ -n ${!var:-} ]] && printf '%s=%s\0' "$var" "${!var}" >> "$SESSION_ENV"
done

# --- host key --------------------------------------------------------------
# Per container, never persisted, Ed25519 only. An RSA 4096 key costs seconds
# on every start before anything listens, and buys nothing: the identity a
# developer verifies is the platform edge's, and the hop from the edge to here
# does not pin this key.
rm -f /etc/ssh/ssh_host_*
ssh-keygen -q -t ed25519 -N '' -C '' -f "$HOST_KEY"

# --- server configuration --------------------------------------------------
# Note what is absent: there is no ChrootDirectory. Chroot is incompatible with
# the forwarding this profile exists to provide -- the process that opens a
# forwarded connection inherits it and has no resolver configuration there, so
# the forward's target fails to resolve (D3).
{
    cat <<-CONFIG
	Port ${PORT}
	ListenAddress 0.0.0.0
	ListenAddress ::

	HostKey ${HOST_KEY}

	PubkeyAuthentication yes
	AuthenticationMethods publickey
	AuthorizedKeysFile ${AUTHORIZED_KEYS}
	PermitRootLogin prohibit-password
	PasswordAuthentication no
	KbdInteractiveAuthentication no
	PermitEmptyPasswords no
	UsePAM no
	PermitUserEnvironment no

	AllowTcpForwarding local
	AllowAgentForwarding no
	AllowStreamLocalForwarding no
	GatewayPorts no
	X11Forwarding no
	PermitTunnel no

	PermitUserRC no
	PrintMotd no
	PrintLastLog no
	ForceCommand /usr/local/bin/freepod-dispatch
	Subsystem sftp internal-sftp
	CONFIG
    printf 'PermitOpen %s\n' "${permit_open[*]:-none}"
} > "$SSHD_CONFIG"
chmod 0600 "$SSHD_CONFIG"

/usr/sbin/sshd -t -f "$SSHD_CONFIG" || die "rendered sshd configuration was rejected by sshd -t."

echo "ssh-sidecar: release ${FREEPOD_RELEASE_NUMBER} (${FREEPOD_RELEASE_ID}), login user ${FREEPOD_LOGIN_USER} (uid 0), ${keys} trusted key(s), session rooted at ${session_root_note}, forwarding to ${permit_open[*]:-nothing}, database ${database}, listening on ${PORT}." >&2
exec /usr/sbin/sshd -D -e -f "$SSHD_CONFIG"
