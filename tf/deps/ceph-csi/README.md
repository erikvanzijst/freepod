# ceph-csi

The ceph-csi RBD driver, against a Ceph cluster that runs outside Kubernetes:
one StorageClass, Secret and cephx client per pool (`main.tf` in `tf/deps`).
Which class a deployment's volumes use is the platform's decision, per
deployment: [deployment-storage-class](../../../openspec/changes/deployment-storage-class/specs/deployment-storage-class/spec.md).

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
[design D7](../../../openspec/changes/deployment-storage-class/design.md).

Install on every node:

```sh
sudo tee /etc/systemd/system/k3s-release-volumes.service >/dev/null <<'EOF'
[Unit]
Description=Stop k3s pods and unmount their volumes before the network stops
Wants=network-online.target
After=network-online.target k3s.service k3s-agent.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/bin/true
ExecStop=/usr/local/bin/k3s-killall.sh
TimeoutStopSec=180

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now k3s-release-volumes.service
```

Units stop in the reverse of their start order, so this one stops before k3s
and before the network. `k3s-killall.sh` stops k3s, kills the containers and
unmounts everything under `/var/lib/kubelet/pods` and
`/var/lib/kubelet/plugins`, CSI staging mounts included.

- **Orderly shutdown or reboot:** needs the unit. Without it, the shutdown
  hangs on the unmount.
- **Crash or power loss:** needs nothing. Nothing is unmounted, so nothing
  waits; on the next map the volume's ext4 journal replays, and Ceph breaks the
  dead client's exclusive lock.
