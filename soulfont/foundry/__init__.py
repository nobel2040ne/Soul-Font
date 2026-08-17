"""Soul Font's own pipeline: template PDF in, installable TTF family out.

    char_layout        where each glyph sits in the printed template
    font_processor     PDF to cleaned glyph rasters, plus the weight variants
    inference          runs the handwriting model over the cropped samples
    glyph_vectorizer   rasters to Bezier outlines and a TTF
    refine_metrics     typographic fitting: sizes, side bearings, baseline
    set_font_metadata  name/OS2 tables so the three weights install as one family

The model itself (models/, datasets/, utils/) is vendored upstream and stays at the
project root, where its own flat imports expect it.
"""
