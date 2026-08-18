# Architecture

A Django app (accounts, uploads, pages) and a font foundry (directories of PNGs in, a TTF
family out). They meet at one background thread started in `pybo/views.py`.

```text
browser ──▶ pybo/views.py ──▶ threading.Thread(_background_pipeline)
   ▲                                     │
   │  polls /pybo/user/<id>/status/      ├─▶ foundry/  crop → generate → clean → trace → fit → stamp
   └─────── UserData row ◀───────────────┘   writes workdir/ and media/ttf_files/
```

That row is the thread's only channel back to the page — there is no queue and no worker
process, so builds die with the web process and nothing retries.

## Data model

`UserData` is one row per **font**, not per user, and its `id` keys everything else: the URL
`/pybo/user/<id>/`, the build directory `workdir/fonts/<id>/`, the TTF basename
`user_font_<id>.ttf`. `status`, `status_stage` and `status_percent` carry build progress and
are written with `.update()` rather than `save()`, so the thread cannot roll back the TTF
fields it wrote moments earlier. `show_on_home` marks the one font a user features in the
gallery. `Font` and `Template` are legacy.

## Pipeline

| # | Step | Code | Output |
| --- | --- | --- | --- |
| 1 | PDF to page rasters | `FontStyleProcessor.convert_pdf_to_images` | `workdir/crops/user_<id>/`, 300 dpi |
| 2 | page to cells | `foundry/crop.py` (subprocess) | `cropped/` trimmed to the mark, `framed/` keeping cell framing |
| 3 | ink/paper split | `clean_images` | `cleaned/`, 128×128 |
| 4 | cells to characters | `char_layout.split_cells` | 28 style refs, then Latin/digits/punctuation |
| 5 | generate Hangul | `foundry/inference.py` | `workdir/glyphs/user_<id>/inferred_<CP>.png` |
| 6 | Latin bypass | `copy_traced_glyphs` | same directory, from the 512 px framed crops |
| 7 | raster cleanup | `prepare_trace_images` | `workdir/fonts/<id>/trace_regular/` |
| 8 | trace | `glyph_vectorizer.build_ttf` | `media/ttf_files/user_font_<id>.ttf` |
| 9 | metrics | `refine_metrics` | rewrites that file |
| 10 | names, OS/2 | `set_font_metadata.apply_metadata` | rewrites that file |

`char_layout.py` is the single definition of which cell holds which character: 4×7 per page,
cells 0–27 the Korean style references, the rest `EXTRA_CHARS`. Change the printed template
and this file changes with it. Cell count and blank style cells are validated before
inference, so a bad upload is an error on the page rather than a garbage font.

Inference is DM-Font's `MACore` in two stages: encode the 28 style images into component
memory, decode each target syllable out of it. Targets are filtered to `[가-힣]` — the model
knows Hangul only, which is why Latin bypasses it. The generator is cached per (checkpoint,
config, device) and `_INFER_LOCK` serializes runs, because that cached component memory is
mutable. GPU on Apple Silicon, CUDA opt-in, fp16 refused on Metal (it damages every glyph).

Light and Bold are the same `trace_regular` rasters with each glyph's distance field offset,
then traced and fitted like Regular. All three use the fit measured once on Regular and saved
to `glyph_fit.json`, so the editor's later exports match the family. Both are best-effort: a
failure leaves Regular intact.

Thresholds in `prepare_trace_images` and `glyph_vectorizer.py` are relative to the glyph's own
stroke width or to the 1000-unit em, never to the frame. The reasoning is in those files.

## Disk layout

```text
uploads/user_<id>.pdf         the uploaded template
workdir/crops/user_<id>/      page rasters, cropped/, framed/, cleaned/
workdir/configs/<name>.yaml   the generated inference config
workdir/glyphs/user_<id>/     model output + traced Latin
workdir/fonts/<id>/           trace_regular/, trace_light/, trace_bold/, glyph_fit.json
media/ttf_files/              the finished TTFs
```

All of `workdir/` is disposable.

## Frontend

`base.html` owns the menu bar; pages fill `app_name`, `app_menus` and `content`. `retro.js`
does pull-down menus, desktop patterns, the Coverflow/list switch and alerts. `system7.js` is
the window manager, active only where `#desk` exists: it fetches an application's URL, lifts
the `.window` element out of the response, runs that page's own scripts against it, and
mirrors open windows into `location.hash`. Icons are links and forms are forms, so the site
works with both scripts absent.

## Limits

- Builds are threads in the web process: no retry, nothing survives a restart.
- The model cache is per-process, so each worker holds its own copy of the checkpoint.
- `workdir/` is never pruned; one run leaves tens of thousands of PNGs.
- `generateTTF.js` survives only as `SOULFONT_VECTORIZER=imagetracer`.
