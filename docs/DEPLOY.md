# Deploying to Hugging Face Spaces

A free CPU Space gives 16 GB RAM and 2 vCPU — enough to hold torch and the 183 MB
checkpoint, which is what rules out most other free hosts.

## 1. Put the checkpoint where the Space can fetch it

Too large for Git, so it is downloaded at boot. Upload it to a Hugging Face model repo:

```bash
pip install huggingface_hub
huggingface-cli login
huggingface-cli repo create soul-font-checkpoint --type model
huggingface-cli upload soul-font-checkpoint \
    soulfont/checkpoints/korean-handwriting.pth korean-handwriting.pth --repo-type model
```

The download URL is then:

```text
https://huggingface.co/<username>/soul-font-checkpoint/resolve/main/korean-handwriting.pth
```

Any public direct-download URL works instead.

## 2. Create the Space

New Space → SDK **Docker**, blank template, CPU basic (free). The README's YAML header
already declares `sdk: docker` and `app_port: 7860`, so the push in step 4 configures it.

## 3. Set its secrets

Space → Settings → Variables and secrets:

| Name | Value |
| --- | --- |
| `DJANGO_SECRET_KEY` | a long random string — the fallback in `settings.py` is committed to this repo and therefore public |
| `SOULFONT_CHECKPOINT_URL` | the URL from step 1 |
| `HF_TOKEN` | a read token, only if that model repo is private |

Generate a key with `python -c "import secrets; print(secrets.token_urlsafe(50))"`.

## 4. Push

```bash
git remote add space https://huggingface.co/spaces/<username>/<space-name>
git push space main
```

The first build takes around ten minutes, most of it installing torch. The first boot
then downloads the checkpoint before gunicorn starts.

## What to expect

- **Generation is slow.** CPU-only, so the 2,350-syllable set takes several minutes
  against 17 s on your Mac's GPU. The full 11,172-syllable option is not realistic there.
- **Everything resets on rebuild.** Free Spaces have no persistent disk: accounts, the
  database and every generated font are lost. Enabling persistent storage (~$5/mo) mounts
  a volume at `/data`, which is already where the app writes.
- **The Space sleeps** after prolonged inactivity and wakes on the next visit — and
  re-downloads the checkpoint unless storage is persistent.
- **A restart kills any build in progress.** Generation is a thread inside the web
  process, and nothing resumes it.
- **No admin account exists** on a fresh deploy. Sign up through the site as usual; if you
  need `/admin/`, run `createsuperuser` from the Space's terminal.

## Testing the image locally

```bash
docker build -t soulfont .
docker run --rm -p 7860:7860 \
    -e DJANGO_SECRET_KEY=dev \
    -e DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1 \
    -e SOULFONT_CHECKPOINT_URL=<url> \
    soulfont
```

Then open http://127.0.0.1:8000 → http://127.0.0.1:7860.

## What the container changes

Every one of these is an environment variable with a local-development default, so
running `manage.py runserver` on your machine is unaffected.

| Variable | In the container | Why |
| --- | --- | --- |
| `DJANGO_DEBUG` | `0` | never run a public site with debug on |
| `DJANGO_ALLOWED_HOSTS` | `.hf.space,…` | `*` accepts Host-header spoofing |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | `https://*.hf.space` | without it every POST fails CSRF behind the proxy |
| `DJANGO_BEHIND_PROXY` | `1` | the proxy terminates TLS; Django would build `http://` redirects |
| `SOULFONT_DATA_DIR` | `/data` | database and generated fonts on the volume, not in the image |
| `SOUL_FONT_DEVICE` | `cpu` | there is no GPU, and this also makes builds reproducible |
