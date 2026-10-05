"""
ICON TRACE - barcodes and QR, rendered as inline SVG.

No internet, no image files, no fonts. The SVG goes straight into the page,
so a label prints identically from any browser on the plant network and
nothing has to be fetched at print time.

Code128 Auto is implemented here rather than pulled from a package: it is about
sixty lines, it has no dependencies, and the pallet sheet needs one barcode
per module - a package that fails to install on the plant machine would stop
printing, which is the one thing a label routine must not do.

QR uses the `qrcode` package (pure Python, no native library). If it is
missing the label still prints, with the payload as text instead. A missing
QR is a degraded label; a crash is no label.
"""

# --------------------------------------------------------------------------
# Code128 Auto (subsets B and C, optimal switching)
# --------------------------------------------------------------------------
#
# Code128 Auto is what Zebra Designer and every label printer call it: the
# encoder picks subset B for letters and subset C for runs of digits, where
# one symbol carries TWO digits. A serial's numeric tail therefore costs
# half as many symbols, and the printed barcode is that much narrower.
#
# The width depends on the serial, not just its length. Same 18 characters:
#   ICON520R1292134347  ->  189 modules  (month 9: one 10-digit tail)
#   ICON520R12A2134347  ->  211 modules  (month A: the letter splits the tail)
# Subset B alone was 233 for both. So barcodes on one sheet can differ in
# width - a pallet that mixes September and October modules will show both -
# and anything laid out around a barcode must centre on it, not assume a size.
#
# The choice of subsets is a shortest-path over (position, current subset),
# so the result is the minimum symbol count, not a rule of thumb. Serials are
# A-Z0-9 and subset A adds nothing over B for them, so only B and C are used.

_PATTERNS = [
    "212222", "222122", "222221", "121223", "121322", "131222", "122213",
    "122312", "132212", "221213", "221312", "231212", "112232", "122132",
    "122231", "113222", "123122", "123221", "223211", "221132", "221231",
    "213212", "223112", "312131", "311222", "321122", "321221", "312212",
    "322112", "322211", "212123", "212321", "232121", "111323", "131123",
    "131321", "112313", "132113", "132311", "211313", "231113", "231311",
    "112133", "112331", "132131", "113123", "113321", "133121", "313121",
    "211331", "231131", "213113", "213311", "213131", "311123", "311321",
    "331121", "312113", "312311", "332111", "314111", "221411", "431111",
    "111224", "111422", "121124", "121421", "141122", "141221", "112214",
    "112412", "122114", "122411", "142112", "142211", "241211", "221114",
    "413111", "241112", "134111", "111242", "121142", "121241", "114212",
    "124112", "124211", "411212", "421112", "421211", "212141", "214121",
    "412121", "111143", "111341", "131141", "114113", "114311", "411113",
    "411311", "113141", "114131", "311141", "411131", "211412", "211214",
    "211232", "2331112",
]
_START_B, _START_C, _STOP = 104, 105, 106
_CODE_C, _CODE_B = 99, 100      # switch codes: 99 inside B, 100 inside C


def _xml_escape(s):
    """The human-readable line under a barcode goes into SVG that pages embed
    with |safe - so it is escaped here. Code128-B carries < > & perfectly
    well; only serials reach this today, but nothing here should assume so."""
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;"))


def _pair(s, i):
    return i + 1 < len(s) and s[i].isdigit() and s[i + 1].isdigit()


def code128_codes(text):
    """Symbol values for `text`: start code, data (with any subset switches),
    checksum, stop. Characters outside subset B are dropped rather than
    encoded as something a scanner would read as garbage."""
    s = "".join(ch for ch in (text or "").strip() if 32 <= ord(ch) <= 126)
    if not s:
        return []
    n = len(s)
    INF = float("inf")
    # best[i][k]: fewest symbols to encode s[i:] when subset k is active
    # (k=0 is B, k=1 is C). Every move consumes input, so there is no cycle.
    best = [[INF, INF] for _ in range(n + 1)]
    move = [[None, None] for _ in range(n + 1)]
    best[n] = [0, 0]
    for i in range(n - 1, -1, -1):
        # in B: one character, or switch to C and take a digit pair
        b = (1 + best[i + 1][0], "b")
        if _pair(s, i):
            b = min(b, (2 + best[i + 2][1], "b>c"), key=lambda t: t[0])
        best[i][0], move[i][0] = b
        # in C: a digit pair, or switch to B and take one character
        c = (2 + best[i + 1][0], "c>b")
        if _pair(s, i):
            c = min((1 + best[i + 2][1], "c"), c, key=lambda t: t[0])
        best[i][1], move[i][1] = c

    # start in C only when it is strictly shorter; ties stay in B
    k = 1 if (_pair(s, 0) and best[0][1] < best[0][0]) else 0
    codes = [_START_C if k else _START_B]
    i = 0
    while i < n:
        m = move[i][k]
        if m == "b":
            codes.append(ord(s[i]) - 32); i += 1
        elif m == "c":
            codes.append(int(s[i:i + 2])); i += 2
        elif m == "b>c":
            codes += [_CODE_C, int(s[i:i + 2])]; i += 2; k = 1
        else:  # "c>b"
            codes += [_CODE_B, ord(s[i]) - 32]; i += 1; k = 0

    check = codes[0]
    for pos, c in enumerate(codes[1:], start=1):
        check += c * pos
    codes.append(check % 103)
    codes.append(_STOP)
    return codes


def code128_modules(text):
    """Width of the barcode in modules (narrow-bar units), quiet zones not
    included. Lets a layout size a barcode in mm before drawing it."""
    return sum(int(w) for c in code128_codes(text) for w in _PATTERNS[c])


def code128_svg(text, height=34, module=1.6, show_text=True, font=8):
    """One Code128 Auto barcode as inline SVG."""
    s = (text or "").strip()
    codes = code128_codes(s)
    if not codes:
        return ""

    bars, x = [], 0.0
    for c in codes:
        pat = _PATTERNS[c]
        dark = True
        for w in pat:
            width = int(w) * module
            if dark:
                bars.append('<rect x="%.2f" y="0" width="%.2f" height="%d"/>'
                            % (x, width, height))
            x += width
            dark = not dark
    total = x
    th = font + 3 if show_text else 0
    label = ('<text x="%.2f" y="%d" text-anchor="middle" font-size="%d" '
             'font-family="Consolas,monospace">%s</text>'
             % (total / 2.0, height + font, font, _xml_escape(s))) if show_text else ""
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="%.2f" height="%d" '
            'viewBox="0 0 %.2f %d" shape-rendering="crispEdges">'
            '<g fill="#000">%s</g>%s</svg>'
            % (total, height + th, total, height + th, "".join(bars), label))


# --------------------------------------------------------------------------
# Barcode for print: bars at a real size, the text under them styled apart
# --------------------------------------------------------------------------
#
# The pallet sheet used to size each barcode by its HEIGHT and let the width
# land wherever the aspect ratio put it - so the width followed the serial and
# whether the text sat inside the SVG, and a wide one pushed the table past
# the page margin. Here the narrow bar has a real width in mm, like a label
# designer's "narrow bar" setting, and the barcode is exactly as wide as its
# modules make it.
#
# 0.254 mm (10 mil) is 3 dots at 300 dpi and 6 at 600, so a laser printer
# draws every bar the same width; it is also what a 203 dpi Zebra prints at
# 2 dots. The text is NOT inside the SVG: there it shrank with the bars. It is
# set beside it in HTML, so its size is a real point size.
#
# These three are the DEFAULTS of the Settings "Barcode" card (bar width,
# height, quiet zone); BAR_DEFAULTS below is what is stored.

NARROW_BAR_MM = 0.254
BAR_HEIGHT_MM = 11.0
QUIET_MODULES = 10          # Code128 asks for ten modules of white on each side


def code128_bars_svg(text, module_mm=NARROW_BAR_MM, height_mm=BAR_HEIGHT_MM,
                     quiet=QUIET_MODULES):
    """Bars only, quiet zones included, sized in mm. Empty string for no
    serial. The serial rides along as aria-label, escaped. data-modules and
    data-quiet let the Settings preview resize it without re-encoding."""
    s = (text or "").strip()
    codes = code128_codes(s)
    if not codes:
        return ""
    rects, x = [], quiet
    for c in codes:
        dark = True
        for w in _PATTERNS[c]:
            w = int(w)
            if dark:
                rects.append('<rect x="%d" y="0" width="%d" height="1"/>' % (x, w))
            x += w
            dark = not dark
    total = x + quiet
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="%.3fmm" height="%.3fmm" '
            'viewBox="0 0 %d 1" preserveAspectRatio="none" shape-rendering="crispEdges" '
            'data-modules="%d" data-quiet="%d" '
            'role="img" aria-label="%s"><g fill="#000">%s</g></svg>'
            % (total * module_mm, height_mm, total, total - 2 * quiet, quiet,
               _xml_escape(s), "".join(rects)))


def bars_width_mm(text, module_mm=NARROW_BAR_MM, quiet=QUIET_MODULES):
    """Printed width of one barcode, quiet zones included - exactly what
    code128_bars_svg draws, so a layout can be checked before it prints."""
    return (code128_modules(text) + 2 * quiet) * module_mm


# The bars: width of the narrowest bar (the "module" or "X dimension"), height,
# and the white margin each side, in modules. Stored as strings like every
# setting. The quiet zone is held at the Code128 minimum of ten modules or
# more: less is not a layout choice, it is a barcode some scanners will not read.

BAR_DEFAULTS = {
    "bc_bar_width": "0.254",     # mm, the narrowest bar
    "bc_bar_height": "11",       # mm
    "bc_bar_quiet": "10",        # modules of white each side
}
BAR_RANGES = {   # key: (low, high, unit, name, decimals)
    "bc_bar_width": (0.15, 0.40, "mm", "Barcode module width", 3),
    "bc_bar_height": (6, 20, "mm", "Barcode height", 2),
    "bc_bar_quiet": (10, 25, "modules", "Barcode quiet zone", 0),
}


# The text under a barcode - what Bartender and Zebra Designer let you set on
# a text object. Always centred on the barcode, always below it, fixed size.
#
# Fonts are a fixed list, not free text: the sheet prints from whatever PC
# opens it, and a font that PC lacks silently falls back to something else.
# Windows ships every one of these; Poppins is bundled under static/fonts.
# A key is stored, never CSS, so a setting cannot inject into the page.

TEXT_FONTS = {   # key: (shown in Settings, CSS font stack)
    "arial":       ("Arial", "Arial, Helvetica, sans-serif"),
    "arial_black": ("Arial Black", "'Arial Black', Arial, sans-serif"),
    "calibri":     ("Calibri", "Calibri, Arial, sans-serif"),
    "segoe":       ("Segoe UI", "'Segoe UI', Arial, sans-serif"),
    "tahoma":      ("Tahoma", "Tahoma, Arial, sans-serif"),
    "verdana":     ("Verdana", "Verdana, Arial, sans-serif"),
    "poppins":     ("Poppins (bundled)", "Poppins, Arial, sans-serif"),
    "consolas":    ("Consolas (fixed width)", "Consolas, 'Courier New', monospace"),
    "courier":     ("Courier New (fixed width)", "'Courier New', Courier, monospace"),
    "lucida":      ("Lucida Console (fixed width)", "'Lucida Console', Consolas, monospace"),
    "times":       ("Times New Roman", "'Times New Roman', Times, serif"),
}

TEXT_DEFAULTS = {
    "bc_text_font": "arial",
    "bc_text_size": "10",        # pt
    "bc_text_spacing": "0",      # pt between letters
    "bc_text_gap": "0.8",        # mm between the bars and the text
    "bc_text_bold": "1",
    "bc_text_italic": "0",
    "bc_text_underline": "0",
}
_TEXT_RANGES = {"bc_text_size": (6, 20, "pt", "Barcode text size"),
                "bc_text_spacing": (-1, 6, "pt", "Barcode letter spacing"),
                "bc_text_gap": (0, 5, "mm", "Gap under the barcode")}
_TEXT_FLAGS = {"bc_text_bold": "Bold", "bc_text_italic": "Italic",
               "bc_text_underline": "Underline"}
_YES = {"1": "1", "true": "1", "on": "1", "yes": "1",
        "0": "0", "false": "0", "off": "0", "no": "0", "": "0"}


SETTING_DEFAULTS = dict(TEXT_DEFAULTS, **BAR_DEFAULTS)    # everything stored


def clean_settings(d):
    """(clean, why) for the barcode keys present in `d` - the bars and the text.
    All or nothing: one bad value refuses the lot, so a save never half-applies."""
    out = {}
    for k in SETTING_DEFAULTS:
        if k not in d:
            continue
        v = str(d[k] if d[k] is not None else "").strip()
        if k == "bc_text_font":
            if v not in TEXT_FONTS:
                return None, ("Barcode text font must be one of: %s."
                              % ", ".join(lbl for lbl, _ in TEXT_FONTS.values()))
        elif k in _TEXT_FLAGS:
            v = _YES.get(v.lower())
            if v is None:
                return None, "%s must be on or off." % _TEXT_FLAGS[k]
        else:
            if k in BAR_RANGES:
                lo, hi, unit, name, places = BAR_RANGES[k]
            else:
                (lo, hi, unit, name), places = _TEXT_RANGES[k], 2
            try:
                f = float(v)
            except ValueError:
                return None, "%s must be a number, not %r." % (name, v)
            if not (lo <= f <= hi):           # also refuses NaN
                return None, "%s must be from %g to %g %s." % (name, lo, hi, unit)
            if places == 0 and f != int(f):
                return None, "%s must be a whole number of modules, not %s." % (name, v)
            v = "%g" % round(f, places)
        out[k] = v
    return out, None


def _valid_settings(cfg, defaults):
    """`defaults`' keys, each from `cfg` where the stored value still
    validates, else the default. A bad stored value must never stop a pallet
    sheet from printing."""
    c = dict(defaults)
    for k in defaults:
        if cfg and k in cfg:
            ok, _ = clean_settings({k: cfg[k]})
            if ok:
                c.update(ok)
    return c


def text_settings(cfg):
    """The barcode-text settings to print with (see _valid_settings)."""
    return _valid_settings(cfg, TEXT_DEFAULTS)


def bar_settings(cfg):
    """The bar settings to print with, as the stored strings."""
    return _valid_settings(cfg, BAR_DEFAULTS)


def bar_params(cfg):
    """Keyword arguments for code128_bars_svg from the stored bar settings."""
    c = bar_settings(cfg)
    return {"module_mm": float(c["bc_bar_width"]),
            "height_mm": float(c["bc_bar_height"]),
            "quiet": int(float(c["bc_bar_quiet"]))}


def text_style(cfg):
    """Inline CSS for the text under a barcode.

    Letter-spacing is added after EVERY character, the last one included, so
    centred text with spacing sits half a space left of centre (measured in
    Chromium 141: 6 pt spacing put it 3.5 px off). A negative right margin of
    one spacing takes the trailing space back out, and the text centres on
    the bars exactly."""
    c = text_settings(cfg)
    sp = float(c["bc_text_spacing"])
    return ("font-family:%s;font-size:%spt;font-weight:%d;font-style:%s;"
            "text-decoration:%s;letter-spacing:%gpt;margin-right:%gpt;margin-top:%smm"
            % (TEXT_FONTS[c["bc_text_font"]][1], c["bc_text_size"],
               700 if c["bc_text_bold"] == "1" else 400,
               "italic" if c["bc_text_italic"] == "1" else "normal",
               "underline" if c["bc_text_underline"] == "1" else "none",
               sp, (-sp) or 0, c["bc_text_gap"]))


# --------------------------------------------------------------------------
# QR
# --------------------------------------------------------------------------

def qr_svg(text, module=2.4, quiet=2):
    """QR as inline SVG. Falls back to the payload in a box if the package is
    absent - a degraded label still prints."""
    try:
        import qrcode
    except Exception:
        return ('<svg xmlns="http://www.w3.org/2000/svg" width="90" height="90">'
                '<rect width="90" height="90" fill="none" stroke="#000"/>'
                '<text x="45" y="42" text-anchor="middle" font-size="7">QR</text>'
                '<text x="45" y="54" text-anchor="middle" font-size="6">'
                'not available</text></svg>')
    q = qrcode.QRCode(version=None, error_correction=qrcode.ERROR_CORRECT_M,
                      box_size=1, border=0)
    q.add_data(text)
    q.make(fit=True)
    m = q.get_matrix()
    n = len(m)
    side = (n + quiet * 2) * module
    cells = []
    for r, row in enumerate(m):
        run = None
        for c, on in enumerate(row + [False]):
            if on and run is None:
                run = c
            elif not on and run is not None:
                cells.append('<rect x="%.2f" y="%.2f" width="%.2f" height="%.2f"/>'
                             % ((run + quiet) * module, (r + quiet) * module,
                                (c - run) * module, module))
                run = None
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="%.2f" height="%.2f" '
            'viewBox="0 0 %.2f %.2f" shape-rendering="crispEdges">'
            '<rect width="%.2f" height="%.2f" fill="#fff"/><g fill="#000">%s</g>'
            '</svg>' % (side, side, side, side, side, side, "".join(cells)))


def box_qr_payload(box_no, model, grade, qty, pack_date):
    """What the pallet QR carries. Enough for a scanner to identify the box
    without a lookup, and nothing that changes after printing - no customer,
    no challan, because a box can wait months before it is dispatched."""
    return "ICONTRACE|BOX|%s|%s|%s|%d|%s" % (box_no, model, grade, qty, pack_date)


def gp_qr_payload(gp_no):
    """Identity only, same shape as box_qr_payload - the gate pass number
    resolves back to the full record by lookup; nothing that could go
    stale (party, vehicle, challan) is worth encoding twice."""
    return "ICONTRACE|GATEPASS|%s" % gp_no


def challan_qr_payload(challan_no):
    """Identity only (DECISIONS 2): the challan number looks the record up on
    the server. No party, vehicle or quantity - those can be edited (MA, MB)
    and a printed QR cannot follow them."""
    return "ICONTRACE|CHALLAN|%s" % challan_no
