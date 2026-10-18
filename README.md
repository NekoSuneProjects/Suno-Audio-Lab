# NekoSune Suno Audio Lab

Free, local-first audio finishing app with a browser UI. Supports WAV, MP3, FLAC, M4A, OGG, and AIFF uploads, three processing presets, optional -16 LUFS normalization, FLAC/WAV/MP3 exports, before/after spectrograms, waveforms, and loudness reports.

**This is an audio-quality tool, not an AI fingerprint-removal or provenance-concealment tool.** It does not run an AI music detector or promise a particular detection score. It cannot verify removal of undisclosed watermarks. FFmpeg transcoding may fail to retain C2PA credentials even when common metadata is mapped; keep your original file and accurately disclose provenance where required.

## Quick start (Docker)

```bash
mkdir -p data
# Linux only, if needed for the non-root container user:
sudo chown -R 10001:10001 data
docker compose up -d --build
```

Visit http://localhost:8787. Docker Compose publishes on **127.0.0.1 only** by design. To reach it from another device, use a secure authenticated proxy or SSH port forwarding. Do **not** expose this upload service directly to the public Internet without authentication, upload limits, rate limiting and operational hardening.

## AMD64 and ARM64 (including Raspberry Pi)

This project builds on **linux/amd64** (Intel/AMD PCs and VPSs) and **linux/arm64** (64-bit Raspberry Pi OS / Ubuntu on Pi 4 or Pi 5, and ARM64 servers). The official Python 3.12 Debian Bookworm image and Debian FFmpeg provide native packages for both. No GPU, CUDA, x86 binaries, or architecture-specific Python packages are required. **ARMv7/32-bit Raspberry Pi OS is not supported.** Check `uname -m`: `x86_64` is AMD64, `aarch64` is ARM64.

On either supported machine:

```bash
uname -m
mkdir -p data
sudo chown -R 10001:10001 data
# Choose native architecture automatically; do not set platform: linux/amd64
docker compose up -d --build
docker compose ps
curl -f http://127.0.0.1:8787/api/health
```

For a Raspberry Pi accessed from your laptop, the default loopback binding intentionally *will not* serve other devices. The safest method is an SSH tunnel on the laptop (`ssh -L 8787:127.0.0.1:8787 <pi-user>@<pi-ip>`), then open `http://localhost:8787`. If you choose direct access on a trusted LAN, set `AUDIO_LAB_BIND=0.0.0.0` in a `.env` file next to `compose.yaml`, then run `docker compose up -d --build` and visit `http://<pi-ip>:8787`. **Warning:** the LAN service has no authentication; don't publish it to the internet. A firewall or authenticated reverse proxy is recommended.

**Performance:** CPU-only FFmpeg works on ARM64 but can be noticeably slower on a Pi than on an x86 desktop. A Pi 4 with 4 GB+ RAM or Pi 5 is recommended for comfortable use, especially for long files; the container has a 2 GB memory cap. Store `data/` on storage with enough free space for temporary files and outputs. Raspberry Pi OS **64-bit** or Ubuntu Server **ARM64** is required.

Optional multi-architecture build verification (requires a working Docker Buildx builder and QEMU emulation or native builder for both targets):

```bash
./scripts/check-multiarch.sh
```

This only verifies image builds. Full application and runtime performance on real ARM64 hardware are not established by an x86-only build.

## Troubleshooting: 500 on upload / permission denied

If the API logs show `PermissionError: [Errno 13] Permission denied: '/data/...'` on `POST /api/process`, the bind-mounted `./data` directory is not writable by the container's non-root UID **10001**. The server may still show `/api/health` as healthy.

From the directory containing `compose.yaml` on the host (not inside the container), run:

```bash
docker compose down
sudo mkdir -p data
sudo chown -R 10001:10001 data
sudo chmod -R u+rwX data
docker compose up -d
```

Check with `docker compose exec audio-lab sh -c 'id && ls -ld /data && test -w /data && echo writable'`. This preserves existing data and does not require rebuilding the image. If you instead use a Docker named volume or a different host bind path, identify that mount using `docker inspect suno-audio-lab --format '{{json .Mounts}}'` and fix permissions on the appropriate storage. With NFS root-squash, SMB or a read-only mount, host `chown` may fail; configure ownership/ACLs on the underlying storage rather than applying `chmod 777`.

A shutdown with exit code 143 is typically SIGTERM and not this upload failure. A favicon 404 is cosmetic.

## Processing

- **Studio quality:** conservative EQ and low-ratio compression for full musical mixes. Checks the processed duration against the original and (when normalization is off) rejects >4 LU loudness changes. The original upload is retained in the job folder on successful processing.
- **Transparent:** peak limiter; optional loudness normalization.
- **Gentle:** high-pass at 25 Hz, subtle low-mid EQ, presence EQ and light compression.
- **Vocal:** high-pass at 35 Hz, more noticeable mid EQ and light compression.
- **Normalize:** one-pass EBU R128 target (-16 LUFS integrated, -1.5 dBTP, LRA 11); actual measured loudness may differ. Does not guarantee preservation of all metadata or playback quality.

Uploaded originals and outputs are stored under `data/<random_job_id>/`. Anyone who has a job's random URL can access its files; there are no accounts/authentication or auto-cleanup. Treat job URLs as sensitive. Delete job folders to reclaim space. Limit use to trusted users.

## API

- `GET /api/health` health/status
- `POST /api/process` multipart form: `file`, `preset` (`transparent`, `gentle`, `vocal`), `output_format` (`flac`, `wav`, `mp3`), `normalize` (`true`/`false`)
- `GET /api/jobs/{job_id}/report.json` get the measurements for a processed job
- `GET /api/jobs/{job_id}/processed.flac` (or `.wav`/`.mp3`) download processed audio

## Requirements

Docker Engine with Compose plugin, about 2 GB RAM, and disk space for both audio copies. CPU processing; no GPU required. Not suitable for high-volume/public multi-tenant workloads as supplied.

## Development

```bash
pip install -r requirements.txt
# Ensure ffmpeg/ffprobe are installed and on your PATH
DATA_DIR=./data uvicorn app.main:app --reload
```

## Licensing

App source is released under MIT (`LICENSE`). FFmpeg, its linked libraries, and installed Python dependencies retain their respective licenses.
