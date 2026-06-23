# Soul Font

Soul Font Advanced is a Django web application for creating a personal Korean handwriting font from a completed PDF handwriting template. The app accepts a user's template upload, crops and cleans the glyph samples, runs the handwriting model for Hangul generation, vectorizes the generated PNG glyphs with Node.js, and saves a downloadable TTF font.

## What is in this repository

- `proj01/` - main Django project and app.
- `proj01/pybo/` - web views, forms, models, templates, and routes.
- `proj01/font_processor.py` - PDF-to-glyph preprocessing and inference pipeline.
- `proj01/inference.py` - model loading and glyph image generation.
- `proj01/generateTTF.js` - PNG/SVG glyph conversion and TTF generation.
- `proj01/data/charset/` - Korean target character sets.
- `requirements.txt` - compact ML/font-processing dependency list.
- `requirments_d.txt` - full pinned dependency list used by the Django app. The filename is intentionally referenced as it exists in the repo.

## Prerequisites

Install these before starting:

- Python 3.9 or newer.
- Node.js and npm.
- Poppler, required by `pdf2image`.

On macOS, Poppler can be installed with Homebrew:

```bash
brew install poppler
```

## Required model checkpoint (the one manual download)

The handwriting template (`proj01/static/templates/28_template.pdf`) and the default
font (`proj01/media/ttf_files/MaruBuri-Regular.ttf`) are already included in the repo,
so the **only** asset you must download yourself is the model checkpoint (it is too
large to track in Git):

1. Open the DM-Font v1.0.0 release: https://github.com/clovaai/dmfont/releases/tag/v1.0.0
2. Download the pretrained Korean generator weights.
3. Save the file as `proj01/checkpoints/korean-handwriting.pth` (create the
   `proj01/checkpoints/` folder and rename the downloaded file to that exact name).

Without this file the web app still runs, but font generation will fail at the
inference step. The app creates the runtime directories it needs
(`proj01/uploads/`, `proj01/FONT/`, `proj01/style/`, `proj01/static/outputs/`, and
additional files under `proj01/media/`) automatically as fonts are generated.

## Setup

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirments_d.txt
```

Install the Node.js dependencies used for TTF generation:

```bash
cd proj01
npm install
cd ..
```

Initialize the Django database:

```bash
cd proj01
python manage.py migrate
```

Optional: create an admin account.

```bash
python manage.py createsuperuser
```

## Run the development server

From `proj01/` with the virtual environment activated:

```bash
python manage.py runserver
```

Open the app at:

```text
http://127.0.0.1:8000/
```

Useful routes:

- `/pybo/` - home page.
- `/signup/` - create a user account.
- `/login/` - log in.
- `/create/` - upload a handwriting template.
- `/result/` - view and edit generated font metadata.
- `/admin/` - Django admin.

## Font generation workflow

1. Start the Django development server.
2. Sign up or log in.
3. Download and fill out the handwriting template.
4. Upload the completed PDF from the create page.
5. Choose fast generation for the common 2,350 Hangul set or full generation for the 11,172 Hangul set.
6. Wait for the background pipeline to finish.
7. Open the result/user page to download the generated TTF.

The web pipeline calls:

```text
FontStyleProcessor -> inference.py -> generateTTF.js -> set_font_metadata.py
```

## Running the model scripts directly

Training entry point:

```bash
cd proj01
python train.py <run-name> <config.yaml>
```

Inference entry point:

```bash
cd proj01
python inference.py <config.yaml> checkpoints/korean-handwriting.pth static/outputs/manual_run
```

The inference config must include style image paths, style characters, target characters, architecture settings, and `language: kor`.

## Troubleshooting

- `ModuleNotFoundError: django`: install the full dependency file with `python -m pip install -r requirments_d.txt`.
- `pdf2image` or PDF conversion errors: install Poppler and make sure it is available on your `PATH`.
- Missing checkpoint errors: place `korean-handwriting.pth` in `proj01/checkpoints/`.
- `node generateTTF.js <userId>` errors: run `npm install` inside `proj01/`.
- Generated font is missing: check the Django server logs; generation runs in a background thread and writes intermediate files under `proj01/FONT/<user_id>/`, `proj01/style/`, and `proj01/static/outputs/`.

## Development notes

The default Django settings use SQLite, `DEBUG = True`, and permissive `ALLOWED_HOSTS`, so they are intended for local development. Before deploying, move secrets into environment variables, turn off debug mode, restrict hosts, and configure persistent storage for media, static files, model checkpoints, and generated fonts.
