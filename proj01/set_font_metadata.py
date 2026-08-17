"""Set TTF metadata reliably with fonttools.

The previous opentype.js post-processing only wrote English name records (and the
pipeline shipped the *pre*-metadata file anyway), so the Korean family name never
stuck and had to be fixed by hand in FontForge. This sets the name table for both
English and Korean Windows language IDs plus a Mac record, and recalculates the
OS/2 Unicode/codepage ranges so the font advertises Hangul + Latin coverage.

Usage (CLI):  python set_font_metadata.py <ttf_path> <font_name> [out_path]
Usage (code): from set_font_metadata import apply_metadata
"""
import sys
from fontTools.ttLib import TTFont, newTable

# Windows (platformID 3, platEncID 1 = Unicode BMP)
LANG_EN = 0x409   # en-US
LANG_KO = 0x412   # ko-KR

# Name records svg2ttf stamps on every font it builds. They advertise the wrong tool and
# link to an unrelated project, so they are cleared unless the user supplies their own.
TOOL_NAME_IDS = (10, 11)   # Description, URL Vendor


def _ascii_postscript_name(font_name, user_id=''):
    """PostScript names must be ASCII with no spaces/special chars."""
    ascii_part = ''.join(c for c in font_name if c.isascii() and (c.isalnum()))
    return ascii_part or f"SoulFont{user_id}"


def _set_name(name_table, name_id, value, ascii_only=False):
    # Windows (platformID 3) records are UTF-16 and handle any Unicode; this is what
    # modern apps read for the family/full names.
    name_table.setName(value, name_id, 3, 1, LANG_EN)      # Windows / English
    if not ascii_only:
        name_table.setName(value, name_id, 3, 1, LANG_KO)  # Windows / Korean
    # The Mac/Roman record can only encode Latin, so only add it for ASCII values.
    if value.isascii():
        name_table.setName(value, name_id, 1, 0, 0)        # Mac / Roman / English
    else:
        # Drop any stale Mac record so it can't override the new Korean name.
        name_table.removeNames(nameID=name_id, platformID=1)


# Supported weights -> (OS/2 usWeightClass, subfamily/style name).
WEIGHTS = {
    'Light': (300, 'Light'),
    'Regular': (400, 'Regular'),
    'Bold': (700, 'Bold'),
}


def _apply_weight(font, weight):
    """Set OS/2 usWeightClass + the bold style bits so the OS groups & styles the weight.

    The family name (IDs 1/16) is kept identical across weights, so Light, Regular,
    and Bold install as one family with proper style selection.
    """
    us_weight, _ = WEIGHTS.get(weight, WEIGHTS['Regular'])
    is_bold = weight == 'Bold'
    font['OS/2'].usWeightClass = us_weight

    macstyle = font['head'].macStyle
    fssel = font['OS/2'].fsSelection
    if is_bold:
        macstyle |= 0x01                  # head.macStyle bit0 = Bold
        fssel = (fssel | 0x20) & ~0x40    # fsSelection: set BOLD, clear REGULAR
    elif weight == 'Regular':
        macstyle &= ~0x01
        fssel = (fssel | 0x40) & ~0x20    # set REGULAR, clear BOLD
    else:
        macstyle &= ~0x01
        fssel &= ~0x60                    # Light is neither REGULAR nor BOLD
    font['head'].macStyle = macstyle
    font['OS/2'].fsSelection = fssel


def _ink_top(font, char):
    """yMax of a reference glyph, for the OS/2 cap-height / x-height fields."""
    name = font.getBestCmap().get(ord(char))
    if not name:
        return None
    glyf = font['glyf']
    if name not in glyf.glyphs:
        return None
    glyph = glyf[name]
    if glyph.numberOfContours <= 0:
        return None
    glyph.recalcBounds(glyf)
    return glyph.yMax


def _apply_font_defaults(font):
    """Fill in the table fields svg2ttf leaves at zero or points at its own project.

    None of this changes an outline; it is the difference between a font an OS treats as
    a proper handwriting family and one it treats as an unidentified icon set.
    """
    name = font['name']
    for name_id in TOOL_NAME_IDS:
        name.removeNames(nameID=name_id)

    os2 = font['OS/2']
    os2.achVendID = 'SFNT'
    # PANOSE: family 3 = Latin Hand Written, proportionally spaced. Font menus use this to
    # group script faces; the default (0/2 = "any"/text) files handwriting under serif text.
    os2.panose.bFamilyType = 3
    os2.panose.bSerifStyle = 0
    os2.panose.bProportion = 0
    # Metrics that layout engines read for vertical centring — zero means "unknown".
    cap = _ink_top(font, 'H') or _ink_top(font, 'A')
    ex = _ink_top(font, 'x') or _ink_top(font, 'o')
    if cap:
        os2.sCapHeight = cap
    if ex:
        os2.sxHeight = ex
    # Prefer the sTypo* metrics for line spacing so lines are laid out the same on every
    # platform instead of Windows falling back to the usWin* clipping box. The bit only
    # exists from OS/2 version 4, and font builders still default to 3.
    if os2.version < 4:
        os2.version = 4
    os2.fsSelection |= 1 << 7   # USE_TYPO_METRICS

    post = font['post']
    post.isFixedPitch = 0
    post.underlinePosition = -150
    post.underlineThickness = 50

    head = font['head']
    head.lowestRecPPEM = 8

    # gasp tells Windows to use grayscale antialiasing (and symmetric smoothing) at every
    # size. Without it, traced handwriting outlines get hinted into a jagged mess at
    # screen sizes on GDI.
    if 'gasp' not in font:
        gasp = newTable('gasp')
        gasp.version = 1
        gasp.gaspRange = {0xFFFF: 0x000F}
        font['gasp'] = gasp


def apply_metadata(ttf_path, font_name, out_path=None, user_id='',
                   designer='', manufacturer='Generated by Soul Font',
                   copyright='', description='', license_text='', license_url='',
                   version='', weight='Regular'):
    """Write name records + OS/2 ranges into `ttf_path` (in place unless out_path given).

    Any optional field left blank is simply skipped (existing value untouched).
    `weight` is 'Light', 'Regular', or 'Bold'; the family name stays the same so
    the faces group in font menus.
    """
    out_path = out_path or ttf_path
    style = WEIGHTS.get(weight, WEIGHTS['Regular'])[1]
    font = TTFont(ttf_path)
    name = font['name']
    ps_name = _ascii_postscript_name(font_name, user_id)
    # Clears the generator's leftover records first, so user-supplied ones below stick.
    _apply_font_defaults(font)

    _set_name(name, 1, font_name)                 # Font Family
    _set_name(name, 2, style)                     # Font Subfamily
    _set_name(name, 4, f'{font_name} {style}')    # Full font name
    _set_name(name, 6, f'{ps_name}-{style}', ascii_only=True)  # PostScript name (ASCII)
    _set_name(name, 16, font_name)                # Typographic Family
    _set_name(name, 17, style)                    # Typographic Subfamily
    _set_name(name, 8, manufacturer)              # Manufacturer
    _apply_weight(font, weight)

    # Optional, user-supplied records.
    if designer:
        _set_name(name, 9, designer)              # Designer
    if copyright:
        _set_name(name, 0, copyright)             # Copyright notice
    if description:
        _set_name(name, 10, description)          # Description
    if license_text:
        _set_name(name, 13, license_text)         # License description
    if license_url:
        _set_name(name, 14, license_url, ascii_only=True)  # License URL
    if version:
        ver = version if version.lower().startswith('version') else f'Version {version}'
        _set_name(name, 5, ver, ascii_only=True)  # Version string

    os2 = font['OS/2']
    # Recalculate Unicode range bits from the actual cmap coverage (Hangul + Latin).
    try:
        os2.recalcUnicodeRanges(font)
    except Exception:
        pass
    # Codepage ranges: Latin-1 (bit 0) + Korean Wansung 949 (bit 19).
    os2.ulCodePageRange1 = (os2.ulCodePageRange1 or 0) | (1 << 0) | (1 << 19)

    font.save(out_path)
    print(f"[metadata] '{font_name}' written to {out_path}")
    return out_path


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("Usage: python set_font_metadata.py <ttf_path> <font_name> [out_path]")
        sys.exit(1)
    apply_metadata(sys.argv[1], sys.argv[2],
                   out_path=sys.argv[3] if len(sys.argv) > 3 else None)
