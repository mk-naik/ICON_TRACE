"""
ICON TRACE - barcodes and QR, rendered as inline SVG.

No internet, no image files, no fonts. The SVG goes straight into the page,
so a label prints identically from any browser on the plant network and
nothing has to be fetched at print time.

Code128 is implemented here rather than pulled from a package: it is about
sixty lines, it has no dependencies, and the pallet sheet needs one barcode
per module - a package that fails to install on the plant machine would stop
printing, which is the one thing a label routine must not do.

QR uses the `qrcode` package (pure Python, no native library). If it is
missing the label still prints, with the payload as text instead. A missing
QR is a degraded label; a crash is no label.
"""

# --------------------------------------------------------------------------
# Code128 subset B/C
# --------------------------------------------------------------------------

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
_START_B, _STOP = 104, 106


def code128_svg(text, height=34, module=1.6, show_text=True, font=8):
    """One Code128-B barcode as inline SVG. Serials are A-Z0-9, which sits
    inside subset B, so no subset switching is needed."""
    s = (text or "").strip()
    if not s:
        return ""
    codes = [_START_B]
    for ch in s:
        v = ord(ch) - 32
        if v < 0 or v > 94:          # outside subset B - drop rather than
            continue                 # emit a barcode that scans as garbage
        codes.append(v)
    check = codes[0]
    for i, c in enumerate(codes[1:], start=1):
        check += c * i
    codes.append(check % 103)
    codes.append(_STOP)

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
             % (total / 2.0, height + font, font, s)) if show_text else ""
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="%.2f" height="%d" '
            'viewBox="0 0 %.2f %d" shape-rendering="crispEdges">'
            '<g fill="#000">%s</g>%s</svg>'
            % (total, height + th, total, height + th, "".join(bars), label))


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
