"""Library behaviour LLD-2 relies on (BD-07): Protego follows RFC 9309, trafilatura keeps
main content and tables, pdfplumber gives page text and tables. Pinned here so an upgrade
that changes behaviour fails the build."""

from fpdf import FPDF

from app.adapters.fetch.robots_protego import ProtegoRobotsParser
from app.adapters.parse.documents import DocumentParser

UA = "CARDIO4CitiesResearchBot/0.1 (+https://github.com/rachanna/cardio4cities)"
BASE = "https://health.halden-bay.test"
ROBOTS = """User-agent: *
Disallow: /private
Crawl-delay: 2

User-agent: cardio4citiesresearchbot
Disallow: /reports/
Allow: /reports/annual$
Disallow: /*.xls
Allow: /p
Disallow: /p
"""


def _can(path: str, robots: str = ROBOTS, agent: str = UA) -> bool:
    return ProtegoRobotsParser().parse(robots).can_fetch(BASE + path, agent)


# --- Protego (RFC 9309) ------------------------------------------------------------------


def test_product_token_selects_our_group_case_insensitively() -> None:
    assert not _can("/reports/2024")
    assert _can("/private")  # our group replaces '*'
    assert not _can("/private", agent="OtherBot/1.0")


def test_longest_match_and_end_anchor() -> None:
    assert _can("/reports/annual")
    assert not _can("/reports/annual-2024")


def test_wildcard() -> None:
    assert not _can("/data/table.xls")


def test_allow_wins_an_equal_length_tie() -> None:
    assert _can("/p")


def test_empty_disallow_and_empty_file_allow_everything() -> None:
    assert _can("/x", "User-agent: *\nDisallow:\n")
    assert _can("/x", "")


def test_crawl_delay_per_group() -> None:
    rules = ProtegoRobotsParser().parse(ROBOTS)

    assert rules.crawl_delay("OtherBot/1.0") == 2.0
    assert rules.crawl_delay(UA) is None


# --- trafilatura ------------------------------------------------------------------------

PAGE = b"""<html><head><title>Heart health in Halden Bay</title>
<meta name="date" content="2025-02-11"></head><body>
<nav><a href="/">Home</a> | Cookie settings</nav>
<main><article><h1>Heart health in Halden Bay</h1>
<p>In Halden Bay, 31.2% of adults aged 30-79 had raised blood pressure in 2024.</p>
<table><thead><tr><th>Indicator</th><th>Women</th><th>Men</th></tr></thead>
<tbody><tr><td>Raised blood pressure</td><td>29.0%</td><td>33.5%</td></tr></tbody></table>
<p>The survey used the 140/90 mmHg threshold.</p></article></main>
<footer>Privacy policy. Subscribe to our newsletter.</footer></body></html>"""


def test_html_keeps_main_content_and_drops_boilerplate() -> None:
    doc = DocumentParser().parse_html(PAGE, BASE + "/heart")

    assert "31.2% of adults aged 30-79" in doc.text
    assert "Cookie settings" not in doc.text
    assert "newsletter" not in doc.text
    assert doc.title == "Heart health in Halden Bay"
    assert str(doc.published_date) == "2025-02-11"


def test_html_tables_keep_their_header_row() -> None:
    doc = DocumentParser().parse_html(PAGE, BASE + "/heart")

    (start, end) = doc.tables[0]
    table = doc.text[start:end]
    assert table.splitlines()[0] == "| Indicator | Women | Men |"
    assert "| Raised blood pressure | 29.0% | 33.5% |" in table


SPANNED = """<html><head><title>Districts of Norvania</title></head><body><main><article>
<h1>Hypertension care cascade by district</h1>
<p>The survey covered three districts of Norvania in 2024 and reports counts, then
percentages, for each district on two rows.</p>
<table><thead><tr><th rowspan="2">District</th><th colspan="2">Under control</th></tr>
<tr><th>n</th><th>%</th></tr></thead>
<tbody><tr><td rowspan="2">Halden Bay</td><td>412</td><td></td></tr>
<tr><td></td><td>31.5</td></tr>
<tr><td>Port Ostra</td><td>98</td><td>22.0</td></tr></tbody></table>
</article></main></body></html>"""


def _table(markup: str) -> list[str]:
    doc = DocumentParser().parse_html(markup.encode(), BASE + "/districts")
    (start, end) = doc.tables[0]
    return doc.text[start:end].splitlines()


def test_row_spanning_label_cell_is_kept_on_every_row_it_spans() -> None:
    """Spike D2-3: the percentage row must carry its district, as the source shows (BD-10)."""
    lines = _table(SPANNED)

    assert lines[0] == "| District | Under control |  |"
    assert lines[2] == "| District | n | % |"
    assert "| Halden Bay | 412 |  |" in lines
    assert "| Halden Bay |  | 31.5 |" in lines
    assert "| Port Ostra | 98 | 22.0 |" in lines


def test_spans_are_capped_so_markup_cannot_inflate_a_page() -> None:
    markup = SPANNED.replace('colspan="2"', 'colspan="100000"')
    assert len(_table(markup)[0].split("|")) < 60


# --- pdfplumber ------------------------------------------------------------------------


def _pdf() -> bytes:
    pdf = FPDF()
    pdf.set_font("Helvetica", size=11)
    pdf.add_page()
    pdf.multi_cell(0, 6, "Hypertension survey of 2,400 adults in Halden Bay, 2024.")
    with pdf.table() as table:
        for row in (("Indicator", "Women", "Men"), ("Raised blood pressure", "29.0%", "33.5%")):
            cells = table.row()
            for cell in row:
                cells.cell(cell)
    pdf.add_page()
    pdf.multi_cell(0, 6, "Annex: fieldwork methods only.")
    with pdf.table() as table:
        for annex_row in (("Team", "Days"), ("North", "12")):
            cells = table.row()
            for cell in annex_row:
                cells.cell(cell)
    return bytes(pdf.output())


def test_pdf_page_text_with_page_markers() -> None:
    doc = DocumentParser().parse_pdf(_pdf(), ["hypertension"])

    assert doc.text.startswith("[page 1]\n")
    assert [n for n, _ in doc.pages] == [1, 2]
    assert doc.text[doc.pages[1][1] :].startswith("[page 2]\n")


def test_pdf_tables_only_on_pages_with_a_keyword() -> None:
    doc = DocumentParser().parse_pdf(_pdf(), ["hypertension"])

    assert len(doc.tables) == 1
    start, end = doc.tables[0]
    assert doc.text[start:end].splitlines()[0] == "| Indicator | Women | Men |"
    assert start < doc.pages[1][1]  # on page 1


def test_pdf_without_keywords_extracts_no_tables() -> None:
    assert DocumentParser().parse_pdf(_pdf(), []).tables == []


def test_layout_box_of_prose_is_not_a_table() -> None:
    """Spike S-5: a 'table' whose cells are paragraphs stays page text only (BD-07)."""
    from app.adapters.parse.documents import is_tabular

    prose = " ".join(["The Norvania Health Directorate describes its programme in Halden Bay."] * 8)

    assert not is_tabular([[prose, None], [None, None]])
    assert not is_tabular([[prose], [prose]])
    assert not is_tabular([["Indicator", "Value"], ["Raised blood pressure", "not measured"]])
    assert is_tabular([["Indicator", "Women", "Men"], ["Raised blood pressure", "29.0%", "33.5%"]])
