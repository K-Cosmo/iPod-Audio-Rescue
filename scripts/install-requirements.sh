#!/usr/bin/env bash
# Ubuntu 24.04 WSL2 requirements only. Does not access an iPod.
set -Eeuo pipefail
trap 'echo "ERROR at line $LINENO" >&2' ERR
if [[ $EUID -eq 0 ]]; then
  echo 'Run as your regular Ubuntu user, not root.' >&2
  exit 1
fi
if ! grep -qi microsoft /proc/version && ! grep -qi microsoft /proc/sys/kernel/osrelease; then
  echo 'Expected WSL2; aborting.' >&2
  exit 1
fi
# shellcheck disable=SC1091
source /etc/os-release
if [[ "$ID" != ubuntu || "$VERSION_ID" != 24.04 ]]; then
  echo "Ubuntu 24.04 LTS required; found ${PRETTY_NAME:-unknown}" >&2
  exit 1
fi
sudo apt-get update
sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
  libimobiledevice-utils ifuse usbmuxd usbutils fuse ca-certificates
version="$(dpkg-query -W -f='${Version}' ifuse)"
echo "Installed ifuse: $version"
if dpkg --compare-versions "$version" ge 1.2.0 && dpkg --compare-versions "$version" lt 1.2.1; then
  echo 'STOP: ifuse 1.2.0 has a known data corruption bug. Do NOT mount an iPod.' >&2
  exit 2
fi
for command_name in idevice_id ideviceinfo ifuse fusermount lsusb; do
  command -v "$command_name" >/dev/null || { echo "Missing: $command_name" >&2; exit 3; }
done
mkdir -p "$HOME/ipod-media"
if mountpoint -q "$HOME/ipod-media"; then
  echo 'A mount already exists at ~/ipod-media; aborting.' >&2
  exit 4
fi
echo 'READY: dependencies installed. No iPod communication performed.'
echo 'Next: read docs/WSL-SETUP.md before manually connecting USB.'
