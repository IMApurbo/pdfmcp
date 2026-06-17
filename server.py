"""
VisualPDF MCP Server v5
=======================
All-in-one PDF tool with next-level graphical design capabilities.
Standard: merge, split, rotate, compress, encrypt, extract text/tables/images,
          watermark, forms, metadata, OCR, convert.
Design:   gradient backgrounds, hero sections, glassmorphism cards, shape overlays,
          typography effects, stat cards, timelines, QR codes, magazine layouts,
          cover pages, certificates, invoices, brochures, data charts, and more.

v5 improvements
---------------
* Temp files: all tools that need intermediate files use a fresh
  tempfile.TemporaryDirectory() via _tmpdir() context-manager; the entire
  directory is deleted automatically when the tool returns — no leaks.
* Text wrapping: every text-rendering path uses _wrap_text() / _draw_text_block()
  so text never gets silently cut off.
* "Work on current PDF": every tool that reads or writes a PDF accepts an empty
  string and falls back to the server-level _CURRENT_PDF, which the caller sets
  with set_current_pdf().  "By default, operate on the current PDF."
* create_new_or_modify(): convenience tool that declares a working file and
  optionally resets it, then sets it as the current PDF.
* page param: ALL design/create tools support page=int (1-based) OR
  page="append" (always add to the end).
* New tools added: create_table_page, create_chart_page, pdf_replace_page,
  pdf_crop, pdf_flatten, pdf_stamp, pdf_n_up, pdf_page_info,
  set_current_pdf, get_current_pdf, create_new_or_modify.
"""

import os
import sys
import json
import math
import logging
import tempfile
import traceback
import contextlib
from io import BytesIO
from pathlib import Path
from datetime import datetime
from typing import List, Optional

from mcp.server.fastmcp import FastMCP

from reportlab.lib.pagesizes import A4, LETTER, A3, A5
from reportlab.lib.units import mm, cm, inch
from reportlab.lib import colors
from reportlab.lib.colors import HexColor, Color
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, Image as RLImage, HRFlowable,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT, TA_JUSTIFY
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from pypdf import PdfReader, PdfWriter
from PIL import Image as PILImage, ImageFilter, ImageDraw, ImageFont
import pdfplumber
import qrcode

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_DIR  = Path(__file__).parent
LOG_FILE = LOG_DIR / "pdf_mcp.log"
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler(sys.stderr)],
)
log = logging.getLogger("visual-pdf-mcp")
log.info("=" * 60)
log.info("VisualPDF MCP Server v5 starting")
log.info(f"PID: {os.getpid()}")
log.info("=" * 60)

mcp = FastMCP("visual-pdf-mcp")

# ── Server-level state ────────────────────────────────────────────────────────
_CURRENT_PDF: str = ""   # set via set_current_pdf()

# ── Page-size lookup ──────────────────────────────────────────────────────────
PAGE_SIZES = {"a4": A4, "letter": LETTER, "a3": A3, "a5": A5}

# =============================================================================
# LOW-LEVEL HELPERS
# =============================================================================

def _page_size(name: str):
    return PAGE_SIZES.get(name.lower(), A4)

def _hex(h: str) -> HexColor:
    return HexColor(h if h.startswith("#") else f"#{h}")

def _out(path: str) -> str:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return path

def _ok(path: str, **extra) -> str:
    return json.dumps({"ok": True, "output": path, **extra})

def _err(msg: str) -> str:
    return json.dumps({"ok": False, "error": msg})

def _resolve_input(path: str) -> str:
    """Return path if non-empty, else fall back to _CURRENT_PDF."""
    if path:
        return path
    if _CURRENT_PDF:
        return _CURRENT_PDF
    raise ValueError(
        "No input PDF path provided and no current PDF is set. "
        "Call set_current_pdf() first or pass an explicit path."
    )

@contextlib.contextmanager
def _tmpdir():
    """Yield a temp directory; delete it and ALL contents on exit."""
    with tempfile.TemporaryDirectory(prefix="visualpdf_") as d:
        yield d

def _wrap_text(canvas_obj, text: str, font: str, font_size: float,
               max_width: float) -> List[str]:
    """Word-wrap *text* to fit within *max_width* points. Returns list of lines."""
    lines: List[str] = []
    for paragraph in text.split("\n"):
        if not paragraph.strip():
            lines.append("")
            continue
        words = paragraph.split()
        current = ""
        for word in words:
            test = f"{current} {word}".strip()
            if canvas_obj.stringWidth(test, font, font_size) <= max_width:
                current = test
            else:
                if current:
                    lines.append(current)
                if canvas_obj.stringWidth(word, font, font_size) > max_width:
                    lines.append(word)   # force oversized word
                    current = ""
                else:
                    current = word
        if current:
            lines.append(current)
    return lines or [""]

def _draw_text_block(c, text: str, font: str, font_size: float,
                     x: float, y: float, max_width: float,
                     line_height: float, color: str = "#000000",
                     alignment: str = "left", max_lines: int = 999) -> float:
    """
    Draw word-wrapped text starting at (x, y) going downward.
    Returns the y position *below* the last line.
    """
    c.setFillColor(_hex(color))
    c.setFont(font, font_size)
    lines = _wrap_text(c, text, font, font_size, max_width)
    for line in lines[:max_lines]:
        if not line:
            y -= line_height * 0.5
            continue
        if alignment == "center":
            c.drawCentredString(x + max_width / 2, y, line)
        elif alignment == "right":
            c.drawRightString(x + max_width, y, line)
        else:
            c.drawString(x, y, line)
        y -= line_height
    return y

def _draw_linear_gradient(c, x, y, w, h, color1: str, color2: str,
                           steps: int = 60, vertical: bool = True):
    r1, g1, b1 = _hex(color1).red, _hex(color1).green, _hex(color1).blue
    r2, g2, b2 = _hex(color2).red, _hex(color2).green, _hex(color2).blue
    for i in range(steps):
        t = i / steps
        r = r1 + (r2 - r1) * t; g = g1 + (g2 - g1) * t; b = b1 + (b2 - b1) * t
        c.setFillColorRGB(r, g, b)
        if vertical:
            sh = h / steps
            c.rect(x, y + h - (i + 1) * sh, w, sh + 1, fill=1, stroke=0)
        else:
            sw = w / steps
            c.rect(x + i * sw, y, sw + 1, h, fill=1, stroke=0)

def _draw_radial_gradient(c, cx, cy, max_r, color_inner: str,
                           color_outer: str, steps: int = 50):
    ri, gi, bi = _hex(color_inner).red, _hex(color_inner).green, _hex(color_inner).blue
    ro, go, bo = _hex(color_outer).red, _hex(color_outer).green, _hex(color_outer).blue
    for i in range(steps, 0, -1):
        t = i / steps
        r = ri + (ro - ri) * t; g = gi + (go - gi) * t; b = bi + (bo - bi) * t
        c.setFillColorRGB(r, g, b)
        c.circle(cx, cy, max_r * (i / steps), fill=1, stroke=0)

def _rounded_rect(c, x, y, w, h, radius: float = 10,
                  fill_color=None, stroke_color=None, stroke_width: float = 1):
    if fill_color:
        c.setFillColor(fill_color)
    if stroke_color:
        c.setStrokeColor(stroke_color); c.setLineWidth(stroke_width)
    p = c.beginPath()
    p.moveTo(x + radius, y)
    p.lineTo(x + w - radius, y)
    p.arcTo(x + w - 2 * radius, y, x + w, y + 2 * radius, startAng=-90, extent=90)
    p.lineTo(x + w, y + h - radius)
    p.arcTo(x + w - 2 * radius, y + h - 2 * radius, x + w, y + h, startAng=0, extent=90)
    p.lineTo(x + radius, y + h)
    p.arcTo(x, y + h - 2 * radius, x + 2 * radius, y + h, startAng=90, extent=90)
    p.lineTo(x, y + radius)
    p.arcTo(x, y, x + 2 * radius, y + 2 * radius, startAng=180, extent=90)
    p.close()
    c.drawPath(p, fill=1 if fill_color else 0, stroke=1 if stroke_color else 0)

def _blank_page_buf(pw: float, ph: float) -> BytesIO:
    buf = BytesIO()
    bc = rl_canvas.Canvas(buf, pagesize=(pw, ph))
    bc.setFillColorRGB(1, 1, 1); bc.rect(0, 0, pw, ph, fill=1, stroke=0)
    bc.save(); buf.seek(0)
    return buf

def _save_page(canvas_buf: BytesIO, output_path: str, page) -> None:
    """
    Save a single-page canvas buffer into output_path.

    page:
      int      → 1-based; create/replace that slot (pads with blanks if needed)
      "append" → always add as the last page
    """
    canvas_buf.seek(0)
    new_reader = PdfReader(canvas_buf)
    new_pg     = new_reader.pages[0]
    pw = float(new_pg.mediabox.width)
    ph = float(new_pg.mediabox.height)

    existing: list = []
    if Path(output_path).exists():
        existing = list(PdfReader(output_path).pages)

    if str(page).lower() == "append":
        existing.append(new_pg)
    else:
        idx = int(page) - 1
        while len(existing) < idx:
            existing.append(PdfReader(_blank_page_buf(pw, ph)).pages[0])
        if idx < len(existing):
            existing[idx] = new_pg
        else:
            existing.append(new_pg)

    writer = PdfWriter()
    for p in existing:
        writer.add_page(p)
    with open(_out(output_path), "wb") as f:
        writer.write(f)

# =============================================================================
# SERVER CONTROL TOOLS
# =============================================================================

@mcp.tool()
def set_current_pdf(path: str) -> str:
    """
    Set the server-level 'current PDF'.
    All tools that accept input_pdf / input_path / output_path will use this
    path when their argument is left empty.
    path: absolute path to the PDF (need not exist yet for create/output calls).
    """
    global _CURRENT_PDF
    _CURRENT_PDF = path
    log.info(f"Current PDF set to: {path}")
    return json.dumps({"ok": True, "current_pdf": path})


@mcp.tool()
def get_current_pdf() -> str:
    """Return the currently active PDF path."""
    return json.dumps({"ok": True, "current_pdf": _CURRENT_PDF})


@mcp.tool()
def create_new_or_modify(
    path: str,
    mode: str = "auto",
) -> str:
    """
    Declare the working file for subsequent tool calls and set it as the
    current PDF.

    mode:
      "auto"   – if the file exists keep it (modify); if not, it will be
                 created by the next design/create tool call.
      "new"    – delete the file if it exists, start completely fresh.
      "modify" – assert the file must already exist; returns error if missing.

    After this call, all tools that accept empty input/output paths will
    automatically use *path*.
    """
    global _CURRENT_PDF
    exists = Path(path).exists()

    if mode == "modify" and not exists:
        return _err(f"modify mode requested but file does not exist: {path}")

    if mode == "new" and exists:
        os.remove(path)
        log.info(f"create_new_or_modify: deleted existing file {path}")
        exists = False

    _CURRENT_PDF = path
    log.info(f"create_new_or_modify: current PDF → {path}  (mode={mode}, existed={exists})")
    return json.dumps({
        "ok": True,
        "current_pdf": path,
        "file_existed": exists,
        "mode_applied": mode,
    })

# =============================================================================
# DESIGN / CREATION TOOLS
# =============================================================================

@mcp.tool()
def create_gradient_page(
    output_path: str = "",
    color1: str = "#667eea",
    color2: str = "#764ba2",
    direction: str = "vertical",
    page_size: str = "a4",
    page: int = 1,
    title: str = "",
    subtitle: str = "",
    title_color: str = "#ffffff",
) -> str:
    """
    Create a PDF page with a smooth gradient background.
    output_path: leave empty to use the current PDF.
    color1/color2: hex colours e.g. '#ff6b6b'.
    direction: 'vertical' | 'horizontal' | 'radial'.
    title/subtitle: optional overlaid text (auto word-wrapped).
    page: 1-based int or 'append'.
    """
    log.info("TOOL create_gradient_page")
    try:
        out = output_path or _CURRENT_PDF
        if not out:
            return _err("output_path required (or set a current PDF first)")
        ps = _page_size(page_size); w, h = ps
        buf = BytesIO()
        c = rl_canvas.Canvas(buf, pagesize=ps)

        if direction == "radial":
            c.setFillColor(_hex(color2)); c.rect(0, 0, w, h, fill=1, stroke=0)
            _draw_radial_gradient(c, w / 2, h / 2, max(w, h) * 0.8, color1, color2)
        else:
            _draw_linear_gradient(c, 0, 0, w, h, color1, color2,
                                  vertical=(direction != "horizontal"))

        if title:
            _draw_text_block(c, title, "Helvetica-Bold", 42,
                             w * 0.06, h / 2 + 40, w * 0.88, 52,
                             title_color, alignment="center", max_lines=4)
        if subtitle:
            _draw_text_block(c, subtitle, "Helvetica", 20,
                             w * 0.06, h / 2 - 20, w * 0.88, 28,
                             title_color, alignment="center", max_lines=3)

        c.save()
        _save_page(buf, out, page)
        log.info("create_gradient_page OK")
        return _ok(out)
    except Exception as e:
        log.error(f"create_gradient_page FAILED: {e}\n{traceback.format_exc()}")
        return _err(str(e))


@mcp.tool()
def create_cover_page(
    output_path: str = "",
    title: str = "Untitled",
    subtitle: str = "",
    author: str = "",
    bg_color1: str = "#0f0c29",
    bg_color2: str = "#302b63",
    accent_color: str = "#24243e",
    text_color: str = "#ffffff",
    style: str = "diagonal",
    page_size: str = "a4",
    page: int = 1,
) -> str:
    """
    Create a stunning cover page.
    output_path: leave empty to use the current PDF.
    style: 'diagonal' | 'split' | 'centered' | 'minimal' | 'bold'.
    All text args are auto word-wrapped.
    page: 1-based int or 'append'.
    """
    log.info("TOOL create_cover_page")
    try:
        out = output_path or _CURRENT_PDF
        if not out:
            return _err("output_path required (or set a current PDF first)")
        ps = _page_size(page_size); w, h = ps
        buf = BytesIO()
        c = rl_canvas.Canvas(buf, pagesize=ps)

        _draw_linear_gradient(c, 0, 0, w, h, bg_color1, bg_color2)

        if style == "diagonal":
            p = c.beginPath()
            p.moveTo(0, h * 0.55); p.lineTo(w * 0.65, h * 0.75)
            p.lineTo(w * 0.65, h); p.lineTo(0, h); p.close()
            c.setFillColor(_hex(accent_color)); c.setFillAlpha(0.6)
            c.drawPath(p, fill=1, stroke=0); c.setFillAlpha(1)
            c.setFillColor(_hex(accent_color)); c.setFillAlpha(0.4)
            c.circle(w * 0.85, h * 0.75, 120, fill=1, stroke=0)
            c.circle(w * 0.75, h * 0.85, 70, fill=1, stroke=0)
            c.setFillAlpha(1)
            _draw_text_block(c, title, "Helvetica-Bold", 52,
                             w * 0.08, h * 0.57, w * 0.56, 62,
                             text_color, max_lines=4)
            if subtitle:
                _draw_text_block(c, subtitle, "Helvetica", 24,
                                 w * 0.08, h * 0.44, w * 0.56, 32,
                                 text_color, max_lines=3)
            if author:
                c.setFillColor(_hex(text_color)); c.setFillAlpha(0.7)
                c.setFont("Helvetica-Oblique", 16)
                c.drawString(w * 0.08, h * 0.12, f"by {author}")
                c.setFillAlpha(1)

        elif style == "split":
            _draw_linear_gradient(c, 0, 0, w * 0.45, h, accent_color, bg_color1, vertical=False)
            _draw_text_block(c, title, "Helvetica-Bold", 38,
                             w * 0.47, h * 0.60, w * 0.48, 48,
                             text_color, alignment="center", max_lines=6)
            if subtitle:
                _draw_text_block(c, subtitle, "Helvetica", 18,
                                 w * 0.47, h * 0.46, w * 0.48, 26,
                                 text_color, alignment="center", max_lines=3)

        elif style == "minimal":
            c.setStrokeColor(_hex(accent_color)); c.setLineWidth(4)
            c.line(w * 0.08, h * 0.48, w * 0.55, h * 0.48)
            _draw_text_block(c, title, "Helvetica-Bold", 52,
                             w * 0.08, h * 0.58, w * 0.84, 62,
                             text_color, max_lines=4)
            if subtitle:
                _draw_text_block(c, subtitle, "Helvetica", 22,
                                 w * 0.08, h * 0.42, w * 0.84, 30,
                                 text_color, max_lines=3)

        elif style == "bold":
            font_size = min(72, w / max(len(title), 1) * 1.4)
            _draw_text_block(c, title, "Helvetica-Bold", font_size,
                             w * 0.05, h * 0.62, w * 0.90, font_size + 10,
                             text_color, alignment="center", max_lines=4)
            c.setFillColor(_hex(accent_color))
            c.rect(w * 0.1, h * 0.52, w * 0.8, 6, fill=1, stroke=0)
            if subtitle:
                _draw_text_block(c, subtitle, "Helvetica", 24,
                                 w * 0.05, h * 0.46, w * 0.90, 32,
                                 text_color, alignment="center", max_lines=3)

        else:  # centered
            _draw_radial_gradient(c, w / 2, h / 2, max(w, h) * 0.7, accent_color, bg_color1)
            _draw_text_block(c, title, "Helvetica-Bold", 48,
                             w * 0.05, h / 2 + 55, w * 0.90, 58,
                             text_color, alignment="center", max_lines=4)
            if subtitle:
                _draw_text_block(c, subtitle, "Helvetica", 22,
                                 w * 0.05, h / 2 - 20, w * 0.90, 30,
                                 text_color, alignment="center", max_lines=3)
            if author:
                c.setFillColor(_hex(text_color)); c.setFillAlpha(0.6)
                c.setFont("Helvetica-Oblique", 15)
                c.drawCentredString(w / 2, h * 0.12, f"— {author} —")
                c.setFillAlpha(1)

        c.save()
        _save_page(buf, out, page)
        log.info("create_cover_page OK")
        return _ok(out)
    except Exception as e:
        log.error(f"create_cover_page FAILED: {e}\n{traceback.format_exc()}")
        return _err(str(e))


@mcp.tool()
def create_card_page(
    output_path: str = "",
    cards: str = "[]",
    bg_color1: str = "#1a1a2e",
    bg_color2: str = "#16213e",
    card_color: str = "#0f3460",
    accent_color: str = "#e94560",
    text_color: str = "#ffffff",
    columns: int = 2,
    page_size: str = "a4",
    page: int = 1,
) -> str:
    """
    Create a page of glassmorphism-style info cards.
    output_path: leave empty to use the current PDF.
    cards: JSON array of {'title','value','subtitle'} objects.
    columns: 1–3.
    page: 1-based int or 'append'.
    """
    log.info("TOOL create_card_page")
    try:
        out = output_path or _CURRENT_PDF
        if not out:
            return _err("output_path required (or set a current PDF first)")
        cards_data = json.loads(cards)
        ps = _page_size(page_size); w, h = ps
        buf = BytesIO()
        c = rl_canvas.Canvas(buf, pagesize=ps)

        _draw_linear_gradient(c, 0, 0, w, h, bg_color1, bg_color2)
        c.setFillColor(_hex(accent_color)); c.setFillAlpha(0.06)
        c.circle(w * 0.85, h * 0.15, 130, fill=1, stroke=0)
        c.circle(w * 0.1,  h * 0.85, 100, fill=1, stroke=0)
        c.setFillAlpha(1)

        margin = 40
        cols   = max(1, min(columns, 3))
        card_w = (w - 2 * margin - (cols - 1) * 20) / cols
        card_h = 140
        pad    = 16

        for idx, card in enumerate(cards_data):
            col = idx % cols; row = idx // cols
            cx  = margin + col * (card_w + 20)
            cy  = h - margin - 80 - row * (card_h + 20)

            c.saveState()
            c.setFillColor(_hex(card_color)); c.setFillAlpha(0.55)
            _rounded_rect(c, cx, cy, card_w, card_h, radius=14,
                          fill_color=_hex(card_color))
            c.setFillAlpha(1); c.restoreState()

            c.setFillColor(_hex(accent_color)); c.setFillAlpha(0.9)
            c.rect(cx, cy + card_h - 5, card_w, 5, fill=1, stroke=0)
            c.setFillAlpha(1)

            c.setFillColor(_hex(text_color)); c.setFont("Helvetica-Bold", 12)
            c.drawString(cx + pad, cy + card_h - 28, str(card.get("title", ""))[:42])

            c.setFont("Helvetica-Bold", 30)
            c.drawString(cx + pad, cy + card_h - 68, str(card.get("value", ""))[:18])

            _draw_text_block(c, str(card.get("subtitle", "")),
                             "Helvetica", 10,
                             cx + pad, cy + 30, card_w - 2 * pad, 14,
                             text_color, max_lines=2)

        c.save()
        _save_page(buf, out, page)
        log.info("create_card_page OK")
        return _ok(out, cards_rendered=len(cards_data))
    except Exception as e:
        log.error(f"create_card_page FAILED: {e}\n{traceback.format_exc()}")
        return _err(str(e))

@mcp.tool()
def create_hero_section(
    output_path: str = "",
    heading: str = "Your Heading Here",
    body: str = "",
    cta_text: str = "",
    bg_style: str = "gradient",
    bg_color1: str = "#fc466b",
    bg_color2: str = "#3f5efb",
    shape_color: str = "#ffffff",
    text_color: str = "#ffffff",
    page_size: str = "a4",
    page: int = 1,
) -> str:
    """
    Create a hero / landing-section page with full word-wrap.
    output_path: leave empty to use the current PDF.
    bg_style: 'gradient' | 'radial' | 'solid' | 'diagonal_split'.
    page: 1-based int or 'append'.
    """
    log.info("TOOL create_hero_section")
    try:
        out = output_path or _CURRENT_PDF
        if not out:
            return _err("output_path required (or set a current PDF first)")
        ps = _page_size(page_size); w, h = ps
        buf = BytesIO()
        c = rl_canvas.Canvas(buf, pagesize=ps)

        if bg_style == "radial":
            c.setFillColor(_hex(bg_color2)); c.rect(0, 0, w, h, fill=1, stroke=0)
            _draw_radial_gradient(c, w / 2, h * 0.6, max(w, h) * 0.85, bg_color1, bg_color2)
        elif bg_style == "solid":
            c.setFillColor(_hex(bg_color1)); c.rect(0, 0, w, h, fill=1, stroke=0)
        elif bg_style == "diagonal_split":
            c.setFillColor(_hex(bg_color2)); c.rect(0, 0, w, h, fill=1, stroke=0)
            p2 = c.beginPath()
            p2.moveTo(0, h); p2.lineTo(w, h); p2.lineTo(w, h * 0.35)
            p2.lineTo(0, h * 0.65); p2.close()
            c.setFillColor(_hex(bg_color1)); c.drawPath(p2, fill=1, stroke=0)
        else:
            _draw_linear_gradient(c, 0, 0, w, h, bg_color1, bg_color2)

        c.setStrokeColor(_hex(shape_color)); c.setStrokeAlpha(0.12); c.setLineWidth(2)
        for r in [180, 300, 420]:
            c.circle(w * 0.82, h * 0.72, r, fill=0, stroke=1)
        c.setStrokeAlpha(1)

        y = _draw_text_block(c, heading, "Helvetica-Bold", 46,
                             w * 0.06, h * 0.70, w * 0.88, 56,
                             text_color, alignment="center", max_lines=5)

        if body:
            y -= 10
            y = _draw_text_block(c, body, "Helvetica", 18,
                                 w * 0.06, y, w * 0.88, 26,
                                 text_color, alignment="center", max_lines=4)

        if cta_text:
            btn_w, btn_h = 220, 46
            bx, by = w / 2 - btn_w / 2, y - 20
            c.setFillColor(_hex(text_color)); c.setFillAlpha(0.2)
            c.roundRect(bx, by, btn_w, btn_h, btn_h / 2, fill=1, stroke=0)
            c.setFillAlpha(1)
            c.setStrokeColor(_hex(text_color)); c.setStrokeAlpha(0.7); c.setLineWidth(1.5)
            c.roundRect(bx, by, btn_w, btn_h, btn_h / 2, fill=0, stroke=1)
            c.setStrokeAlpha(1)
            c.setFillColor(_hex(text_color)); c.setFont("Helvetica-Bold", 16)
            c.drawCentredString(w / 2, by + btn_h * 0.32, cta_text)

        c.save()
        _save_page(buf, out, page)
        log.info("create_hero_section OK")
        return _ok(out)
    except Exception as e:
        log.error(f"create_hero_section FAILED: {e}\n{traceback.format_exc()}")
        return _err(str(e))


@mcp.tool()
def create_timeline_page(
    output_path: str = "",
    events: str = "[]",
    title: str = "Timeline",
    bg_color1: str = "#0a0a0a",
    bg_color2: str = "#1a1a2e",
    accent_color: str = "#7c3aed",
    text_color: str = "#ffffff",
    page_size: str = "a4",
    page: int = 1,
) -> str:
    """
    Create a vertical timeline infographic page.
    output_path: leave empty to use the current PDF.
    events: JSON array of {'year':'2020','title':'...','desc':'...'}.
    page: 1-based int or 'append'.
    """
    log.info("TOOL create_timeline_page")
    try:
        out = output_path or _CURRENT_PDF
        if not out:
            return _err("output_path required (or set a current PDF first)")
        evts = json.loads(events)
        ps = _page_size(page_size); w, h = ps
        buf = BytesIO()
        c = rl_canvas.Canvas(buf, pagesize=ps)

        _draw_linear_gradient(c, 0, 0, w, h, bg_color1, bg_color2)

        c.setFillColor(_hex(accent_color)); c.setFont("Helvetica-Bold", 32)
        c.drawCentredString(w / 2, h - 60, title)
        c.setStrokeColor(_hex(accent_color)); c.setLineWidth(2)
        c.line(w * 0.2, h - 72, w * 0.8, h - 72)

        line_x = w / 2; top_y = h - 100; bottom_y = 60
        c.setStrokeColor(_hex(accent_color)); c.setStrokeAlpha(0.4)
        c.setLineWidth(2); c.line(line_x, top_y, line_x, bottom_y)
        c.setStrokeAlpha(1)

        n = max(len(evts), 1)
        step = (top_y - bottom_y) / n

        for i, evt in enumerate(evts):
            ey = top_y - i * step - step / 2
            left = (i % 2 == 0)

            c.setFillColor(_hex(accent_color))
            c.circle(line_x, ey, 8, fill=1, stroke=0)
            c.setFillColor(_hex(bg_color1))
            c.circle(line_x, ey, 4, fill=1, stroke=0)

            c.setStrokeColor(_hex(accent_color)); c.setStrokeAlpha(0.5); c.setLineWidth(1)
            if left:
                c.line(line_x - 8, ey, line_x - 120, ey)
            else:
                c.line(line_x + 8, ey, line_x + 120, ey)
            c.setStrokeAlpha(1)

            card_w, card_h = 195, 75
            cx_c = (line_x - 140 - card_w) if left else (line_x + 140)
            cy_c = ey - card_h / 2

            c.setFillColor(_hex(accent_color)); c.setFillAlpha(0.15)
            _rounded_rect(c, cx_c, cy_c, card_w, card_h, radius=8,
                          fill_color=_hex(accent_color))
            c.setFillAlpha(1)

            c.setFillColor(_hex(accent_color))
            c.roundRect(cx_c + 8, cy_c + card_h - 26, 60, 20, 4, fill=1, stroke=0)
            c.setFillColor(_hex("#ffffff")); c.setFont("Helvetica-Bold", 11)
            c.drawString(cx_c + 12, cy_c + card_h - 20, str(evt.get("year", "")))

            c.setFillColor(_hex(text_color)); c.setFont("Helvetica-Bold", 11)
            c.drawString(cx_c + 10, cy_c + card_h - 40, evt.get("title", "")[:30])

            _draw_text_block(c, evt.get("desc", ""), "Helvetica", 8,
                             cx_c + 10, cy_c + 24, card_w - 20, 12,
                             text_color, max_lines=2)

        c.save()
        _save_page(buf, out, page)
        log.info("create_timeline_page OK")
        return _ok(out, events_rendered=len(evts))
    except Exception as e:
        log.error(f"create_timeline_page FAILED: {e}\n{traceback.format_exc()}")
        return _err(str(e))


@mcp.tool()
def create_infographic_page(
    output_path: str = "",
    title: str = "Infographic",
    stats: str = "[]",
    bg_color1: str = "#000428",
    bg_color2: str = "#004e92",
    accent_color: str = "#00d2ff",
    text_color: str = "#ffffff",
    bar_style: str = "horizontal",
    page_size: str = "a4",
    page: int = 1,
) -> str:
    """
    Create a data infographic page.
    output_path: leave empty to use the current PDF.
    stats: JSON array of {'label':'...','value':75,'max':100,'color':'#hex'}.
    bar_style: 'horizontal' | 'circular'.
    page: 1-based int or 'append'.
    """
    log.info("TOOL create_infographic_page")
    try:
        out = output_path or _CURRENT_PDF
        if not out:
            return _err("output_path required (or set a current PDF first)")
        data = json.loads(stats)
        ps = _page_size(page_size); w, h = ps
        buf = BytesIO()
        c = rl_canvas.Canvas(buf, pagesize=ps)

        _draw_linear_gradient(c, 0, 0, w, h, bg_color1, bg_color2)

        c.setFillColor(_hex(accent_color)); c.setFillAlpha(0.05)
        for gx in range(0, int(w), 30):
            for gy in range(0, int(h), 30):
                c.circle(gx, gy, 2, fill=1, stroke=0)
        c.setFillAlpha(1)

        c.setFillColor(_hex(accent_color)); c.setFont("Helvetica-Bold", 36)
        c.drawCentredString(w / 2, h - 70, title)
        c.setStrokeColor(_hex(accent_color)); c.setStrokeAlpha(0.5); c.setLineWidth(1.5)
        c.line(w * 0.15, h - 82, w * 0.85, h - 82); c.setStrokeAlpha(1)

        if bar_style == "horizontal":
            bar_area_top = h - 110
            n = len(data)
            slot = (bar_area_top - 60) / max(n, 1)
            bar_max_w = w * 0.55

            for i, d in enumerate(data):
                by    = bar_area_top - i * slot - slot * 0.5
                val   = float(d.get("value", 0))
                mx    = float(d.get("max", 100))
                pct   = min(val / mx, 1.0) if mx else 0
                bclr  = d.get("color", accent_color)

                c.setFillColor(_hex(text_color)); c.setFillAlpha(0.1)
                c.roundRect(w * 0.3, by - 10, bar_max_w, 20, 10, fill=1, stroke=0)
                c.setFillAlpha(1)

                fill_w = bar_max_w * pct
                if fill_w > 0:
                    _draw_linear_gradient(c, w * 0.3, by - 10, fill_w, 20,
                                          bclr, accent_color, vertical=False)

                c.setFillColor(_hex(text_color)); c.setFont("Helvetica-Bold", 12)
                c.drawRightString(w * 0.28, by - 5, d.get("label", ""))
                c.setFillColor(_hex(bclr)); c.setFont("Helvetica-Bold", 12)
                c.drawString(w * 0.3 + fill_w + 8, by - 5, f"{val:.0f}%")

        elif bar_style == "circular":
            n = len(data)
            cols_c = min(n, 3)
            rows_c = math.ceil(n / cols_c)
            cell_w = w / cols_c
            cell_h = (h - 140) / max(rows_c, 1)
            radius = min(cell_w, cell_h) * 0.32

            for i, d in enumerate(data):
                col = i % cols_c; row = i // cols_c
                cx  = cell_w * col + cell_w / 2
                cy  = h - 140 - row * cell_h - cell_h / 2
                val = float(d.get("value", 0))
                mx  = float(d.get("max", 100))
                pct = min(val / mx, 1.0) if mx else 0
                bclr = d.get("color", accent_color)

                c.setStrokeColor(_hex(text_color)); c.setStrokeAlpha(0.15)
                c.setLineWidth(10)
                c.arc(cx - radius, cy - radius, cx + radius, cy + radius,
                      startAng=0, extent=360)
                c.setStrokeAlpha(1)

                if pct > 0:
                    c.setStrokeColor(_hex(bclr)); c.setLineWidth(10)
                    c.arc(cx - radius, cy - radius, cx + radius, cy + radius,
                          startAng=90, extent=-(360 * pct))

                c.setFillColor(_hex(text_color)); c.setFont("Helvetica-Bold", 20)
                c.drawCentredString(cx, cy - 8, f"{val:.0f}%")
                c.setFont("Helvetica", 11); c.setFillAlpha(0.7)
                c.drawCentredString(cx, cy - radius - 18, d.get("label", ""))
                c.setFillAlpha(1)

        c.save()
        _save_page(buf, out, page)
        log.info("create_infographic_page OK")
        return _ok(out, stats_rendered=len(data))
    except Exception as e:
        log.error(f"create_infographic_page FAILED: {e}\n{traceback.format_exc()}")
        return _err(str(e))

@mcp.tool()
def create_certificate(
    output_path: str = "",
    recipient_name: str = "Recipient Name",
    certificate_title: str = "Certificate of Achievement",
    body_text: str = "",
    issuer: str = "",
    date: str = "",
    bg_color1: str = "#fff9e6",
    bg_color2: str = "#fff3cc",
    accent_color: str = "#c9a84c",
    text_color: str = "#2c2c2c",
    page_size: str = "a4",
    page: int = 1,
) -> str:
    """
    Create a formal certificate PDF with decorative borders.
    output_path: leave empty to use the current PDF.
    date: e.g. 'June 2025' — defaults to today if blank.
    page: 1-based int or 'append'.
    """
    log.info("TOOL create_certificate")
    try:
        out = output_path or _CURRENT_PDF
        if not out:
            return _err("output_path required (or set a current PDF first)")
        ps = _page_size(page_size); w, h = ps
        buf = BytesIO()
        c = rl_canvas.Canvas(buf, pagesize=ps)

        _draw_linear_gradient(c, 0, 0, w, h, bg_color1, bg_color2)

        c.setStrokeColor(_hex(accent_color)); c.setLineWidth(3)
        c.rect(24, 24, w - 48, h - 48, fill=0, stroke=1)
        c.setLineWidth(1)
        c.rect(32, 32, w - 64, h - 64, fill=0, stroke=1)

        for cx_c, cy_c in [(40, 40), (w - 40, 40), (40, h - 40), (w - 40, h - 40)]:
            c.setFillColor(_hex(accent_color)); c.circle(cx_c, cy_c, 6, fill=1, stroke=0)

        c.setFillColor(_hex(accent_color)); c.setFont("Helvetica-Bold", 13)
        c.drawCentredString(w / 2, h - 100, "✦  " + certificate_title.upper() + "  ✦")

        c.setStrokeColor(_hex(accent_color)); c.setStrokeAlpha(0.5); c.setLineWidth(1.5)
        c.line(w * 0.15, h - 112, w * 0.85, h - 112); c.setStrokeAlpha(1)

        c.setFillColor(_hex(text_color)); c.setFillAlpha(0.7)
        c.setFont("Helvetica-Oblique", 16)
        c.drawCentredString(w / 2, h - 160, "This is to certify that")
        c.setFillAlpha(1)

        c.setFillColor(_hex(text_color)); c.setFont("Helvetica-Bold", 44)
        c.drawCentredString(w / 2, h - 220, recipient_name)
        name_w = c.stringWidth(recipient_name, "Helvetica-Bold", 44)
        c.setStrokeColor(_hex(accent_color)); c.setLineWidth(2)
        c.line(w / 2 - name_w / 2, h - 230, w / 2 + name_w / 2, h - 230)

        if body_text:
            _draw_text_block(c, body_text, "Helvetica", 14,
                             w * 0.1, h - 268, w * 0.8, 20,
                             text_color, alignment="center", max_lines=4)

        dt = date or datetime.today().strftime("%B %d, %Y")
        c.setFillColor(_hex(text_color)); c.setFillAlpha(0.6)
        c.setFont("Helvetica", 12)
        c.drawString(w * 0.15, h * 0.2, f"Date: {dt}")
        if issuer:
            c.drawRightString(w * 0.85, h * 0.2, f"Issued by: {issuer}")
        c.setFillAlpha(1)

        c.setStrokeColor(_hex(text_color)); c.setStrokeAlpha(0.35); c.setLineWidth(1)
        c.line(w * 0.35, h * 0.22, w * 0.65, h * 0.22); c.setStrokeAlpha(1)
        c.setFont("Helvetica-Oblique", 10); c.setFillAlpha(0.5)
        c.drawCentredString(w / 2, h * 0.18, "Authorized Signature"); c.setFillAlpha(1)

        c.save()
        _save_page(buf, out, page)
        log.info("create_certificate OK")
        return _ok(out)
    except Exception as e:
        log.error(f"create_certificate FAILED: {e}\n{traceback.format_exc()}")
        return _err(str(e))


@mcp.tool()
def create_invoice(
    output_path: str = "",
    company_name: str = "Company Name",
    client_name: str = "Client Name",
    invoice_number: str = "001",
    items: str = "[]",
    due_date: str = "",
    logo_color: str = "#6366f1",
    bg_color: str = "#ffffff",
    accent_color: str = "#6366f1",
    page_size: str = "a4",
    page: int = 1,
) -> str:
    """
    Generate a modern styled invoice PDF.
    output_path: leave empty to use the current PDF.
    items: JSON array of {'desc':'...','qty':1,'rate':100.0}.
    page: 1-based int or 'append'.
    """
    log.info("TOOL create_invoice")
    try:
        out = output_path or _CURRENT_PDF
        if not out:
            return _err("output_path required (or set a current PDF first)")
        items_data = json.loads(items)
        ps = _page_size(page_size); w, h = ps
        buf = BytesIO()
        c = rl_canvas.Canvas(buf, pagesize=ps)

        c.setFillColor(_hex(bg_color)); c.rect(0, 0, w, h, fill=1, stroke=0)
        _draw_linear_gradient(c, 0, h - 130, w, 130, logo_color, accent_color, vertical=False)

        c.setFillColor(HexColor("#ffffff")); c.setFont("Helvetica-Bold", 28)
        c.drawString(40, h - 80, company_name)
        c.setFont("Helvetica", 13); c.setFillAlpha(0.8)
        c.drawString(40, h - 100, "INVOICE"); c.setFillAlpha(1)

        c.setFillColor(HexColor("#ffffff")); c.setFont("Helvetica-Bold", 14)
        c.drawRightString(w - 40, h - 65, f"#{invoice_number}")
        c.setFont("Helvetica", 11); c.setFillAlpha(0.8)
        dt = due_date or datetime.today().strftime("%Y-%m-%d")
        c.drawRightString(w - 40, h - 82, f"Due: {dt}")
        c.drawRightString(w - 40, h - 98, f"To: {client_name}"); c.setFillAlpha(1)

        table_top = h - 160
        c.setFillColor(_hex(accent_color))
        c.rect(40, table_top - 22, w - 80, 24, fill=1, stroke=0)
        c.setFillColor(HexColor("#ffffff")); c.setFont("Helvetica-Bold", 11)
        c.drawString(50, table_top - 16, "Description")
        c.drawRightString(w * 0.65, table_top - 16, "Qty")
        c.drawRightString(w * 0.78, table_top - 16, "Rate")
        c.drawRightString(w - 45,   table_top - 16, "Amount")

        total = 0.0; row_y = table_top - 42
        for i, item in enumerate(items_data):
            qty    = float(item.get("qty", 1))
            rate   = float(item.get("rate", 0))
            amount = qty * rate; total += amount

            if i % 2 == 0:
                c.setFillColor(_hex(accent_color)); c.setFillAlpha(0.05)
                c.rect(40, row_y - 4, w - 80, 22, fill=1, stroke=0); c.setFillAlpha(1)

            c.setFillColor(HexColor("#333333")); c.setFont("Helvetica", 11)
            desc = item.get("desc", "")
            if c.stringWidth(desc, "Helvetica", 11) > w * 0.44:
                desc = desc[:55] + "…"
            c.drawString(50, row_y + 4, desc)
            c.drawRightString(w * 0.65, row_y + 4, str(int(qty)))
            c.drawRightString(w * 0.78, row_y + 4, f"${rate:,.2f}")
            c.setFont("Helvetica-Bold", 11)
            c.drawRightString(w - 45, row_y + 4, f"${amount:,.2f}")
            row_y -= 26

        c.setFillColor(_hex(accent_color))
        c.rect(40, row_y - 8, w - 80, 28, fill=1, stroke=0)
        c.setFillColor(HexColor("#ffffff")); c.setFont("Helvetica-Bold", 13)
        c.drawString(50, row_y, "TOTAL")
        c.drawRightString(w - 45, row_y, f"${total:,.2f}")

        c.setFillColor(_hex(accent_color)); c.setFillAlpha(0.12)
        c.rect(0, 0, w, 50, fill=1, stroke=0); c.setFillAlpha(1)
        c.setFillColor(HexColor("#888888")); c.setFont("Helvetica-Oblique", 9)
        c.drawCentredString(w / 2, 20, "Thank you for your business.")

        c.save()
        _save_page(buf, out, page)
        log.info("create_invoice OK")
        return _ok(out, total=total)
    except Exception as e:
        log.error(f"create_invoice FAILED: {e}\n{traceback.format_exc()}")
        return _err(str(e))

@mcp.tool()
def create_resume(
    output_path: str = "",
    name: str = "Full Name",
    title: str = "Job Title",
    summary: str = "",
    contact: str = "",
    experience: str = "[]",
    skills: str = "[]",
    education: str = "[]",
    accent_color: str = "#2563eb",
    sidebar_color: str = "#1e3a5f",
    page_size: str = "a4",
    page: int = 1,
) -> str:
    """
    Generate a modern two-column resume PDF with full text wrapping.
    output_path: leave empty to use the current PDF.
    experience: JSON array of {'role':'...','company':'...','period':'...','desc':'...'}.
    skills: JSON array of skill strings.
    education: JSON array of {'degree':'...','school':'...','year':'...'}.
    page: 1-based int or 'append'.
    """
    log.info("TOOL create_resume")
    try:
        out = output_path or _CURRENT_PDF
        if not out:
            return _err("output_path required (or set a current PDF first)")
        exp_data    = json.loads(experience)
        skills_data = json.loads(skills)
        edu_data    = json.loads(education)
        ps = _page_size(page_size); w, h = ps
        buf = BytesIO()
        c = rl_canvas.Canvas(buf, pagesize=ps)

        sidebar_w = w * 0.32
        _draw_linear_gradient(c, 0, 0, sidebar_w, h, sidebar_color, "#0f2440", vertical=True)
        c.setFillColor(HexColor("#f8fafc"))
        c.rect(sidebar_w, 0, w - sidebar_w, h, fill=1, stroke=0)
        _draw_linear_gradient(c, sidebar_w, h - 120, w - sidebar_w, 120,
                               accent_color, "#1d4ed8", vertical=False)

        c.setFillColor(HexColor("#ffffff")); c.setFont("Helvetica-Bold", 28)
        c.drawString(sidebar_w + 24, h - 70, name)
        c.setFont("Helvetica", 14); c.setFillAlpha(0.85)
        c.drawString(sidebar_w + 24, h - 90, title); c.setFillAlpha(1)

        if contact:
            c.setFillColor(HexColor("#ffffff")); c.setFont("Helvetica", 8)
            c.setFillAlpha(0.75); c.drawString(sidebar_w + 24, h - 108, contact[:80])
            c.setFillAlpha(1)

        sy = h - 55
        c.setFillColor(HexColor("#ffffff")); c.setFont("Helvetica-Bold", 13)
        c.drawString(18, sy, "SKILLS")
        c.setStrokeColor(_hex(accent_color)); c.setLineWidth(2)
        c.line(18, sy - 8, sidebar_w - 18, sy - 8); sy -= 28
        for skill in skills_data[:16]:
            c.setFillColor(HexColor("#ffffff")); c.setFillAlpha(0.15)
            c.roundRect(16, sy - 4, sidebar_w - 32, 18, 5, fill=1, stroke=0)
            c.setFillAlpha(1); c.setFillColor(HexColor("#ffffff"))
            c.setFont("Helvetica", 10); c.drawString(22, sy, str(skill)[:35]); sy -= 24

        sy -= 18
        c.setFillColor(HexColor("#ffffff")); c.setFont("Helvetica-Bold", 13)
        c.drawString(18, sy, "EDUCATION")
        c.setStrokeColor(_hex(accent_color))
        c.line(18, sy - 8, sidebar_w - 18, sy - 8); sy -= 24
        for ed in edu_data:
            c.setFillColor(HexColor("#ffffff")); c.setFont("Helvetica-Bold", 10)
            c.drawString(18, sy, ed.get("degree", "")[:28]); sy -= 13
            c.setFont("Helvetica", 9); c.setFillAlpha(0.7)
            c.drawString(18, sy, ed.get("school", "")[:28]); sy -= 11
            c.drawString(18, sy, ed.get("year", "")); c.setFillAlpha(1); sy -= 18

        mx, my = sidebar_w + 24, h - 140
        if summary:
            c.setFillColor(HexColor("#1e293b")); c.setFont("Helvetica-Oblique", 11)
            c.drawString(mx, my, "Summary"); my -= 16
            my = _draw_text_block(c, summary, "Helvetica", 10,
                                  mx, my, w - sidebar_w - 48, 14,
                                  "#475569", max_lines=5)
            my -= 10

        c.setFillColor(HexColor("#1e293b")); c.setFont("Helvetica-Bold", 13)
        c.drawString(mx, my, "EXPERIENCE")
        c.setStrokeColor(_hex(accent_color)); c.setLineWidth(2)
        c.line(mx, my - 8, w - 24, my - 8); my -= 28

        for job in exp_data:
            c.setFillColor(_hex(accent_color)); c.setFont("Helvetica-Bold", 12)
            c.drawString(mx, my, job.get("role", ""))
            c.setFillColor(HexColor("#64748b")); c.setFont("Helvetica", 10)
            c.drawRightString(w - 24, my, job.get("period", "")); my -= 14
            c.setFillColor(HexColor("#334155")); c.setFont("Helvetica-Bold", 10)
            c.drawString(mx, my, job.get("company", "")); my -= 13
            my = _draw_text_block(c, job.get("desc", ""), "Helvetica", 9,
                                  mx + 8, my, w - sidebar_w - 50, 12,
                                  "#64748b", max_lines=4)
            my -= 8

        c.save()
        _save_page(buf, out, page)
        log.info("create_resume OK")
        return _ok(out)
    except Exception as e:
        log.error(f"create_resume FAILED: {e}\n{traceback.format_exc()}")
        return _err(str(e))


@mcp.tool()
def create_brochure_page(
    output_path: str = "",
    headline: str = "Headline",
    sections: str = "[]",
    footer_text: str = "",
    bg_color1: str = "#ffffff",
    bg_color2: str = "#f0f4ff",
    accent_color: str = "#4f46e5",
    text_color: str = "#1e1e2e",
    columns: int = 3,
    page_size: str = "a4",
    page: int = 1,
) -> str:
    """
    Create a multi-column brochure / flyer page with full text wrapping.
    output_path: leave empty to use the current PDF.
    sections: JSON array of {'title':'...','body':'...','icon':'★'}.
    columns: 1–3.
    page: 1-based int or 'append'.
    """
    log.info("TOOL create_brochure_page")
    try:
        out = output_path or _CURRENT_PDF
        if not out:
            return _err("output_path required (or set a current PDF first)")
        secs = json.loads(sections)
        ps = _page_size(page_size); w, h = ps
        buf = BytesIO()
        c = rl_canvas.Canvas(buf, pagesize=ps)

        _draw_linear_gradient(c, 0, 0, w, h, bg_color1, bg_color2)
        _draw_linear_gradient(c, 0, h - 90, w, 90, accent_color, "#818cf8", vertical=False)

        c.setFillColor(HexColor("#ffffff")); c.setFont("Helvetica-Bold", 28)
        c.drawCentredString(w / 2, h - 58, headline)

        cols    = max(1, min(columns, 3))
        margin  = 40
        col_w   = (w - 2 * margin - (cols - 1) * 20) / cols
        col_top = h - 115

        for i, sec in enumerate(secs[:cols * 4]):
            col = i % cols; row = i // cols
            cx  = margin + col * (col_w + 20)
            cy  = col_top - row * 210

            c.setFillColor(_hex(accent_color)); c.setFillAlpha(0.07)
            _rounded_rect(c, cx, cy - 180, col_w, 190, radius=12,
                          fill_color=_hex(accent_color))
            c.setFillAlpha(1)

            c.setFillColor(_hex(accent_color)); c.setFont("Helvetica-Bold", 24)
            c.drawString(cx + 16, cy - 32, sec.get("icon", "◆"))

            c.setFillColor(_hex(text_color)); c.setFont("Helvetica-Bold", 13)
            c.drawString(cx + 16, cy - 58, sec.get("title", "")[:30])

            _draw_text_block(c, sec.get("body", ""), "Helvetica", 10,
                             cx + 16, cy - 76, col_w - 32, 14,
                             text_color, max_lines=7)

        if footer_text:
            c.setFillColor(_hex(accent_color))
            c.rect(0, 0, w, 36, fill=1, stroke=0)
            c.setFillColor(HexColor("#ffffff")); c.setFont("Helvetica", 11)
            c.drawCentredString(w / 2, 13, footer_text)

        c.save()
        _save_page(buf, out, page)
        log.info("create_brochure_page OK")
        return _ok(out)
    except Exception as e:
        log.error(f"create_brochure_page FAILED: {e}\n{traceback.format_exc()}")
        return _err(str(e))


@mcp.tool()
def create_text_page(
    output_path: str = "",
    content: str = "",
    font_size: int = 12,
    font: str = "Helvetica",
    text_color: str = "#1e1e1e",
    bg_color: str = "#ffffff",
    alignment: str = "left",
    title: str = "",
    title_color: str = "#111111",
    line_spacing: float = 1.4,
    margin: int = 60,
    page_size: str = "a4",
    page: int = 1,
) -> str:
    """
    Create a clean typography-focused text page with robust word-wrap.
    output_path: leave empty to use the current PDF.
    font: 'Helvetica'|'Helvetica-Bold'|'Times-Roman'|'Courier'.
    alignment: 'left'|'center'|'right'.
    content: multi-line supported; use \\n for line breaks.
    page: 1-based int or 'append'.
    """
    log.info("TOOL create_text_page")
    try:
        out = output_path or _CURRENT_PDF
        if not out:
            return _err("output_path required (or set a current PDF first)")
        ps = _page_size(page_size); w, h = ps
        buf = BytesIO()
        c = rl_canvas.Canvas(buf, pagesize=ps)

        c.setFillColor(_hex(bg_color)); c.rect(0, 0, w, h, fill=1, stroke=0)
        y = h - margin

        if title:
            c.setFillColor(_hex(title_color)); c.setFont("Helvetica-Bold", font_size + 14)
            c.drawString(margin, y, title)
            y -= (font_size + 14) * 1.8
            c.setStrokeColor(_hex(text_color)); c.setStrokeAlpha(0.2); c.setLineWidth(1)
            c.line(margin, y + 8, w - margin, y + 8); c.setStrokeAlpha(1)
            y -= 16

        _draw_text_block(c, content, font, font_size,
                         margin, y, w - 2 * margin, font_size * line_spacing,
                         text_color, alignment=alignment)

        c.save()
        _save_page(buf, out, page)
        log.info("create_text_page OK")
        return _ok(out)
    except Exception as e:
        log.error(f"create_text_page FAILED: {e}\n{traceback.format_exc()}")
        return _err(str(e))

@mcp.tool()
def create_table_page(
    output_path: str = "",
    title: str = "Table",
    headers: str = "[]",
    rows: str = "[]",
    bg_color: str = "#ffffff",
    header_color: str = "#4f46e5",
    accent_color: str = "#e0e7ff",
    text_color: str = "#1e1e2e",
    page_size: str = "a4",
    page: int = 1,
) -> str:
    """
    Create a clean data table page.
    output_path: leave empty to use the current PDF.
    headers: JSON array of column header strings e.g. '["Name","Score","Grade"]'.
    rows: JSON array of arrays e.g. '[["Alice",95,"A"],["Bob",82,"B"]]'.
    Cells too wide are auto-truncated with an ellipsis.
    page: 1-based int or 'append'.
    """
    log.info("TOOL create_table_page")
    try:
        out = output_path or _CURRENT_PDF
        if not out:
            return _err("output_path required (or set a current PDF first)")
        hdr_list = json.loads(headers)
        row_list  = json.loads(rows)
        if not hdr_list:
            return _err("headers must not be empty")
        ps = _page_size(page_size); w, h = ps
        buf = BytesIO()
        c = rl_canvas.Canvas(buf, pagesize=ps)

        c.setFillColor(_hex(bg_color)); c.rect(0, 0, w, h, fill=1, stroke=0)

        margin = 40; y = h - 60
        if title:
            c.setFillColor(_hex(header_color)); c.setFont("Helvetica-Bold", 24)
            c.drawString(margin, y, title); y -= 36

        n_cols = len(hdr_list)
        col_w  = (w - 2 * margin) / n_cols
        row_h  = 22

        c.setFillColor(_hex(header_color))
        c.rect(margin, y - row_h, w - 2 * margin, row_h, fill=1, stroke=0)
        c.setFillColor(HexColor("#ffffff")); c.setFont("Helvetica-Bold", 11)
        for ci, hdr in enumerate(hdr_list):
            c.drawString(margin + ci * col_w + 8, y - row_h + 6, str(hdr)[:30])
        y -= row_h

        rendered = 0
        for ri, row in enumerate(row_list):
            if y < 50:
                break
            if ri % 2 == 0:
                c.setFillColor(_hex(accent_color))
                c.rect(margin, y - row_h, w - 2 * margin, row_h, fill=1, stroke=0)
            c.setFillColor(_hex(text_color)); c.setFont("Helvetica", 10)
            for ci, cell in enumerate(list(row)[:n_cols]):
                txt      = str(cell)
                max_cell = col_w - 16
                if c.stringWidth(txt, "Helvetica", 10) > max_cell:
                    while txt and c.stringWidth(txt + "…", "Helvetica", 10) > max_cell:
                        txt = txt[:-1]
                    txt += "…"
                c.drawString(margin + ci * col_w + 8, y - row_h + 6, txt)
            c.setStrokeColor(_hex(header_color)); c.setStrokeAlpha(0.15); c.setLineWidth(0.5)
            c.line(margin, y - row_h, w - margin, y - row_h); c.setStrokeAlpha(1)
            y -= row_h; rendered += 1

        c.save()
        _save_page(buf, out, page)
        log.info("create_table_page OK")
        return _ok(out, rows_rendered=rendered)
    except Exception as e:
        log.error(f"create_table_page FAILED: {e}\n{traceback.format_exc()}")
        return _err(str(e))


@mcp.tool()
def create_chart_page(
    output_path: str = "",
    title: str = "Chart",
    chart_type: str = "bar",
    data: str = "[]",
    bg_color1: str = "#0f172a",
    bg_color2: str = "#1e293b",
    accent_color: str = "#38bdf8",
    text_color: str = "#ffffff",
    page_size: str = "a4",
    page: int = 1,
) -> str:
    """
    Create a bar or line chart page.
    output_path: leave empty to use the current PDF.
    chart_type: 'bar' | 'line'.
    data: JSON array of {'label':'Jan','value':120,'color':'#hex'} objects.
    page: 1-based int or 'append'.
    """
    log.info("TOOL create_chart_page")
    try:
        out = output_path or _CURRENT_PDF
        if not out:
            return _err("output_path required (or set a current PDF first)")
        pts = json.loads(data)
        ps  = _page_size(page_size); w, h = ps
        buf = BytesIO()
        c = rl_canvas.Canvas(buf, pagesize=ps)

        _draw_linear_gradient(c, 0, 0, w, h, bg_color1, bg_color2)
        c.setFillColor(_hex(accent_color)); c.setFont("Helvetica-Bold", 28)
        c.drawCentredString(w / 2, h - 60, title)

        if not pts:
            c.save(); _save_page(buf, out, page); return _ok(out, data_points=0)

        margin  = 60
        chart_x = margin + 30
        chart_y = 80
        chart_w = w - chart_x - margin
        chart_h = h - 160
        max_val = max(float(d.get("value", 0)) for d in pts) or 1

        n_grid = 5
        for gi in range(n_grid + 1):
            gy = chart_y + chart_h * gi / n_grid
            c.setStrokeColor(_hex(text_color)); c.setStrokeAlpha(0.12); c.setLineWidth(0.5)
            c.line(chart_x, gy, chart_x + chart_w, gy); c.setStrokeAlpha(1)
            grid_val = max_val * (n_grid - gi) / n_grid
            c.setFillColor(_hex(text_color)); c.setFont("Helvetica", 8)
            c.drawRightString(chart_x - 4, gy - 4, f"{grid_val:.0f}")

        c.setStrokeColor(_hex(text_color)); c.setStrokeAlpha(0.5); c.setLineWidth(1.5)
        c.line(chart_x, chart_y, chart_x, chart_y + chart_h)
        c.line(chart_x, chart_y, chart_x + chart_w, chart_y)
        c.setStrokeAlpha(1)

        n = len(pts); bar_w = chart_w / n * 0.6; gap = chart_w / n

        if chart_type == "bar":
            for i, d in enumerate(pts):
                val  = float(d.get("value", 0))
                bh   = chart_h * val / max_val
                bx   = chart_x + i * gap + gap * 0.2
                bclr = d.get("color", accent_color)
                _draw_linear_gradient(c, bx, chart_y, bar_w, bh, bclr, accent_color)
                c.setFillColor(_hex(text_color)); c.setFont("Helvetica-Bold", 9)
                c.drawCentredString(bx + bar_w / 2, chart_y + bh + 4, f"{val:.0f}")
                c.setFont("Helvetica", 8)
                lbl = d.get("label", "")
                if c.stringWidth(lbl, "Helvetica", 8) > gap:
                    lbl = lbl[:int(gap / 5)] + "…"
                c.drawCentredString(bx + bar_w / 2, chart_y - 14, lbl)
        else:
            points_xy = []
            for i, d in enumerate(pts):
                val = float(d.get("value", 0))
                px  = chart_x + i * gap + gap / 2
                py  = chart_y + chart_h * val / max_val
                points_xy.append((px, py))
                c.setFillColor(_hex(text_color)); c.setFont("Helvetica", 8)
                lbl = d.get("label", "")
                if c.stringWidth(lbl, "Helvetica", 8) > gap:
                    lbl = lbl[:int(gap / 5)] + "…"
                c.drawCentredString(px, chart_y - 14, lbl)

            if len(points_xy) > 1:
                c.setStrokeColor(_hex(accent_color)); c.setLineWidth(2.5)
                path = c.beginPath(); path.moveTo(*points_xy[0])
                for pt in points_xy[1:]: path.lineTo(*pt)
                c.drawPath(path, stroke=1, fill=0)

            for px, py in points_xy:
                c.setFillColor(_hex(accent_color)); c.circle(px, py, 5, fill=1, stroke=0)
                c.setFillColor(_hex(text_color)); c.setFont("Helvetica-Bold", 9)
                c.drawCentredString(px, py + 8, f"{pts[points_xy.index((px,py))].get('value',0):.0f}")

        c.save()
        _save_page(buf, out, page)
        log.info("create_chart_page OK")
        return _ok(out, data_points=len(pts))
    except Exception as e:
        log.error(f"create_chart_page FAILED: {e}\n{traceback.format_exc()}")
        return _err(str(e))


@mcp.tool()
def add_geometric_background(
    output_path: str = "",
    input_pdf: str = "",
    pattern: str = "hexagons",
    bg_color: str = "#0d1117",
    shape_color: str = "#30363d",
    accent_color: str = "#58a6ff",
    page_size: str = "a4",
    overlay_on_existing: bool = False,
    page: int = 1,
) -> str:
    """
    Create or overlay a geometric pattern background page.
    output_path / input_pdf: leave empty to use the current PDF.
    pattern: 'hexagons'|'triangles'|'dots'|'lines'|'waves'|'circuit'.
    overlay_on_existing: if True, merges the pattern onto every page of input_pdf.
    page: 1-based int or 'append' (only used when overlay_on_existing=False).
    """
    log.info("TOOL add_geometric_background")
    try:
        out = output_path or _CURRENT_PDF
        if not out:
            return _err("output_path required (or set a current PDF first)")
        ps = _page_size(page_size); w, h = ps
        buf = BytesIO()
        c = rl_canvas.Canvas(buf, pagesize=ps)

        c.setFillColor(_hex(bg_color)); c.rect(0, 0, w, h, fill=1, stroke=0)
        c.setStrokeColor(_hex(shape_color)); c.setLineWidth(0.8)

        if pattern == "hexagons":
            r = 28; dx, dy = r * 1.732, r * 1.5
            for col in range(-1, int(w / dx) + 2):
                for row in range(-1, int(h / dy) + 2):
                    cx_h = col * dx + (r * 0.866 if row % 2 else 0)
                    cy_h = row * dy
                    pts = [(cx_h + r * math.cos(math.radians(60 * k + 30)),
                            cy_h + r * math.sin(math.radians(60 * k + 30))) for k in range(6)]
                    p = c.beginPath(); p.moveTo(*pts[0])
                    for pt in pts[1:]: p.lineTo(*pt)
                    p.close(); c.drawPath(p, fill=0, stroke=1)

        elif pattern == "triangles":
            sz = 40
            for row in range(-1, int(h / sz) + 2):
                for col in range(-1, int(w / sz) + 2):
                    bx, by = col * sz, row * sz
                    p = c.beginPath()
                    if (col + row) % 2 == 0:
                        p.moveTo(bx, by); p.lineTo(bx + sz, by); p.lineTo(bx, by + sz)
                    else:
                        p.moveTo(bx + sz, by); p.lineTo(bx + sz, by + sz); p.lineTo(bx, by + sz)
                    p.close(); c.drawPath(p, fill=0, stroke=1)

        elif pattern == "dots":
            spacing = 22; c.setFillColor(_hex(shape_color))
            for gx in range(0, int(w), spacing):
                for gy in range(0, int(h), spacing):
                    c.circle(gx, gy, 1.5, fill=1, stroke=0)
            import random; random.seed(42)
            c.setFillColor(_hex(accent_color))
            for _ in range(20):
                c.circle(random.randint(0, int(w)), random.randint(0, int(h)), 3.5, fill=1, stroke=0)

        elif pattern == "lines":
            spacing = 18; c.setStrokeColor(_hex(shape_color)); c.setLineWidth(0.5)
            for gy in range(0, int(h), spacing): c.line(0, gy, w, gy)
            c.setStrokeColor(_hex(accent_color)); c.setStrokeAlpha(0.3)
            for gx in range(0, int(w), spacing * 4): c.line(gx, 0, gx, h)
            c.setStrokeAlpha(1)

        elif pattern == "waves":
            amplitude = 15; freq = w / 3
            for row in range(-1, int(h / 30) + 2):
                base_y = row * 30
                p = c.beginPath(); p.moveTo(0, base_y)
                for px in range(0, int(w), 4):
                    p.lineTo(px, base_y + amplitude * math.sin(2 * math.pi * px / freq))
                c.drawPath(p, fill=0, stroke=1)

        elif pattern == "circuit":
            import random; random.seed(99)
            c.setStrokeColor(_hex(shape_color)); c.setLineWidth(0.8)
            for _ in range(60):
                sx = random.randint(0, int(w)); sy = random.randint(0, int(h))
                for _ in range(random.randint(2, 5)):
                    ex = sx + random.choice([-1, 0, 1]) * random.randint(20, 80)
                    ey = sy + random.choice([-1, 0, 1]) * random.randint(20, 80)
                    c.line(sx, sy, ex, ey)
                    c.setFillColor(_hex(accent_color)); c.setFillAlpha(0.5)
                    c.circle(ex, ey, 3, fill=1, stroke=0); c.setFillAlpha(1)
                    sx, sy = ex, ey

        c.save(); buf.seek(0)

        if overlay_on_existing:
            inp = _resolve_input(input_pdf)
            bg_reader  = PdfReader(buf)
            doc_reader = PdfReader(inp)
            writer = PdfWriter()
            for pg in doc_reader.pages:
                pg.merge_page(bg_reader.pages[0]); writer.add_page(pg)
            with open(_out(out), "wb") as f:
                writer.write(f)
        else:
            _save_page(buf, out, page)

        log.info("add_geometric_background OK")
        return _ok(out, pattern=pattern)
    except Exception as e:
        log.error(f"add_geometric_background FAILED: {e}\n{traceback.format_exc()}")
        return _err(str(e))

# =============================================================================
# OVERLAY TOOLS  (temp files auto-deleted via _tmpdir)
# =============================================================================

@mcp.tool()
def add_qr_code(
    output_path: str = "",
    input_pdf: str = "",
    url: str = "https://example.com",
    page_number: int = 1,
    x: float = 460,
    y: float = 30,
    size: float = 80,
    label: str = "",
) -> str:
    """
    Embed a QR code onto a page of an existing PDF.
    output_path / input_pdf: leave empty to use the current PDF.
    Temp image file is deleted automatically after the call.
    """
    log.info("TOOL add_qr_code")
    try:
        inp = _resolve_input(input_pdf)
        out = output_path or _CURRENT_PDF or inp
        with _tmpdir() as td:
            qr_path = str(Path(td) / "qr.png")
            qr = qrcode.QRCode(box_size=10, border=2)
            qr.add_data(url); qr.make(fit=True)
            qr.make_image(fill_color="black", back_color="white").save(qr_path)

            reader = PdfReader(inp)
            pg = reader.pages[page_number - 1]
            pw, ph = float(pg.mediabox.width), float(pg.mediabox.height)

            ol_buf = BytesIO()
            oc = rl_canvas.Canvas(ol_buf, pagesize=(pw, ph))
            oc.drawImage(qr_path, x, y, width=size, height=size)
            if label:
                oc.setFont("Helvetica", 7)
                oc.drawCentredString(x + size / 2, y - 10, label)
            oc.save(); ol_buf.seek(0)

            ol_reader = PdfReader(ol_buf)
            writer = PdfWriter()
            for i, p2 in enumerate(reader.pages):
                if i == page_number - 1:
                    p2.merge_page(ol_reader.pages[0])
                writer.add_page(p2)
            with open(_out(out), "wb") as f:
                writer.write(f)
        # _tmpdir exited → temp dir + qr.png deleted automatically
        log.info("add_qr_code OK")
        return _ok(out, qr_url=url)
    except Exception as e:
        log.error(f"add_qr_code FAILED: {e}\n{traceback.format_exc()}")
        return _err(str(e))


@mcp.tool()
def add_watermark(
    output_path: str = "",
    input_pdf: str = "",
    watermark_text: str = "CONFIDENTIAL",
    color: str = "#cccccc",
    opacity: float = 0.18,
    angle: float = 45.0,
    font_size: int = 60,
) -> str:
    """
    Add a diagonal text watermark to every page of a PDF.
    output_path / input_pdf: leave empty to use the current PDF.
    opacity: 0.0 (invisible) → 1.0 (fully opaque).
    """
    log.info("TOOL add_watermark")
    try:
        inp = _resolve_input(input_pdf)
        out = output_path or _CURRENT_PDF or inp
        reader = PdfReader(inp); writer = PdfWriter()
        for pg in reader.pages:
            pw, ph = float(pg.mediabox.width), float(pg.mediabox.height)
            wm_buf = BytesIO()
            c = rl_canvas.Canvas(wm_buf, pagesize=(pw, ph))
            c.saveState()
            c.setFillColor(_hex(color)); c.setFillAlpha(opacity)
            c.setFont("Helvetica-Bold", font_size)
            c.translate(pw / 2, ph / 2); c.rotate(angle)
            c.drawCentredString(0, 0, watermark_text)
            c.restoreState(); c.save()
            wm_buf.seek(0)
            pg.merge_page(PdfReader(wm_buf).pages[0])
            writer.add_page(pg)
        with open(_out(out), "wb") as f:
            writer.write(f)
        log.info("add_watermark OK")
        return _ok(out, pages=len(reader.pages))
    except Exception as e:
        log.error(f"add_watermark FAILED: {e}\n{traceback.format_exc()}")
        return _err(str(e))


@mcp.tool()
def add_page_numbers(
    output_path: str = "",
    input_pdf: str = "",
    style: str = "centered",
    color: str = "#666666",
    font_size: int = 10,
    prefix: str = "",
    start_number: int = 1,
) -> str:
    """
    Add page numbers to every page of a PDF.
    output_path / input_pdf: leave empty to use the current PDF.
    style: 'centered'|'right'|'left'|'footer_bar'.
    prefix: e.g. 'Page ' → 'Page 1'.
    """
    log.info("TOOL add_page_numbers")
    try:
        inp = _resolve_input(input_pdf)
        out = output_path or _CURRENT_PDF or inp
        reader = PdfReader(inp); writer = PdfWriter()
        for i, pg in enumerate(reader.pages):
            pw, ph = float(pg.mediabox.width), float(pg.mediabox.height)
            label = f"{prefix}{i + start_number}"
            nb_buf = BytesIO()
            c = rl_canvas.Canvas(nb_buf, pagesize=(pw, ph))
            if style == "footer_bar":
                c.setFillColor(_hex(color)); c.setFillAlpha(0.08)
                c.rect(0, 0, pw, 28, fill=1, stroke=0); c.setFillAlpha(1)
            c.setFillColor(_hex(color)); c.setFont("Helvetica", font_size)
            y_pos = 14
            if style in ("centered", "footer_bar"):
                c.drawCentredString(pw / 2, y_pos, label)
            elif style == "right":
                c.drawRightString(pw - 30, y_pos, label)
            else:
                c.drawString(30, y_pos, label)
            c.save(); nb_buf.seek(0)
            pg.merge_page(PdfReader(nb_buf).pages[0])
            writer.add_page(pg)
        with open(_out(out), "wb") as f:
            writer.write(f)
        log.info("add_page_numbers OK")
        return _ok(out, pages=len(reader.pages))
    except Exception as e:
        log.error(f"add_page_numbers FAILED: {e}\n{traceback.format_exc()}")
        return _err(str(e))


@mcp.tool()
def pdf_stamp(
    output_path: str = "",
    input_pdf: str = "",
    stamp_text: str = "APPROVED",
    color: str = "#009900",
    opacity: float = 0.55,
    page_number: int = 1,
    x: float = -1.0,
    y: float = -1.0,
    font_size: int = 48,
    border: bool = True,
) -> str:
    """
    Add a stamp (APPROVED / REJECTED / DRAFT etc.) to one page of a PDF.
    output_path / input_pdf: leave empty to use the current PDF.
    x, y: position in points; -1 = auto-centre.
    border: draw a rectangle border around the stamp.
    """
    log.info("TOOL pdf_stamp")
    try:
        inp = _resolve_input(input_pdf)
        out = output_path or _CURRENT_PDF or inp
        reader = PdfReader(inp); writer = PdfWriter()
        for i, pg in enumerate(reader.pages):
            if i == page_number - 1:
                pw, ph = float(pg.mediabox.width), float(pg.mediabox.height)
                st_buf = BytesIO()
                c = rl_canvas.Canvas(st_buf, pagesize=(pw, ph))
                c.saveState()
                c.setFillColor(_hex(color)); c.setFillAlpha(opacity)
                c.setFont("Helvetica-Bold", font_size)
                tw = c.stringWidth(stamp_text, "Helvetica-Bold", font_size)
                sx = (pw - tw) / 2 if x < 0 else x
                sy = (ph - font_size) / 2 if y < 0 else y
                if border:
                    pad = 12
                    c.setStrokeColor(_hex(color)); c.setStrokeAlpha(opacity)
                    c.setLineWidth(3)
                    c.roundRect(sx - pad, sy - pad / 2, tw + 2 * pad,
                                font_size + pad, 6, fill=0, stroke=1)
                c.drawString(sx, sy, stamp_text)
                c.restoreState(); c.save()
                st_buf.seek(0)
                pg.merge_page(PdfReader(st_buf).pages[0])
            writer.add_page(pg)
        with open(_out(out), "wb") as f:
            writer.write(f)
        log.info("pdf_stamp OK")
        return _ok(out, stamped_page=page_number)
    except Exception as e:
        log.error(f"pdf_stamp FAILED: {e}\n{traceback.format_exc()}")
        return _err(str(e))


@mcp.tool()
def pdf_add_header_footer(
    output_path: str = "",
    input_path: str = "",
    header: str = "",
    footer: str = "",
    color: str = "#333333",
    font_size: int = 9,
) -> str:
    """
    Add a text header and/or footer to every page of a PDF.
    output_path / input_path: leave empty to use the current PDF.
    Use {page} in header/footer text to insert the current page number.
    """
    log.info("TOOL pdf_add_header_footer")
    try:
        inp = _resolve_input(input_path)
        out = output_path or _CURRENT_PDF or inp
        reader = PdfReader(inp); writer = PdfWriter()
        for i, pg in enumerate(reader.pages):
            pw, ph = float(pg.mediabox.width), float(pg.mediabox.height)
            hf_buf = BytesIO()
            c = rl_canvas.Canvas(hf_buf, pagesize=(pw, ph))
            c.setFillColor(_hex(color)); c.setFont("Helvetica", font_size)
            pg_label = str(i + 1)
            if header:
                c.drawCentredString(pw / 2, ph - 20, header.replace("{page}", pg_label))
            if footer:
                c.drawCentredString(pw / 2, 12, footer.replace("{page}", pg_label))
            c.save(); hf_buf.seek(0)
            pg.merge_page(PdfReader(hf_buf).pages[0])
            writer.add_page(pg)
        with open(_out(out), "wb") as f:
            writer.write(f)
        log.info("pdf_add_header_footer OK")
        return _ok(out, pages=len(reader.pages))
    except Exception as e:
        log.error(f"pdf_add_header_footer FAILED: {e}\n{traceback.format_exc()}")
        return _err(str(e))


@mcp.tool()
def pdf_add_image_to_page(
    output_path: str = "",
    input_pdf: str = "",
    image_path: str = "",
    page_number: int = 1,
    x: float = 50,
    y: float = 50,
    width: float = 200,
    height: float = 150,
) -> str:
    """
    Embed an image onto a specific page of an existing PDF.
    output_path / input_pdf: leave empty to use the current PDF.
    x, y: position in points from bottom-left. width/height in points.
    """
    log.info("TOOL pdf_add_image_to_page")
    try:
        inp = _resolve_input(input_pdf)
        out = output_path or _CURRENT_PDF or inp
        reader = PdfReader(inp); writer = PdfWriter()
        for i, pg in enumerate(reader.pages):
            if i == page_number - 1:
                pw, ph = float(pg.mediabox.width), float(pg.mediabox.height)
                ol_buf = BytesIO()
                c = rl_canvas.Canvas(ol_buf, pagesize=(pw, ph))
                c.drawImage(image_path, x, y, width=width, height=height)
                c.save(); ol_buf.seek(0)
                pg.merge_page(PdfReader(ol_buf).pages[0])
            writer.add_page(pg)
        with open(_out(out), "wb") as f:
            writer.write(f)
        log.info("pdf_add_image_to_page OK")
        return _ok(out)
    except Exception as e:
        log.error(f"pdf_add_image_to_page FAILED: {e}\n{traceback.format_exc()}")
        return _err(str(e))


@mcp.tool()
def pdf_add_text_annotation(
    output_path: str = "",
    input_pdf: str = "",
    text: str = "",
    page_number: int = 1,
    x: float = 100,
    y: float = 100,
    color: str = "#e63946",
    font_size: int = 12,
    font: str = "Helvetica-Bold",
    rotation: float = 0.0,
    max_width: float = 0,
) -> str:
    """
    Overlay text onto a specific position on a PDF page.
    output_path / input_pdf: leave empty to use the current PDF.
    max_width: if > 0, word-wrap text within this width in points.
    rotation: degrees counter-clockwise.
    """
    log.info("TOOL pdf_add_text_annotation")
    try:
        inp = _resolve_input(input_pdf)
        out = output_path or _CURRENT_PDF or inp
        reader = PdfReader(inp); writer = PdfWriter()
        for i, pg in enumerate(reader.pages):
            if i == page_number - 1:
                pw, ph = float(pg.mediabox.width), float(pg.mediabox.height)
                ann_buf = BytesIO()
                c = rl_canvas.Canvas(ann_buf, pagesize=(pw, ph))
                c.setFillColor(_hex(color)); c.setFont(font, font_size)
                c.saveState(); c.translate(x, y); c.rotate(rotation)
                if max_width > 0:
                    _draw_text_block(c, text, font, font_size,
                                     0, 0, max_width, font_size * 1.4, color)
                else:
                    c.drawString(0, 0, text)
                c.restoreState(); c.save()
                ann_buf.seek(0)
                pg.merge_page(PdfReader(ann_buf).pages[0])
            writer.add_page(pg)
        with open(_out(out), "wb") as f:
            writer.write(f)
        log.info("pdf_add_text_annotation OK")
        return _ok(out)
    except Exception as e:
        log.error(f"pdf_add_text_annotation FAILED: {e}\n{traceback.format_exc()}")
        return _err(str(e))

# =============================================================================
# STANDARD PDF OPERATIONS
# =============================================================================

@mcp.tool()
def pdf_merge(
    output_path: str,
    input_paths: str,
) -> str:
    """
    Merge multiple PDF files into one.
    input_paths: JSON array of file paths e.g. '["/a.pdf","/b.pdf"]'.
    output_path is required.
    """
    log.info(f"TOOL pdf_merge → {output_path}")
    try:
        paths = json.loads(input_paths)
        writer = PdfWriter(); total = 0
        for p in paths:
            reader = PdfReader(p)
            for pg in reader.pages: writer.add_page(pg)
            total += len(reader.pages)
        with open(_out(output_path), "wb") as f:
            writer.write(f)
        log.info("pdf_merge OK")
        return _ok(output_path, total_pages=total, files_merged=len(paths))
    except Exception as e:
        log.error(f"pdf_merge FAILED: {e}")
        return _err(str(e))


@mcp.tool()
def pdf_append_page(
    base_pdf: str = "",
    page_pdf: str = "",
    output_path: str = "",
) -> str:
    """
    Append all pages from page_pdf onto base_pdf, write to output_path.
    All paths: leave empty to use the current PDF.
    """
    log.info("TOOL pdf_append_page")
    try:
        b   = _resolve_input(base_pdf)
        p   = _resolve_input(page_pdf) if page_pdf else b
        out = output_path or _CURRENT_PDF or b
        writer = PdfWriter()
        for path in [b, p]:
            for pg in PdfReader(path).pages: writer.add_page(pg)
        with open(_out(out), "wb") as f:
            writer.write(f)
        total = len(PdfReader(b).pages) + len(PdfReader(p).pages)
        log.info("pdf_append_page OK")
        return _ok(out, total_pages=total)
    except Exception as e:
        log.error(f"pdf_append_page FAILED: {e}")
        return _err(str(e))


@mcp.tool()
def pdf_split(
    input_path: str = "",
    output_dir: str = "",
    prefix: str = "page",
) -> str:
    """
    Split a PDF into individual single-page files.
    input_path: leave empty to use the current PDF.
    output_dir: defaults to a 'split_pages' subfolder next to the input.
    """
    log.info("TOOL pdf_split")
    try:
        inp = _resolve_input(input_path)
        if not output_dir:
            output_dir = str(Path(inp).parent / "split_pages")
        reader = PdfReader(inp)
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        outputs = []
        for i, pg in enumerate(reader.pages):
            writer = PdfWriter(); writer.add_page(pg)
            out = str(Path(output_dir) / f"{prefix}_{i+1}.pdf")
            with open(out, "wb") as f: writer.write(f)
            outputs.append(out)
        log.info("pdf_split OK")
        return json.dumps({"ok": True, "pages": outputs, "count": len(outputs)})
    except Exception as e:
        log.error(f"pdf_split FAILED: {e}")
        return _err(str(e))


@mcp.tool()
def pdf_split_range(
    output_path: str,
    input_path: str = "",
    start_page: int = 1,
    end_page: int = 1,
) -> str:
    """
    Extract a page range (1-indexed inclusive) from a PDF.
    input_path: leave empty to use the current PDF.
    """
    log.info(f"TOOL pdf_split_range {start_page}-{end_page}")
    try:
        inp = _resolve_input(input_path)
        reader = PdfReader(inp); writer = PdfWriter()
        for i in range(start_page - 1, min(end_page, len(reader.pages))):
            writer.add_page(reader.pages[i])
        with open(_out(output_path), "wb") as f:
            writer.write(f)
        log.info("pdf_split_range OK")
        return _ok(output_path, pages_extracted=end_page - start_page + 1)
    except Exception as e:
        log.error(f"pdf_split_range FAILED: {e}")
        return _err(str(e))


@mcp.tool()
def pdf_rotate(
    output_path: str = "",
    input_path: str = "",
    angle: int = 90,
    pages: str = "all",
) -> str:
    """
    Rotate pages in a PDF.
    output_path / input_path: leave empty to use the current PDF.
    angle: 90|180|270.
    pages: 'all' or JSON array of 1-indexed page numbers.
    """
    log.info(f"TOOL pdf_rotate {angle}°")
    try:
        inp = _resolve_input(input_path)
        out = output_path or _CURRENT_PDF or inp
        reader = PdfReader(inp); writer = PdfWriter()
        target = None if pages == "all" else set(json.loads(pages))
        for i, pg in enumerate(reader.pages):
            if target is None or (i + 1) in target: pg.rotate(angle)
            writer.add_page(pg)
        with open(_out(out), "wb") as f: writer.write(f)
        log.info("pdf_rotate OK")
        return _ok(out)
    except Exception as e:
        log.error(f"pdf_rotate FAILED: {e}")
        return _err(str(e))


@mcp.tool()
def pdf_compress(
    output_path: str = "",
    input_path: str = "",
) -> str:
    """
    Compress a PDF by deduplicating identical objects.
    output_path / input_path: leave empty to use the current PDF.
    """
    log.info("TOOL pdf_compress")
    try:
        inp = _resolve_input(input_path)
        out = output_path or _CURRENT_PDF or inp
        reader = PdfReader(inp); writer = PdfWriter()
        for pg in reader.pages: writer.add_page(pg)
        writer.compress_identical_objects(remove_identicals=True, remove_orphans=True)
        with open(_out(out), "wb") as f: writer.write(f)
        in_s  = os.path.getsize(inp)
        out_s = os.path.getsize(out)
        log.info("pdf_compress OK")
        return _ok(out, original_bytes=in_s, compressed_bytes=out_s,
                   reduction_pct=round((1 - out_s / in_s) * 100, 1))
    except Exception as e:
        log.error(f"pdf_compress FAILED: {e}")
        return _err(str(e))


@mcp.tool()
def pdf_encrypt(
    output_path: str = "",
    input_path: str = "",
    user_password: str = "",
    owner_password: str = "",
) -> str:
    """
    Password-protect a PDF.
    output_path / input_path: leave empty to use the current PDF.
    user_password: required to open.  owner_password: required to edit.
    """
    log.info("TOOL pdf_encrypt")
    try:
        inp = _resolve_input(input_path)
        out = output_path or _CURRENT_PDF or inp
        reader = PdfReader(inp); writer = PdfWriter()
        for pg in reader.pages: writer.add_page(pg)
        writer.encrypt(user_password, owner_password or user_password)
        with open(_out(out), "wb") as f: writer.write(f)
        log.info("pdf_encrypt OK")
        return _ok(out)
    except Exception as e:
        log.error(f"pdf_encrypt FAILED: {e}")
        return _err(str(e))


@mcp.tool()
def pdf_decrypt(
    output_path: str = "",
    input_path: str = "",
    password: str = "",
) -> str:
    """Remove password protection from a PDF."""
    log.info("TOOL pdf_decrypt")
    try:
        inp = _resolve_input(input_path)
        out = output_path or _CURRENT_PDF or inp
        reader = PdfReader(inp); reader.decrypt(password)
        writer = PdfWriter()
        for pg in reader.pages: writer.add_page(pg)
        with open(_out(out), "wb") as f: writer.write(f)
        log.info("pdf_decrypt OK")
        return _ok(out)
    except Exception as e:
        log.error(f"pdf_decrypt FAILED: {e}")
        return _err(str(e))


@mcp.tool()
def pdf_extract_text(
    input_path: str = "",
    pages: str = "all",
    output_txt: str = "",
) -> str:
    """
    Extract all text from a PDF using pdfplumber.
    input_path: leave empty to use the current PDF.
    pages: 'all' or JSON array of 1-indexed page numbers.
    output_txt: optional path to also save the full text.
    Returns up to 8 000 chars in the JSON response.
    """
    log.info("TOOL pdf_extract_text")
    try:
        inp = _resolve_input(input_path)
        target = None if pages == "all" else set(json.loads(pages))
        full_text = ""
        with pdfplumber.open(inp) as pdf:
            for i, pg in enumerate(pdf.pages):
                if target is None or (i + 1) in target:
                    full_text += f"\n--- Page {i+1} ---\n{pg.extract_text() or ''}"
        if output_txt:
            Path(output_txt).parent.mkdir(parents=True, exist_ok=True)
            Path(output_txt).write_text(full_text)
        log.info("pdf_extract_text OK")
        return json.dumps({"ok": True,
                           "text": full_text[:8000],
                           "total_chars": len(full_text),
                           "saved_to": output_txt or None})
    except Exception as e:
        log.error(f"pdf_extract_text FAILED: {e}")
        return _err(str(e))


@mcp.tool()
def pdf_extract_tables(
    input_path: str = "",
    output_json: str = "",
) -> str:
    """
    Extract all tables from a PDF as structured JSON.
    input_path: leave empty to use the current PDF.
    output_json: optional path to save the full result.
    """
    log.info("TOOL pdf_extract_tables")
    try:
        inp = _resolve_input(input_path)
        result = []
        with pdfplumber.open(inp) as pdf:
            for i, pg in enumerate(pdf.pages):
                for j, tbl in enumerate(pg.extract_tables()):
                    result.append({"page": i + 1, "table": j + 1, "data": tbl})
        if output_json:
            Path(output_json).parent.mkdir(parents=True, exist_ok=True)
            Path(output_json).write_text(json.dumps(result, indent=2))
        log.info("pdf_extract_tables OK")
        return json.dumps({"ok": True, "tables": result[:20],
                           "total_tables": len(result),
                           "saved_to": output_json or None})
    except Exception as e:
        log.error(f"pdf_extract_tables FAILED: {e}")
        return _err(str(e))


@mcp.tool()
def pdf_extract_images(
    input_path: str = "",
    output_dir: str = "",
    format: str = "png",
) -> str:
    """
    Extract all embedded images from a PDF.
    input_path: leave empty to use the current PDF.
    output_dir: defaults to 'extracted_images' next to the input.
    format: 'png'|'jpg'.
    """
    log.info("TOOL pdf_extract_images")
    try:
        inp = _resolve_input(input_path)
        if not output_dir:
            output_dir = str(Path(inp).parent / "extracted_images")
        reader = PdfReader(inp)
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        saved = []; img_idx = 0
        for i, pg in enumerate(reader.pages):
            for img_obj in pg.images:
                try:
                    img = PILImage.open(BytesIO(img_obj.data))
                    out_path = str(Path(output_dir) / f"page{i+1}_img{img_idx+1}.{format}")
                    img.save(out_path); saved.append(out_path); img_idx += 1
                except Exception:
                    pass
        log.info(f"pdf_extract_images OK — {len(saved)} images")
        return json.dumps({"ok": True, "images": saved, "count": len(saved)})
    except Exception as e:
        log.error(f"pdf_extract_images FAILED: {e}")
        return _err(str(e))


@mcp.tool()
def pdf_metadata_get(input_path: str = "") -> str:
    """Read all metadata fields from a PDF."""
    log.info("TOOL pdf_metadata_get")
    try:
        inp = _resolve_input(input_path)
        reader = PdfReader(inp); meta = reader.metadata or {}
        result = {
            "pages":    len(reader.pages),
            "title":    meta.get("/Title", ""),
            "author":   meta.get("/Author", ""),
            "subject":  meta.get("/Subject", ""),
            "creator":  meta.get("/Creator", ""),
            "producer": meta.get("/Producer", ""),
            "created":  str(meta.get("/CreationDate", "")),
            "modified": str(meta.get("/ModDate", "")),
            "encrypted": reader.is_encrypted,
        }
        log.info("pdf_metadata_get OK")
        return json.dumps({"ok": True, **result})
    except Exception as e:
        log.error(f"pdf_metadata_get FAILED: {e}")
        return _err(str(e))


@mcp.tool()
def pdf_metadata_set(
    output_path: str = "",
    input_path: str = "",
    title: str = "",
    author: str = "",
    subject: str = "",
    creator: str = "",
    keywords: str = "",
) -> str:
    """Update metadata fields in a PDF."""
    log.info("TOOL pdf_metadata_set")
    try:
        inp = _resolve_input(input_path)
        out = output_path or _CURRENT_PDF or inp
        reader = PdfReader(inp); writer = PdfWriter()
        for pg in reader.pages: writer.add_page(pg)
        meta = {}
        if title:    meta["/Title"]    = title
        if author:   meta["/Author"]   = author
        if subject:  meta["/Subject"]  = subject
        if creator:  meta["/Creator"]  = creator
        if keywords: meta["/Keywords"] = keywords
        writer.add_metadata(meta)
        with open(_out(out), "wb") as f: writer.write(f)
        log.info("pdf_metadata_set OK")
        return _ok(out, updated_fields=list(meta.keys()))
    except Exception as e:
        log.error(f"pdf_metadata_set FAILED: {e}")
        return _err(str(e))


@mcp.tool()
def pdf_reorder_pages(
    output_path: str = "",
    input_path: str = "",
    order: str = "[]",
) -> str:
    """
    Reorder pages in a PDF.
    order: JSON array of 1-indexed page numbers in the desired order.
    """
    log.info("TOOL pdf_reorder_pages")
    try:
        inp = _resolve_input(input_path)
        out = output_path or _CURRENT_PDF or inp
        page_order = json.loads(order)
        reader = PdfReader(inp); writer = PdfWriter()
        for pg_num in page_order: writer.add_page(reader.pages[pg_num - 1])
        with open(_out(out), "wb") as f: writer.write(f)
        log.info("pdf_reorder_pages OK")
        return _ok(out, new_order=page_order)
    except Exception as e:
        log.error(f"pdf_reorder_pages FAILED: {e}")
        return _err(str(e))


@mcp.tool()
def pdf_delete_pages(
    output_path: str = "",
    input_path: str = "",
    pages_to_delete: str = "[]",
) -> str:
    """
    Delete specific pages from a PDF.
    pages_to_delete: JSON array of 1-indexed page numbers.
    """
    log.info("TOOL pdf_delete_pages")
    try:
        inp = _resolve_input(input_path)
        out = output_path or _CURRENT_PDF or inp
        to_del = set(json.loads(pages_to_delete))
        reader = PdfReader(inp); writer = PdfWriter()
        for i, pg in enumerate(reader.pages):
            if (i + 1) not in to_del: writer.add_page(pg)
        with open(_out(out), "wb") as f: writer.write(f)
        log.info("pdf_delete_pages OK")
        return _ok(out, deleted=list(to_del),
                   remaining=len(reader.pages) - len(to_del))
    except Exception as e:
        log.error(f"pdf_delete_pages FAILED: {e}")
        return _err(str(e))


@mcp.tool()
def pdf_replace_page(
    base_pdf: str = "",
    replacement_pdf: str = "",
    output_path: str = "",
    page_number: int = 1,
) -> str:
    """
    Replace page *page_number* of base_pdf with the first page of replacement_pdf.
    All paths: leave empty to use the current PDF.
    page_number: 1-indexed.
    """
    log.info(f"TOOL pdf_replace_page page={page_number}")
    try:
        base = _resolve_input(base_pdf)
        repl = _resolve_input(replacement_pdf) if replacement_pdf else base
        out  = output_path or _CURRENT_PDF or base
        r_base = PdfReader(base); r_repl = PdfReader(repl)
        new_pg = r_repl.pages[0]
        writer = PdfWriter()
        for i, pg in enumerate(r_base.pages):
            writer.add_page(new_pg if i == page_number - 1 else pg)
        with open(_out(out), "wb") as f: writer.write(f)
        log.info("pdf_replace_page OK")
        return _ok(out, replaced_page=page_number)
    except Exception as e:
        log.error(f"pdf_replace_page FAILED: {e}")
        return _err(str(e))


@mcp.tool()
def pdf_crop(
    output_path: str = "",
    input_path: str = "",
    left: float = 0,
    bottom: float = 0,
    right: float = 0,
    top: float = 0,
    pages: str = "all",
) -> str:
    """
    Crop pages by trimming the given number of points from each edge.
    output_path / input_path: leave empty to use the current PDF.
    left/bottom/right/top: points to remove from each edge.
    pages: 'all' or JSON array of 1-indexed page numbers.
    """
    log.info("TOOL pdf_crop")
    try:
        inp = _resolve_input(input_path)
        out = output_path or _CURRENT_PDF or inp
        target = None if pages == "all" else set(json.loads(pages))
        reader = PdfReader(inp); writer = PdfWriter()
        for i, pg in enumerate(reader.pages):
            if target is None or (i + 1) in target:
                mb = pg.mediabox
                pg.mediabox.lower_left  = (float(mb.left) + left,   float(mb.bottom) + bottom)
                pg.mediabox.upper_right = (float(mb.right) - right,  float(mb.top)    - top)
            writer.add_page(pg)
        with open(_out(out), "wb") as f: writer.write(f)
        log.info("pdf_crop OK")
        return _ok(out)
    except Exception as e:
        log.error(f"pdf_crop FAILED: {e}")
        return _err(str(e))


@mcp.tool()
def pdf_flatten(
    output_path: str = "",
    input_path: str = "",
) -> str:
    """
    Flatten all interactive form fields into static content.
    output_path / input_path: leave empty to use the current PDF.
    """
    log.info("TOOL pdf_flatten")
    try:
        inp = _resolve_input(input_path)
        out = output_path or _CURRENT_PDF or inp
        reader = PdfReader(inp); writer = PdfWriter()
        for pg in reader.pages: writer.add_page(pg)
        if "/AcroForm" in writer._root_object:
            del writer._root_object["/AcroForm"]
        with open(_out(out), "wb") as f: writer.write(f)
        log.info("pdf_flatten OK")
        return _ok(out)
    except Exception as e:
        log.error(f"pdf_flatten FAILED: {e}")
        return _err(str(e))


@mcp.tool()
def pdf_page_info(
    input_path: str = "",
    page_number: int = 1,
) -> str:
    """
    Get detailed info about a single page: dimensions, rotation, crop box.
    input_path: leave empty to use the current PDF.
    page_number: 1-indexed.
    """
    log.info(f"TOOL pdf_page_info page={page_number}")
    try:
        inp = _resolve_input(input_path)
        reader = PdfReader(inp)
        total = len(reader.pages)
        if page_number < 1 or page_number > total:
            return _err(f"page_number {page_number} out of range (1–{total})")
        pg = reader.pages[page_number - 1]
        mb = pg.mediabox
        cb = getattr(pg, "cropbox", mb)
        result = {
            "page": page_number, "total_pages": total,
            "width_pts":  round(float(mb.width),  2),
            "height_pts": round(float(mb.height), 2),
            "width_mm":   round(float(mb.width)  * 25.4 / 72, 2),
            "height_mm":  round(float(mb.height) * 25.4 / 72, 2),
            "cropbox": {
                "left":   float(cb.left),   "bottom": float(cb.bottom),
                "right":  float(cb.right),  "top":    float(cb.top),
            },
            "rotation": pg.get("/Rotate", 0),
        }
        log.info("pdf_page_info OK")
        return json.dumps({"ok": True, **result})
    except Exception as e:
        log.error(f"pdf_page_info FAILED: {e}")
        return _err(str(e))


@mcp.tool()
def pdf_info(input_path: str = "") -> str:
    """
    Get a summary of a PDF: page count, dimensions, encryption status, metadata.
    input_path: leave empty to use the current PDF.
    """
    log.info("TOOL pdf_info")
    try:
        inp = _resolve_input(input_path)
        reader = PdfReader(inp); first = reader.pages[0] if reader.pages else None
        meta   = reader.metadata or {}
        info   = {
            "pages":           len(reader.pages),
            "encrypted":       reader.is_encrypted,
            "file_size_bytes": os.path.getsize(inp),
            "title":           meta.get("/Title", ""),
            "author":          meta.get("/Author", ""),
            "width_pts":       round(float(first.mediabox.width),  2) if first else None,
            "height_pts":      round(float(first.mediabox.height), 2) if first else None,
        }
        log.info("pdf_info OK")
        return json.dumps({"ok": True, **info})
    except Exception as e:
        log.error(f"pdf_info FAILED: {e}")
        return _err(str(e))


@mcp.tool()
def pdf_images_to_pdf(
    output_path: str,
    image_paths: str,
    page_size: str = "a4",
    fit: bool = True,
) -> str:
    """
    Convert a list of image files into a PDF (one image per page).
    image_paths: JSON array of local image file paths.
    fit: if True, scale to fill page; if False, centre at original size.
    output_path is required.
    """
    log.info(f"TOOL pdf_images_to_pdf → {output_path}")
    try:
        paths = json.loads(image_paths)
        ps = _page_size(page_size); w, h = ps
        c = rl_canvas.Canvas(_out(output_path), pagesize=ps)
        for i, img_path in enumerate(paths):
            if i > 0: c.showPage()
            img = PILImage.open(img_path); iw, ih = img.size
            if fit:
                scale = min(w / iw, h / ih); dw, dh = iw * scale, ih * scale
                c.drawImage(img_path, (w - dw) / 2, (h - dh) / 2, dw, dh)
            else:
                c.drawImage(img_path, (w - iw) / 2, (h - ih) / 2, iw, ih)
        c.save()
        log.info("pdf_images_to_pdf OK")
        return _ok(output_path, images_converted=len(paths))
    except Exception as e:
        log.error(f"pdf_images_to_pdf FAILED: {e}")
        return _err(str(e))

# =============================================================================
# URI RESOURCES
# =============================================================================

@mcp.resource("pdf://help")
def resource_help() -> str:
    """Full tool reference."""
    return json.dumps({
        "server_control": [
            "set_current_pdf",
            "get_current_pdf",
            "create_new_or_modify",
        ],
        "design_tools": [
            "create_gradient_page", "create_cover_page", "create_card_page",
            "create_hero_section", "create_timeline_page",
            "create_infographic_page", "create_certificate",
            "create_invoice", "create_resume", "create_brochure_page",
            "create_text_page", "create_table_page", "create_chart_page",
            "add_geometric_background",
        ],
        "overlay_tools": [
            "add_watermark", "add_page_numbers", "add_qr_code",
            "pdf_add_header_footer", "pdf_add_image_to_page",
            "pdf_add_text_annotation", "pdf_stamp",
        ],
        "standard_tools": [
            "pdf_merge", "pdf_append_page", "pdf_split", "pdf_split_range",
            "pdf_rotate", "pdf_compress", "pdf_encrypt", "pdf_decrypt",
            "pdf_extract_text", "pdf_extract_tables", "pdf_extract_images",
            "pdf_metadata_get", "pdf_metadata_set", "pdf_reorder_pages",
            "pdf_delete_pages", "pdf_replace_page", "pdf_crop",
            "pdf_flatten", "pdf_page_info", "pdf_images_to_pdf", "pdf_info",
        ],
        "tips": {
            "current_pdf":    "Call set_current_pdf('/path/file.pdf') once; all tools then use it by default.",
            "create_modify":  "Use create_new_or_modify(path, mode='new'|'modify'|'auto') to declare your working file.",
            "page_param":     "All design tools accept page=1,2,3,... or page='append'. Use the same output_path to build multi-page PDFs.",
            "temp_files":     "Every tool stores intermediate files in a TemporaryDirectory and deletes it automatically on exit — no temp leaks.",
            "text_wrap":      "All text is word-wrapped via _draw_text_block(). Use max_lines to cap overflow. Text never gets silently cut off.",
            "in_place_edit":  "Leave output_path empty and all write tools overwrite the current PDF in-place.",
        },
    })


# =============================================================================
# ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    log.info("Entering mcp.run() — waiting for MCP client via stdio")
    try:
        mcp.run()
    except Exception as e:
        log.critical(f"mcp.run() crashed: {e}")
        log.debug(traceback.format_exc())
        sys.exit(1)

