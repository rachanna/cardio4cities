"""Decoding fetched text (BD-21; code review RV-042). Fictional text only."""

from app.domain.charset import charset_of, decode_text

TEXT = "Prévalence à Halden Bay : 31,5 %"


def test_the_declared_charset_comes_from_the_content_type() -> None:
    assert charset_of("text/html; charset=ISO-8859-1") == "ISO-8859-1"
    assert charset_of('text/html; charset="utf-8"') == "utf-8"
    assert charset_of("text/html") is None
    assert charset_of(None) is None


def test_a_byte_order_mark_wins_over_any_declaration() -> None:
    assert decode_text(TEXT.encode("utf-16"), "iso-8859-1") == TEXT
    assert decode_text(b"\xef\xbb\xbf" + TEXT.encode(), "iso-8859-1") == TEXT


def test_the_servers_charset_wins_over_the_pages_meta() -> None:
    page = f'<meta charset="utf-8"><p>{TEXT}</p>'.encode("latin-1")
    assert TEXT in decode_text(page, "iso-8859-1", html=True)


def test_latin_labels_mean_windows_1252() -> None:
    euro = "Coût : 12 €".encode("cp1252")
    assert decode_text(euro, "iso-8859-1") == "Coût : 12 €"


def test_unknown_or_missing_labels_fall_back_to_utf8_then_windows_1252() -> None:
    assert decode_text(TEXT.encode(), "no-such-charset") == TEXT
    assert decode_text(TEXT.encode("cp1252")) == TEXT
    assert decode_text(TEXT.encode(), None, html=True) == TEXT


def test_meta_is_read_only_for_html() -> None:
    page = f'<meta charset="iso-8859-1"><p>{TEXT}</p>'.encode("latin-1")
    assert TEXT in decode_text(page, None, html=True)
    assert TEXT in decode_text(page)  # not valid UTF-8: windows-1252 anyway
