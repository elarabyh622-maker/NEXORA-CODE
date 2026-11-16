#!/usr/bin/env bash
# Run inside the dedicated Ubuntu 24.04 runner VM. This configures guest services.
set +x
set -euo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
umask 077

fail() {
    printf 'Runner provisioning stopped. %s\n' "$*" >&2
    exit 1
}

[[ $# == 1 && $1 == --dedicated-nexora-runner ]] || fail 'Pass --dedicated-nexora-runner inside the dedicated Ubuntu VM.'
[[ $(uname -s) == Linux && $EUID == 0 ]] || fail 'Run as root inside the Linux guest.'
[[ -r /etc/os-release ]] || fail 'Missing OS information.'
. /etc/os-release
[[ ${ID:-} == ubuntu && ${VERSION_ID:-} == 24.04 ]] || fail 'This installer requires Ubuntu 24.04 LTS.'
systemd-detect-virt --vm --quiet || fail 'A dedicated virtual machine is required.'
if systemd-detect-virt --container --quiet || grep -Eiq 'microsoft|wsl' /proc/sys/kernel/osrelease; then
    fail 'Run inside the dedicated Linux VM.'
fi
[[ -d /run/systemd/system && -r /sys/fs/cgroup/cgroup.controllers ]] || fail 'The guest requires systemd and cgroup v2.'
arch=$(dpkg --print-architecture)
[[ $arch == amd64 || $arch == arm64 ]] || fail 'The pinned profiles support amd64 and arm64.'

source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../runner" && pwd -P)
for file in broker.py sandbox.py smoke.py nexora-code-runner.service; do
    [[ -r $source_dir/$file ]] || fail "Missing runner source file $file."
done

exec 9>/run/lock/nexora-code-runner-provision.lock
flock -n 9 || fail 'Provisioning is already running in this guest.'
stage=$(mktemp -d /run/nexora-runner-provision.XXXXXXXX)
runner_started=0

cleanup() {
    local status=$?
    if (( status != 0 && runner_started )); then
        systemctl stop nexora-code-runner.service || true
    fi
    rm -f -- "$stage/archive.key" "$stage/archive.gpg" "$stage/gvisor.list" "$stage/trustdb.gpg"
    rmdir -- "$stage/docker-config" "$stage" || true
}
trap cleanup EXIT
mkdir -- "$stage/docker-config"
unset DOCKER_CONTEXT DOCKER_HOST DOCKER_TLS_VERIFY DOCKER_CERT_PATH DOCKER_CONFIG

docker_guest() {
    docker --host=unix:///var/run/docker.sock --config "$stage/docker-config" "$@"
}

check_workloads() {
    local workloads line
    workloads=$(docker_guest container ls --all --format '{{.Names}} {{.Label "org.nexora.code.phase3.runner"}}')
    while IFS= read -r line; do
        [[ -z $line || $line =~ ^nexora-code-[0-9a-f]{32}\ 1$ ]] || fail 'Docker contains a workload outside the runner.'
    done <<< "$workloads"
}

if systemctl is-active --quiet docker.service; then
    check_workloads
fi

printf 'Installing Ubuntu Docker Engine and gVisor in the guest.\n'
export DEBIAN_FRONTEND=noninteractive
apt-get -o DPkg::Lock::Timeout=120 -o Acquire::Retries=3 -o APT::Update::Error-Mode=any update
apt-get -o DPkg::Lock::Timeout=120 install -y --no-install-recommends \
    ca-certificates curl docker.io gpg python3

# gVisor signed repository. https://gvisor.dev/docs/user_guide/install/
curl --disable --proto '=https' --tlsv1.2 --fail --silent --show-error --location \
    --retry 3 --max-time 30 --output "$stage/archive.key" https://gvisor.dev/archive.key
fingerprints=$(gpg --batch --no-options --no-keyring --homedir "$stage" --show-keys --with-colons "$stage/archive.key" \
    | awk -F: '$1 == "pub" { main = 1 } $1 == "fpr" && main { print $10; main = 0 }')
[[ $fingerprints == 6F1DF85E3A71C24918E727D56FC6D554E32BD943 ]] || fail 'The gVisor signing key fingerprint differs from the reviewed key.'
gpg --batch --no-options --no-keyring --homedir "$stage" --dearmor --output "$stage/archive.gpg" "$stage/archive.key"
install -o root -g root -m 0644 "$stage/archive.gpg" /usr/share/keyrings/gvisor-archive-keyring.gpg
printf 'deb [arch=%s signed-by=/usr/share/keyrings/gvisor-archive-keyring.gpg] https://storage.googleapis.com/gvisor/releases release main\n' \
    "$arch" > "$stage/gvisor.list"
install -o root -g root -m 0644 "$stage/gvisor.list" /etc/apt/sources.list.d/gvisor.list
apt-get -o DPkg::Lock::Timeout=120 -o Acquire::Retries=3 -o APT::Update::Error-Mode=any update
apt-get -o DPkg::Lock::Timeout=120 install -y --no-install-recommends runsc
runsc_path=$(command -v runsc)
[[ $runsc_path == /* && -x $runsc_path ]] || fail 'The signed package did not install an executable runsc.'

systemctl enable --now docker.service
check_workloads
# The package may already have registered runsc. Preserve unrelated daemon settings.
docker_changed=$(/usr/bin/python3 -I -B - "$runsc_path" <<'PY'
import json
import os
import sys
import tempfile
from pathlib import Path

path = Path("/etc/docker/daemon.json")
config = json.loads(path.read_text()) if path.exists() else {}
runtimes = config.setdefault("runtimes", {})
if "runsc" in runtimes:
    entry = runtimes["runsc"]
    if entry.get("path") not in ("runsc", sys.argv[1]) or entry.get("runtimeArgs") or entry.get("runtimeType"):
        raise SystemExit("The existing runsc entry has custom settings")
    print("unchanged")
else:
    runtimes["runsc"] = {"path": sys.argv[1]}
    path.parent.mkdir(mode=0o755, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False) as temporary:
        json.dump(config, temporary, indent=2)
        temporary.write("\n")
    os.replace(temporary.name, path)
    print("changed")
PY
)
if [[ $docker_changed == changed ]] || ! docker_guest info --format '{{json .Runtimes}}' | grep -Fq '"runsc"'; then
    systemctl reload docker.service
fi

# Review references in the Docker Official Images publication metadata.
# https://github.com/docker-library/repo-info/blob/master/repos/python/remote/3.13.18-slim-bookworm.md
# https://github.com/docker-library/repo-info/blob/master/repos/node/remote/24.22.2-bookworm-slim.md
python_image=docker.io/library/python@sha256:a5a7017efc5969e00ae2b91c8eb0631049a569652aa4ffc4501769049ae45c72
node_image=docker.io/library/node@sha256:01d566e8d94d8c619591d78652babfccd3c6992a3dffa9ed5ab39e11cf6c70e9
for image in "$python_image" "$node_image"; do
    if ! docker_guest image inspect "$image" >/dev/null 2>&1; then
        docker_guest image pull "$image"
    fi
    [[ $(docker_guest image inspect --format '{{.Os}}/{{.Architecture}}' "$image") == "linux/$arch" ]] \
        || fail "Image architecture mismatch for $image."
done

if ! getent passwd nexora-runner >/dev/null; then
    useradd --system --user-group --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin nexora-runner
fi
[[ $(id -gn nexora-runner) == nexora-runner && $(getent passwd nexora-runner | cut -d: -f7) == /usr/sbin/nologin ]] \
    || fail 'The service account has unexpected settings.'
install -d -o root -g root -m 0755 /opt/nexora-code-runner
install -d -o root -g root -m 0700 /etc/nexora-code-runner
install -o root -g root -m 0644 "$source_dir/broker.py" "$source_dir/sandbox.py" "$source_dir/smoke.py" /opt/nexora-code-runner/
install -o root -g root -m 0644 "$source_dir/nexora-code-runner.service" /etc/systemd/system/nexora-code-runner.service

# Keep the existing valid credential on repeat installations. The file is never sourced.
/usr/bin/python3 -I -B - "$python_image" "$node_image" <<'PY'
import os
import re
import secrets
import stat
import sys
import tempfile
from pathlib import Path

path = Path("/etc/nexora-code-runner/runner.env")
name = "NEXORA_RUNNER_BEARER_TOKEN"
if path.exists() or path.is_symlink():
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != 0 or stat.S_IMODE(metadata.st_mode) != 0o600:
        raise SystemExit("The existing runner.env requires a root-owned 0600 regular file")
    matches = [line.partition("=")[2] for line in path.read_text().splitlines() if line.startswith(f"{name}=")]
    if len(matches) != 1 or not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", matches[0]):
        raise SystemExit("The existing runner.env has no unique valid token")
    token = matches[0]
else:
    token = secrets.token_urlsafe(32)

with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False) as temporary:
    temporary.write(f"NEXORA_RUNNER_PYTHON_IMAGE={sys.argv[1]}\n")
    temporary.write(f"NEXORA_RUNNER_JAVASCRIPT_IMAGE={sys.argv[2]}\n")
    temporary.write(f"{name}={token}\n")
os.replace(temporary.name, path)
PY

printf 'Starting the broker and waiting for the gVisor preflight.\n'
systemctl daemon-reload
runner_started=1
systemctl restart nexora-code-runner.service
ready=0
for attempt in {1..30}; do
    response=$(curl --disable --noproxy '*' --max-time 1 --silent --output /dev/null --write-out '%{http_code}' \
        --request POST http://127.0.0.1:8787/v1/execute || true)
    if [[ $response == 401 ]] && systemctl is-active --quiet nexora-code-runner.service; then
        ready=1
        break
    fi
    sleep 1
done
(( ready )) || fail 'The broker did not complete preflight. Inspect the runner unit journal in the guest.'

/usr/bin/python3 -I -B - <<'PY'
import os
import runpy
from pathlib import Path

name = "NEXORA_RUNNER_BEARER_TOKEN"
path = Path("/etc/nexora-code-runner/runner.env")
os.environ[name] = next(line.partition("=")[2] for line in path.read_text().splitlines() if line.startswith(f"{name}="))
runpy.run_path("/opt/nexora-code-runner/smoke.py", run_name="__main__")
PY

[[ -z $(docker_guest container ls -aq --filter 'label=org.nexora.code.phase3.runner=1') ]] \
    || fail 'Runner-owned containers remain after the smoke suite.'
systemctl enable nexora-code-runner.service
printf 'PASS. Both pinned runsc profiles and the loopback HTTP smoke suite are ready.\n'
