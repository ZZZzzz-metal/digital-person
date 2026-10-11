#!/usr/bin/env bash
# Run only as root in the newly created, D-backed B2-B6-Ubuntu22 WSL2 distro.
# Installs prerequisites only; never builds/runs the candidate or uploads it.
# Official sources:
# https://docs.docker.com/engine/install/ubuntu/
# https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html
# https://docs.nvidia.com/cuda/wsl-user-guide/index.html
set -Eeuo pipefail
umask 077

fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
readonly EXPECTED_DISTRO='B2-B6-Ubuntu22'
readonly OWNED_MARKER='/etc/b2-b6-owned'
readonly MARKER_TEXT='b2-b6: B2-B6-Ubuntu22 Ubuntu22.04 amd64 setup-v1'
readonly TOOLKIT_VERSION='1.20.1-1'
readonly DRIVER_ENV='/opt/b2-b6/env'

# All ownership/environment checks precede marker creation or installation.
[[ "$(id -u)" == '0' ]] || fail 'Run as root inside the dedicated WSL distro.'
[[ "${WSL_DISTRO_NAME:-}" == "$EXPECTED_DISTRO" ]] || fail 'Unexpected WSL_DISTRO_NAME; no changes made.'
[[ -r /proc/sys/kernel/osrelease ]] || fail 'Linux kernel information unavailable.'
[[ "$(</proc/sys/kernel/osrelease)" == *[Mm]icrosoft* ]] || fail 'A Microsoft WSL kernel is required.'
[[ -f /etc/os-release && -r /etc/os-release ]] || fail 'Ubuntu os-release information is unavailable.'
# shellcheck source=/dev/null
. /etc/os-release
[[ "${ID:-}" == 'ubuntu' && "${VERSION_ID:-}" == '22.04' && "${VERSION_CODENAME:-}" == 'jammy' ]] || fail 'Only Ubuntu 22.04 jammy is supported.'
[[ "$(dpkg --print-architecture)" == 'amd64' ]] || fail 'Only amd64 is supported.'
[[ "$(ps -p 1 -o comm=)" == 'systemd' ]] || fail 'systemd must already be PID 1; restart this distro after enabling it.'
[[ "$(findmnt -n -o FSTYPE /)" == 'ext4' ]] || fail 'The distro root must be its ext4 VHD, not a Windows-mounted data root.'
for path in /etc/apt/keyrings /etc/apt/sources.list.d /etc/docker /var/lib/docker /var/lib/containerd /opt/b2-b6 /root/b2-b6; do
    [[ ! -L "$path" ]] || fail "Refusing symlinked setup/data path: $path"
done

owned=false
if [[ -e "$OWNED_MARKER" || -L "$OWNED_MARKER" ]]; then
    [[ -f "$OWNED_MARKER" && ! -L "$OWNED_MARKER" ]] || fail 'Invalid ownership marker.'
    [[ "$(<"$OWNED_MARKER")" == "$MARKER_TEXT" ]] || fail 'Ownership marker differs; no changes made.'
    owned=true
fi
installed() { [[ "$(dpkg-query -W -f='${Status}' "$1" 2>/dev/null || true)" == 'install ok installed' ]]; }
for package in docker.io docker-compose docker-compose-v2 docker-doc docker-buildx podman-docker containerd runc docker-desktop; do
    installed "$package" && fail "Conflicting installed package: $package; this script never removes it."
done
if [[ "$owned" == false ]]; then
    for package in docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin nvidia-container-toolkit nvidia-container-toolkit-base libnvidia-container-tools libnvidia-container1; do
        installed "$package" && fail 'Existing runtime packages without our marker; refusing to take ownership.'
    done
    for path in /etc/docker/daemon.json /etc/apt/sources.list.d/docker.sources /etc/apt/sources.list.d/docker.list /etc/apt/sources.list.d/nvidia-container-toolkit.list /etc/apt/keyrings/docker.asc /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg /opt/b2-b6/env; do
        [[ ! -e "$path" && ! -L "$path" ]] || fail "Existing setup configuration without our marker: $path"
    done
fi

# This is a dedicated per-distro lock, not a host-wide Linux setup lock.
exec 9>/run/b2-b6-setup.lock
flock -n 9 || fail 'Another setup is already running in this distro.'
if [[ "$owned" == false ]]; then
    (set -o noclobber; printf '%s\n' "$MARKER_TEXT" > "$OWNED_MARKER") || fail 'Could not create ownership marker.'
fi

install -d -m 0700 /root/b2-b6/setup-evidence
evidence=$(mktemp -d /root/b2-b6/setup-evidence/run-XXXXXXXX)
readonly evidence
stage='start'
temporary=''
finish() {
    result=$?
    trap - EXIT
    if [[ -n "$temporary" ]]; then rm -rf -- "$temporary"; fi
    printf 'exit_code=%s\nlast_stage=%s\nfinished_at_utc=%s\nimage_verified=false\nmodel_verified=false\ngpu_container_verified=false\ncontest_submitted=false\n' \
        "$result" "$stage" "$(date -u +%FT%TZ)" > "$evidence/status.txt"
    printf 'Setup exit=%s; evidence=%s. No candidate/container/model acceptance was performed.\n' "$result" "$evidence"
    exit "$result"
}
trap finish EXIT
exec > >(tee "$evidence/setup.log") 2>&1
printf 'distro=%s\nstarted_at_utc=%s\nroot_fstype=ext4\n' "$EXPECTED_DISTRO" "$(date -u +%FT%TZ)" > "$evidence/environment.txt"
printf 'Windows driver must have verified this distro VHD is on D: before calling this script.\n'
temporary=$(mktemp -d /tmp/b2-b6-setup-XXXXXXXX)
export DEBIAN_FRONTEND=noninteractive

stage='ubuntu-prerequisites'
apt-get update
apt-get install -y --no-remove --no-install-recommends ca-certificates curl gnupg python3 python3-venv

stage='official-signed-repositories'
install -d -m 0755 /etc/apt/keyrings
curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' \
    https://download.docker.com/linux/ubuntu/gpg -o "$temporary/docker.asc"
gpg --batch --show-keys --with-fingerprint "$temporary/docker.asc" > "$evidence/docker-key.txt"
install -m 0644 "$temporary/docker.asc" /etc/apt/keyrings/docker.asc
cat > /etc/apt/sources.list.d/docker.sources <<'EOF'
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: jammy
Components: stable
Architectures: amd64
Signed-By: /etc/apt/keyrings/docker.asc
EOF
chmod 0644 /etc/apt/sources.list.d/docker.sources
curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' \
    https://nvidia.github.io/libnvidia-container/gpgkey -o "$temporary/nvidia.asc"
gpg --batch --show-keys --with-fingerprint "$temporary/nvidia.asc" > "$evidence/nvidia-key.txt"
gpg --batch --dearmor --output "$temporary/nvidia.gpg" "$temporary/nvidia.asc"
install -m 0644 "$temporary/nvidia.gpg" /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
printf '%s\n' 'deb [arch=amd64 signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://nvidia.github.io/libnvidia-container/stable/deb/amd64 /' \
    > /etc/apt/sources.list.d/nvidia-container-toolkit.list
chmod 0644 /etc/apt/sources.list.d/nvidia-container-toolkit.list
apt-get update

stage='available-runtime-versions'
toolkit_packages=(nvidia-container-toolkit nvidia-container-toolkit-base libnvidia-container-tools libnvidia-container1)
for package in "${toolkit_packages[@]}"; do
    apt-cache madison "$package" > "$evidence/$package-available.txt"
    awk -F '|' -v required="$TOOLKIT_VERSION" '{gsub(/^[ \t]+|[ \t]+$/, "", $2); if ($2 == required) found=1} END {exit !found}' \
        "$evidence/$package-available.txt" || fail "Required official version is unavailable: $package=$TOOLKIT_VERSION"
done
apt-cache policy docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin > "$evidence/docker-available.txt"

stage='install-engine-toolkit'
apt-get install -y --no-remove --no-install-recommends docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin \
    "nvidia-container-toolkit=$TOOLKIT_VERSION" "nvidia-container-toolkit-base=$TOOLKIT_VERSION" \
    "libnvidia-container-tools=$TOOLKIT_VERSION" "libnvidia-container1=$TOOLKIT_VERSION"

stage='driver-environment'
if [[ -e "$DRIVER_ENV" ]]; then
    [[ -f "$DRIVER_ENV/pyvenv.cfg" && -x "$DRIVER_ENV/bin/python" ]] || fail 'Existing driver env is not a Python venv.'
else
    python3 -m venv "$DRIVER_ENV"
fi
"$DRIVER_ENV/bin/python" -m pip --isolated --disable-pip-version-check install --require-virtualenv --index-url https://pypi.org/simple 'jsonschema==4.26.0'
"$DRIVER_ENV/bin/python" -m pip --isolated --disable-pip-version-check check > "$evidence/pip-check.txt"
"$DRIVER_ENV/bin/python" -m pip --isolated --disable-pip-version-check freeze --all > "$evidence/pip-freeze.txt"

stage='configure-owned-docker'
# Rootful Engine inside our own WSL distro; never apply rootless no-cgroups.
# nvidia-ctk merges its runtime definition; no TCP listener/group/chmod setup.
nvidia-ctk runtime configure --runtime=docker --set-as-default
systemctl enable --now docker
systemctl restart docker
systemctl is-active docker > "$evidence/docker-active.txt"
env -u DOCKER_HOST -u DOCKER_CONTEXT docker --host unix:///var/run/docker.sock info --format '{{json .}}' > "$evidence/docker-info.json"
"$DRIVER_ENV/bin/python" - "$evidence/docker-info.json" <<'PY'
import json
import sys
with open(sys.argv[1], encoding='utf-8') as handle:
    info = json.load(handle)
if info.get('OSType') != 'linux' or info.get('DockerRootDir') != '/var/lib/docker' or info.get('DefaultRuntime') != 'nvidia':
    raise SystemExit('Unexpected daemon OS, data root, or NVIDIA default runtime')
PY

stage='record-installed-state'
dpkg-query -W -f='${binary:Package}\t${Version}\t${Status}\n' \
    docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin \
    "${toolkit_packages[@]}" python3 python3-venv > "$evidence/dpkg-versions.tsv"
[[ -x /usr/lib/wsl/lib/nvidia-smi ]] || fail 'Windows WSL NVIDIA driver bridge is missing; do not install Linux display drivers.'
timeout 30 /usr/lib/wsl/lib/nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader \
    > "$evidence/nvidia-smi.csv"
stage='prerequisites-recorded'
printf '\nPrerequisites installed and recorded. This does not verify a GPU Docker container, candidate image, or model.\n'
printf 'Next, from the copied B repository root in this distro, manually invoke:\n'
printf '%s\n' '/opt/b2-b6/env/bin/python deploy/verify_container.py --bundle /root/b2-b6/candidate-a34f8df --test-file submission/official-reference/test_inference_data.jsonl --work /root/b2-b6/verify-new'
printf 'The bundle/project paths must first be copied and checked by the driver; --work must not exist.\n'
printf 'No Windows reboot, distro boot configuration, display driver, user group, socket permissions, security bypass, or contest upload is requested by this script.\n'
