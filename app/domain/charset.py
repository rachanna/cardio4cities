"""Decoding fetched text as its publisher wrote it (BD-21; code review RV-042).

A page decoded with the wrong charset garbles every accented word, so its quotes can
never match exactly and its evidence reads wrongly. The order follows the HTML standard:
a byte order mark, then the charset the server declared, then a `<meta>` declaration in
the first bytes, then UTF-8 if the bytes are valid UTF-8, then windows-1252 (the web's
default for Latin text, which ISO-8859-1 labels also mean).
"""

import codecs
import re

_BOMS = ((codecs.BOM_UTF8, "utf-8-sig"), (codecs.BOM_UTF16_LE, "utf-16"),
         (codecs.BOM_UTF16_BE, "utf-16"))  # fmt: skip
_META = re.compile(rb"""<meta[^>]{0,200}?charset\s*=\s*["']?\s*([A-Za-z0-9_.:\-]+)""", re.I)
_PARAM = re.compile(r"""charset\s*=\s*["']?\s*([A-Za-z0-9_.:\-]+)""", re.I)
META_SCAN_BYTES = 4096
# Labels the web treats as windows-1252 (WHATWG Encoding, "windows-1252" labels)
_LATIN = frozenset({"iso-8859-1", "iso8859-1", "latin1", "latin-1", "l1", "us-ascii",
                    "ascii", "cp819", "ibm819", "windows-1252", "cp1252", "x-cp1252"})  # fmt: skip


def charset_of(content_type: str | None) -> str | None:
    """The `charset` parameter of a Content-Type header, if any."""
    found = _PARAM.search(content_type or "")
    return found.group(1) if found else None


def _codec(label: str | None) -> str | None:
    if not label:
        return None
    name = label.strip().lower()
    if name in _LATIN:
        return "cp1252"
    try:
        return codecs.lookup(name).name
    except LookupError:
        return None


def decode_text(content: bytes, declared: str | None = None, html: bool = False) -> str:
    """`content` as text: never raises; undecodable bytes become U+FFFD."""
    for bom, bom_codec in _BOMS:
        if content.startswith(bom):
            return content.decode(bom_codec, errors="replace")
    codec = _codec(declared)
    if codec is None and html:
        found = _META.search(content[:META_SCAN_BYTES])
        codec = _codec(found.group(1).decode("ascii", "ignore")) if found else None
    if codec is not None:
        return content.decode(codec, errors="replace")
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return content.decode("cp1252", errors="replace")
