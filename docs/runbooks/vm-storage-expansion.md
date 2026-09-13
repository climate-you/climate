# Runbook: Expanding VM Storage

Use this runbook when the production VM is running out of disk for the artifact
store.

What you are deciding:

- whether to rescale the server (bigger local NVMe) or attach a Cloud Volume
  (network block storage)
- how to move `/opt/climate/data` onto new storage without losing hardlinks
- how much downtime to expect, and how to roll back

Where it applies:

- Hetzner Cloud VM hosting the API and its artifact store
- `/opt/climate/data`, which holds both `artifacts/` and `releases/`
  (created by `scripts/deploy/bootstrap_vm.sh`)

## Why Storage Runs Out

A single copy of the release data is roughly 19 GB, dominated by the daily
metrics (`t2m_daily_mean_c` and `t2m_daily_max_c` are about 5.8 GB each).

`publish_release.py` writes each changed artifact into a **new dated
directory** and leaves earlier dates in place, so a release can be pinned or
rolled back. Disk therefore grows with every publish that changes something.

Two mechanisms keep that in check:

- `publish_release.py` hardlinks files identical to the artifact's previous
  version, so republishing a metric to change one ranking file costs almost
  nothing (see `--no-link-dest` to disable)
- `prune_artifacts.py` deletes artifact versions no longer referenced by any
  kept release

If pruning reclaims nothing and the disk is still tight, the working set itself
has outgrown the disk and this runbook applies.

## Choosing Between a Volume and a Rescale

| | Cloud Volume | Rescale the server |
| --- | --- | --- |
| Disk type | Network-attached SSD | Local NVMe |
| Downtime to provision | None (hot attach) | A few minutes (power off) |
| Resize later | Yes, online, grow-only | Yes, but grow-only and irreversible |
| Cost shape | Per GB/month, independent of CPU/RAM | Larger plan: disk, CPU and RAM together |
| Read latency | Higher | Unchanged |

Verify current Hetzner pricing, size limits and plan options in the console —
they change, and this table records the shape of the choice rather than the
numbers.

### The Latency Consideration

This deployment is unusually sensitive to storage latency, so do not pick a
Volume on cost alone.

`TileDataStore.try_get_metric_vector` stats and reads a tile file **on every
call**, with no cache in front of it. The `Cache` object in `climate_api/cache.py`
is wired to the panel and graph endpoints, not to tile reads, and its in-process
fallback does not cover them either. Redis, when configured, does not change
this.

That means:

- every location series lookup is a small random file read
- `find_extreme_location`'s scan path performs one such read **per candidate
  city**, thousands per call, whenever it cannot use a precomputed ranking

A network volume adds latency to each of those reads. The precomputed rankings
are loaded into memory at startup and cost nothing, so the common ranking
queries are unaffected — but the scan path and ordinary per-location series
requests are not.

### Measure Before Committing

A Volume is cheap to test and attaches without downtime, so measure rather than
guess. Attach a small volume, copy one metric onto it, and time the same
workload against both paths:

```bash
# On the VM, with a small volume mounted at /mnt/test-volume
sudo mkdir -p /mnt/test-volume/series/global_0p25
sudo rsync -aHAX /opt/climate/data/artifacts/series/t2m_yearly_mean_c/<date>/ \
  /mnt/test-volume/series/global_0p25/t2m_yearly_mean_c/

# Time a few thousand small random reads from each location
for root in /opt/climate/data/artifacts/series/t2m_yearly_mean_c/<date> \
            /mnt/test-volume/series/global_0p25/t2m_yearly_mean_c; do
  echo "== $root"
  sudo sh -c 'echo 3 > /proc/sys/vm/drop_caches'   # cold cache, else you time RAM
  /usr/bin/time -f '  %e s' find "$root/z64" -name '*.bin.zst' \
    | head -2000 | xargs -n1 dd of=/dev/null bs=64k status=none
done
```

Drop the page cache between runs or the second measurement reads from RAM and
both look identical. If the volume is within a few tens of percent on the cold
read, it is fine for this workload; if it is several times slower, rescale
instead.

## Migrating to a Cloud Volume

Total downtime is the catch-up sync plus a service restart — a few minutes. The
bulk copy happens while the service is still serving.

### 1. Provision (no downtime)

Create the volume in the **same location as the server** and attach it in the
console. It appears as `/dev/disk/by-id/scsi-0HC_Volume_<id>`.

```bash
lsblk                      # confirm the new device
sudo mkfs.ext4 -F /dev/disk/by-id/scsi-0HC_Volume_<id>
sudo mkdir -p /mnt/climate-data
sudo mount /dev/disk/by-id/scsi-0HC_Volume_<id> /mnt/climate-data
```

### 2. Bulk copy (no downtime)

```bash
sudo rsync -aHAX --info=progress2 /opt/climate/data/ /mnt/climate-data/
```

**The `-H` is not optional.** See [Preserving Hardlinks](#preserving-hardlinks).

### 3. Cut over (downtime starts)

```bash
sudo systemctl stop climate-backend climate-web
sudo rsync -aHAX --delete /opt/climate/data/ /mnt/climate-data/   # catch-up
sudo mv /opt/climate/data /opt/climate/data.old
sudo mkdir /opt/climate/data
sudo umount /mnt/climate-data
sudo mount /dev/disk/by-id/scsi-0HC_Volume_<id> /opt/climate/data
sudo chown -R climate:climate /opt/climate/data
sudo systemctl start climate-backend climate-web
```

### 4. Persist the mount

Add to `/etc/fstab`, using the `by-id` path — kernel names such as `/dev/sdb`
are not stable across reboots:

```
/dev/disk/by-id/scsi-0HC_Volume_<id>  /opt/climate/data  ext4  discard,nofail,defaults  0 0
```

`nofail` matters: without it a detached or slow-to-attach volume blocks boot and
leaves the VM needing console recovery.

Confirm it survives a reboot before deleting anything:

```bash
sudo umount /opt/climate/data && sudo mount -a && df -h /opt/climate/data
```

### 5. Verify, then reclaim

```bash
df -h /opt/climate/data                    # expect the new size
sudo -u climate ls /opt/climate/data/artifacts/series | head
bash scripts/deploy/smoke_check.sh --local # run from the app root on the VM
```

Fetch a real tile through the API and confirm a chat question answers. Only
then:

```bash
sudo rm -rf /opt/climate/data.old
```

Keeping `data.old` until you are confident is the rollback: stop the service,
unmount, `mv` it back, start.

## Preserving Hardlinks

The artifact store deliberately shares inodes between artifact versions —
`publish_release.py` hardlinks each new version against the previous one. Any
copy that does not understand hardlinks will expand every one of them into a
full copy, re-inflating the store to the size you are migrating to escape.

- `rsync -aH` — correct (`-aHAX` also carries ACLs and xattrs)
- `cp -a` — correct
- `rsync -a` without `-H` — **wrong**, silently duplicates
- `cp -r`, `tar` without `--hard-dereference` awareness, most GUI copies — **wrong**

Check the result before deleting the source. The store total should be well
below the sum of its parts:

```bash
du -sh /opt/climate/data/artifacts                        # whole store
du -sh /opt/climate/data/artifacts/series/*/*/ | head     # individual versions
```

Per-directory sizes double-count shared inodes, so each version reporting its
full size while the store total stays small is the expected, healthy result. If
the total equals the sum, hardlinks were lost — re-copy with `-H`.

Hardlinks cannot cross filesystems. Move **all** of `/opt/climate/data` to the
new storage: splitting `artifacts/` from `releases/`, or putting only some
metrics on the volume, breaks linking silently. If the store must span
filesystems, publish with `--no-link-dest` and accept full copies.

## Sizing Guidance

Budget roughly four times the working set — about 80 GB for today's 19 GB, and
100 GB for comfort. That covers:

- the working set itself
- a full second copy during a migration or large republish
- growth, which comes mainly from new metrics rather than new years (each
  daily-resolution metric lands around 6 GB)

Hardlinking removes most of the per-publish growth, but not the first copy of a
genuinely new metric, which is what fills a disk quickly.

## Related Runbooks

- `docs/runbooks/deployment.md` — publishing releases and deploying the app
- `docs/runbooks/dataset-cache-and-packaging.md` — what produces the artifacts
