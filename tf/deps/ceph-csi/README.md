# ceph-csi

The ceph-csi RBD driver, against a Ceph cluster that runs outside Kubernetes:
one StorageClass, Secret and cephx client per pool (`main.tf` in `tf/deps`),
plus one VolumeSnapshotClass whose client, `freepod-snapshots`, reaches every pool.
Which class a deployment's volumes use is the platform's decision, per
deployment: [deployment-storage-class](../../../openspec/specs/deployment-storage-class/spec.md).

The driver needs two things from every node's OS, which Terraform does not
manage.

## Kernel 7.0 or newer

Nodes map images with the kernel RBD client. Ceph 20 issues `aes256k` cephx
keys, which older kernels cannot load: mapping fails with `failed to add
secret ... (22) Invalid argument`. On Ubuntu 24.04, install the HWE kernel
(`linux-generic-hwe-24.04`, or `linux-virtual-hwe-24.04` on a VM) and reboot.

## A shutdown unit that releases RBD volumes while the network is up

kubelet mounts RBD filesystems without `_netdev`, so systemd unmounts them
last, after the network is gone, and the unmount waits on unreachable OSDs
forever. k3s's own units stop with `KillMode=process`, which leaves the
containers and their mounts in place. Rationale:
[design D7](../../../openspec/changes/archive/2026-11-11-deployment-storage-class/design.md).

Install on every node:

```sh
sudo tee /etc/systemd/system/release-kubelet-volumes.service >/dev/null <<'EOF'
[Unit]
Description=Stop k3s pods and unmount their volumes before the network stops
Wants=network-online.target
After=network-online.target
Before=k3s.service k3s-agent.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/bin/true
ExecStop=-/bin/sh -c 'pkill -9 -f /usr/local/bin/[c]ontainerd-shim-runsc-v1; pkill -9 runsc; for i in $$(seq 30); do pgrep runsc >/dev/null || break; sleep 1; done'
ExecStop=/usr/local/bin/k3s-killall.sh
TimeoutStopSec=180

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now release-kubelet-volumes.service
```

Units stop in the reverse of their start order, so this one stops after k3s
and before the network. k3s stops with `KillMode=process`, leaving its
containers running; `k3s-killall.sh` then kills them and unmounts everything
under `/var/lib/kubelet/pods` and `/var/lib/kubelet/plugins`, CSI staging
mounts included. Ordered after k3s instead, the script's own `systemctl stop
k3s-agent` would wait on the shutdown's queued stop of k3s, which waits on this
unit: a deadlock until `TimeoutStopSec`. For the same reason the unit's name
must not start with `k3s`: the script stops every `k3s*.service`, so it would
stop the unit it runs in.

The first `ExecStop` kills the gVisor pods: the script kills only shims under
k3s's data directory, and gVisor's `containerd-shim-runsc-v1` is installed
separately. A sandbox left running keeps its volumes busy, so they would not
unmount until after the network stops. Its `-` lets a node without gVisor pods
carry on.

- **Orderly shutdown or reboot:** needs the unit. Without it, the shutdown
  hangs on the unmount.
- **Crash or power loss:** needs nothing. Nothing is unmounted, so nothing
  waits; on the next map the volume's ext4 journal replays, and Ceph breaks the
  dead client's exclusive lock.
