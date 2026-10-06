"""RendererPort over fpdf2 (owner, BD-40): the report's HTML to PDF in pure Python, so no
system libraries are needed on Render, in CI or on Windows. The DejaVu fonts (bundled,
open licence: `fonts/LICENSE-DejaVu.txt`) cover every script a source may use. fpdf2
reads a plain subset of HTML (headings, paragraphs, lists, links, tables, bold), which
is what the report template writes."""

import asyncio
from pathlib import Path

from fpdf import FPDF, FontFace

from app.settings import Settings

FONTS = Path(__file__).resolve().parent / "fonts"
FAMILY = "DejaVu"
# Italic uses the upright faces: the report needs emphasis rarely, and two more files
# would only slant it
FACES = {"": "DejaVuSans.ttf", "B": "DejaVuSans-Bold.ttf", "I": "DejaVuSans.ttf",
         "BI": "DejaVuSans-Bold.ttf"}  # fmt: skip


INK = "#1f2937"  # headings in a dark neutral, not fpdf2's default red
MUTED = (110, 116, 125)
HEADINGS = {
    "h1": FontFace(color=INK, size_pt=20, emphasis="BOLD"),
    "h2": FontFace(color=INK, size_pt=14, emphasis="BOLD"),
    "h3": FontFace(color=INK, size_pt=11.5, emphasis="BOLD"),
    "h4": FontFace(color=INK, size_pt=10.5, emphasis="BOLD"),
}
RUNNING_TITLE = "Cardiovascular landscape brief · CARDIO4Cities"


class _Pages(FPDF):
    """A running title from page 2 and "Page n of m" on every page (D4-3)."""

    def header(self) -> None:
        if self.page_no() > 1:
            self.set_font(FAMILY, size=8)
            self.set_text_color(*MUTED)
            self.cell(0, 6, RUNNING_TITLE, align="L")
            self.ln(8)
            self.set_text_color(0, 0, 0)

    def footer(self) -> None:
        self.set_y(-12)
        self.set_font(FAMILY, size=8)
        self.set_text_color(*MUTED)
        self.cell(0, 6, f"Page {self.page_no()} of {{nb}}", align="R")
        self.set_text_color(0, 0, 0)


class Fpdf2Renderer:
    def __init__(self, font_size: float = 10.0) -> None:
        self._size = font_size

    def _render(self, html: str) -> bytes:
        pdf = _Pages(format="A4")
        pdf.set_margins(18, 18, 18)
        pdf.set_auto_page_break(auto=True, margin=18)
        for style, name in FACES.items():
            pdf.add_font(FAMILY, style, str(FONTS / name))
        pdf.set_font(FAMILY, size=self._size)
        pdf.add_page()
        pdf.write_html(
            html, font_family=FAMILY, tag_styles=HEADINGS, li_prefix_color=MUTED,
            table_line_separators=True,
        )  # fmt: skip
        return bytes(pdf.output())

    async def to_pdf(self, html: str) -> bytes:
        # Laying out pages takes a moment: off the event loop (BD-27)
        return await asyncio.to_thread(self._render, html)


def make(settings: Settings) -> Fpdf2Renderer:
    return Fpdf2Renderer()
