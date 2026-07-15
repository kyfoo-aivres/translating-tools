import argparse
import os
import shutil
import glob
import time
from collections import defaultdict
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, HRFlowable, PageBreak,
    Table, TableStyle
)
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.lib.colors import HexColor, black, white, lightgrey, Color
import re
import pdfplumber
from googletrans import Translator
from tqdm import tqdm
import asyncio

# ---------------------------------------------------------------------------
# Translation retry settings
# ---------------------------------------------------------------------------
MAX_RETRIES = 3
RETRY_INTERVAL_SEC = 10


# ---------------------------------------------------------------------------
# Formatting-aware text extraction
# ---------------------------------------------------------------------------

def _is_bold(fontname):
    """Check if a font name indicates bold weight."""
    name = fontname.lower()
    return 'bold' in name or 'heavy' in name or 'black' in name


def _is_italic(fontname):
    """Check if a font name indicates italic style."""
    name = fontname.lower()
    return 'italic' in name or 'oblique' in name


def _group_chars_into_lines(chars, line_tolerance=3):
    """
    Group characters into lines based on their vertical (top) position.
    Characters within `line_tolerance` pts of each other are on the same line.
    Returns lines sorted top-to-bottom, each line sorted left-to-right.
    """
    if not chars:
        return []

    # Sort by vertical position (top), then horizontal (x0)
    sorted_chars = sorted(chars, key=lambda c: (round(c['top']), c['x0']))

    lines = []
    current_line = [sorted_chars[0]]
    current_top = sorted_chars[0]['top']

    for ch in sorted_chars[1:]:
        if abs(ch['top'] - current_top) <= line_tolerance:
            current_line.append(ch)
        else:
            lines.append(sorted(current_line, key=lambda c: c['x0']))
            current_line = [ch]
            current_top = ch['top']

    if current_line:
        lines.append(sorted(current_line, key=lambda c: c['x0']))

    return lines


def _extract_line_info(line_chars):
    """
    From a list of character dicts (one line), extract:
      - text: the concatenated text
      - font_size: the dominant (most common) font size
      - is_bold: whether the majority of chars are bold
      - is_italic: whether the majority of chars are italic
      - x_offset: the x position of the first character (for indentation)
    """
    text = ''.join(ch['text'] for ch in line_chars)

    # Collect font sizes and bold/italic flags weighted by character count
    sizes = defaultdict(int)
    bold_count = 0
    italic_count = 0
    total = 0

    for ch in line_chars:
        if ch['text'].strip():  # skip whitespace for font analysis
            fontname = ch.get('fontname', '')
            size = round(ch.get('size', 10), 1)
            sizes[size] += 1
            if _is_bold(fontname):
                bold_count += 1
            if _is_italic(fontname):
                italic_count += 1
            total += 1

    if total == 0:
        return {
            'text': text,
            'font_size': 10,
            'is_bold': False,
            'is_italic': False,
            'x_offset': line_chars[0]['x0'] if line_chars else 0,
        }

    dominant_size = max(sizes, key=sizes.get)

    return {
        'text': text,
        'font_size': dominant_size,
        'is_bold': bold_count > total * 0.5,
        'is_italic': italic_count > total * 0.5,
        'x_offset': line_chars[0]['x0'],
    }


def extract_formatted_text(pdf_path):
    """
    Extract text from PDF along with formatting metadata.

    Returns a list of pages.  Each page is a dict:
        {
            'lines': [ line_info dicts ... ],
            'tables': [ [[cell, ...], ...], ... ]   # list of tables
        }

    Each line_info dict:
        {
            'text': str,
            'font_size': float,
            'is_bold': bool,
            'is_italic': bool,
            'x_offset': float,
        }
    """
    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            # --- Extract tables ---
            raw_tables = page.extract_tables() or []
            tables = []
            for tbl in raw_tables:
                # Each table is a list of rows; each row is a list of cell strings
                clean_table = []
                for row in tbl:
                    clean_row = [(cell if cell else '') for cell in row]
                    clean_table.append(clean_row)
                if clean_table:
                    tables.append(clean_table)

            # Collect text that lives inside tables so we can exclude it
            # from the free-text lines (avoid duplicating table content)
            table_cell_texts = set()
            for tbl in tables:
                for row in tbl:
                    for cell in row:
                        for fragment in cell.split('\n'):
                            stripped = fragment.strip()
                            if stripped:
                                table_cell_texts.add(stripped)

            # --- Extract formatted lines ---
            chars = page.chars
            page_lines = []
            if chars:
                lines = _group_chars_into_lines(chars)
                for line_chars in lines:
                    info = _extract_line_info(line_chars)
                    text_stripped = info['text'].strip()
                    if text_stripped and text_stripped not in table_cell_texts:
                        page_lines.append(info)

            if page_lines or tables:
                pages.append({'lines': page_lines, 'tables': tables})

    return pages


# ---------------------------------------------------------------------------
# Formatting-aware PDF generation
# ---------------------------------------------------------------------------

_style_cache = {}


def _get_style_for_line(line_info, base_styles, page_min_x):
    """
    Create or retrieve a ParagraphStyle that matches the source formatting.
    """
    size = line_info['font_size']
    bold = line_info['is_bold']
    italic = line_info['is_italic']

    # Calculate relative indentation from page left margin
    indent = max(0, line_info['x_offset'] - page_min_x)
    # Quantize indent to 10pt steps to avoid creating too many styles
    indent_q = round(indent / 10) * 10

    key = (size, bold, italic, indent_q)
    if key in _style_cache:
        return _style_cache[key]

    # Pick parent based on size relative to typical body text
    if size >= 16:
        parent = base_styles['Heading1']
    elif size >= 13:
        parent = base_styles['Heading2']
    elif size >= 11:
        parent = base_styles['Heading3']
    else:
        parent = base_styles['Normal']

    # Build a unique style name
    parts = [f's{size}']
    if bold:
        parts.append('b')
    if italic:
        parts.append('i')
    parts.append(f'ind{indent_q}')
    style_name = '_'.join(parts)

    # Font name logic
    font_name = 'Helvetica'
    if bold and italic:
        font_name = 'Helvetica-BoldOblique'
    elif bold:
        font_name = 'Helvetica-Bold'
    elif italic:
        font_name = 'Helvetica-Oblique'

    style = ParagraphStyle(
        style_name,
        parent=parent,
        fontName=font_name,
        fontSize=size,
        leading=size * 1.3,
        spaceAfter=size * 0.4,
        spaceBefore=size * 0.2 if size >= 13 else 0,
        leftIndent=indent_q,
    )

    _style_cache[key] = style
    return style


def _build_table_flowable(table_data, base_styles, font_size=8):
    """
    Build a reportlab Table flowable from translated table data.
    Applies grid lines, header styling, and alternating row colors.

    Args:
        table_data: list of rows, each row is a list of cell strings.
        base_styles: getSampleStyleSheet() result.
        font_size: base font size for cell text (reduced on retry).
    """
    if not table_data or not table_data[0]:
        return None

    leading = max(font_size + 2, font_size * 1.25)

    body_style = ParagraphStyle(
        f'TableCell_{font_size}', parent=base_styles['Normal'],
        fontSize=font_size, leading=leading,
        spaceAfter=0, spaceBefore=0,
    )
    header_style = ParagraphStyle(
        f'TableHeader_{font_size}', parent=base_styles['Normal'],
        fontSize=font_size, leading=leading,
        spaceAfter=0, spaceBefore=0,
        fontName='Helvetica-Bold',
    )

    # Available height for a single page frame
    frame_height = letter[1] - 1.5 * inch   # page height minus margins

    # Wrap cell text in Paragraphs so long text wraps properly
    wrapped = []
    for r_idx, row in enumerate(table_data):
        style = header_style if r_idx == 0 else body_style
        wrapped_row = []
        for cell in row:
            cell_text = (cell or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            # Preserve internal newlines as <br/>
            cell_text = cell_text.replace('\n', '<br/>')
            wrapped_row.append(Paragraph(cell_text, style))
        wrapped.append(wrapped_row)

    # Calculate column widths: distribute available width evenly
    num_cols = max(len(row) for row in wrapped)
    avail_width = letter[0] - 1.5 * inch  # page width minus margins
    col_width = avail_width / num_cols
    col_widths = [col_width] * num_cols

    tbl = Table(wrapped, colWidths=col_widths, repeatRows=1,
                splitByRow=True)

    # Enable splitting within a row (reportlab 3.6+).
    # This lets tall rows span across pages instead of raising an error.
    try:
        tbl.splitInRow = 1
    except AttributeError:
        pass

    # Alternating row colors
    alt_color = Color(0.94, 0.94, 0.97)  # light blue-grey
    style_cmds = [
        ('GRID', (0, 0), (-1, -1), 0.5, black),
        ('BACKGROUND', (0, 0), (-1, 0), HexColor('#2c3e50')),
        ('TEXTCOLOR', (0, 0), (-1, 0), white),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING', (0, 0), (-1, -1), 3),
        ('RIGHTPADDING', (0, 0), (-1, -1), 3),
    ]
    # Alternating row backgrounds (skip header row 0)
    for i in range(1, len(wrapped)):
        if i % 2 == 0:
            style_cmds.append(
                ('BACKGROUND', (0, i), (-1, i), alt_color)
            )

    tbl.setStyle(TableStyle(style_cmds))
    return tbl


def _build_story(pages_with_format, translated_pages, base_styles, table_font_size=8):
    """
    Build the reportlab story (list of flowables) for the translated PDF.

    Separated from create_pdf_with_formatted_text so it can be retried
    with a smaller table_font_size when a table is too large for a page.
    """
    story = []

    for page_idx, (page_fmt, page_trans) in enumerate(
        zip(pages_with_format, translated_pages)
    ):
        fmt_lines = page_fmt['lines']
        trans_lines = page_trans['lines']
        trans_tables = page_trans['tables']

        # --- Render formatted lines ---
        if fmt_lines:
            page_min_x = min(line['x_offset'] for line in fmt_lines)

            for line_info, translated_text in zip(fmt_lines, trans_lines):
                text = translated_text.strip()
                if not text:
                    story.append(Spacer(1, 0.1 * inch))
                    continue

                # Escape XML-sensitive characters for reportlab Paragraph
                text = text.replace('&', '&amp;')
                text = text.replace('<', '&lt;')
                text = text.replace('>', '&gt;')

                style = _get_style_for_line(line_info, base_styles, page_min_x)
                story.append(Paragraph(text, style))

        # --- Render tables ---
        for tbl_data in trans_tables:
            # Start each table on a fresh page so it has full frame height
            story.append(PageBreak())
            story.append(Spacer(1, 0.1 * inch))
            tbl_flowable = _build_table_flowable(
                tbl_data, base_styles, font_size=table_font_size
            )
            if tbl_flowable:
                story.append(tbl_flowable)
            story.append(Spacer(1, 0.15 * inch))

        # Page break between pages
        if page_idx < len(pages_with_format) - 1:
            story.append(PageBreak())

    return story


def create_pdf_with_formatted_text(pages_with_format, translated_pages, output_path):
    """
    Create a new PDF applying the source formatting to translated text.

    If a table is too large for a page, automatically retries with
    progressively smaller table font sizes.

    Args:
        pages_with_format: list of page dicts (lines + tables)
        translated_pages: list of dicts with 'lines' and 'tables' keys
                          containing translated text
        output_path: path for the output PDF
    """
    global _style_cache

    base_styles = getSampleStyleSheet()

    # Font sizes to try — start normal, shrink if tables don't fit
    font_sizes_to_try = [8, 6, 5, 4]

    for font_size in font_sizes_to_try:
        _style_cache = {}  # reset cache for each attempt

        doc = SimpleDocTemplate(
            output_path, pagesize=letter,
            topMargin=0.75 * inch, bottomMargin=0.75 * inch,
            leftMargin=0.75 * inch, rightMargin=0.75 * inch,
        )

        story = _build_story(
            pages_with_format, translated_pages, base_styles,
            table_font_size=font_size,
        )

        try:
            doc.build(story)
            if font_size != font_sizes_to_try[0]:
                print(f"  (Tables rendered with reduced font size {font_size}pt)")
            return  # success
        except Exception as e:
            error_msg = str(e).lower()
            if 'too large' in error_msg and font_size != font_sizes_to_try[-1]:
                print(
                    f"  Table too large at {font_size}pt font, "
                    f"retrying with smaller font..."
                )
                continue
            else:
                raise  # re-raise if it's not a size error or we're out of options


# ---------------------------------------------------------------------------
# Translation logic
# ---------------------------------------------------------------------------

def translate_pdf(input_file, src_lang="zh-cn", dest_lang="en"):
    # Ensure input file exists
    if not os.path.exists(input_file):
        print(f"Error: The file '{input_file}' was not found.")
        return

    # Prepare input, output, and log paths
    file_directory = os.path.dirname(os.path.abspath(input_file))
    base_name = os.path.splitext(os.path.basename(input_file))[0]
    ext_name = os.path.splitext(input_file)[1]
    
    # Setup paths according to the requirements
    output_file = os.path.join(file_directory, f"{base_name}_{dest_lang}{ext_name}")
    issue_file = os.path.join(file_directory, f"Issues_{base_name}.txt")

    # Extract formatted text from the PDF
    print("Extracting formatted text from PDF...")
    try:
        pages = extract_formatted_text(input_file)
    except Exception as e:
        print(f"Error extracting text from PDF: {e}")
        return

    if not pages:
        print("No text found in the PDF.")
        return

    total_lines = sum(len(page) for page in pages)
    print(f"Discovered {len(pages)} pages with {total_lines} text lines to translate.")
    
    # Setup issue logging 
    if os.path.exists(issue_file):
        os.remove(issue_file) # Clean up old issues file if it exists
        
    issue_found = False

    async def translate_single(translator, text):
        """
        Translate a single text string with retry logic.
        Retries up to MAX_RETRIES times with RETRY_INTERVAL_SEC wait
        if the result is blank or an error occurs.
        """
        nonlocal issue_found
        last_error = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                translation = translator.translate(text, src=src_lang, dest=dest_lang)

                if asyncio.iscoroutine(translation):
                    translation = await translation

                if translation and hasattr(translation, 'text') and translation.text.strip():
                    return translation.text

                # Translation returned blank — retry
                last_error = "Translation returned blank result"
            except Exception as e:
                last_error = str(e)

            if attempt < MAX_RETRIES:
                tqdm.write(
                    f"  Retry {attempt}/{MAX_RETRIES} in {RETRY_INTERVAL_SEC}s "
                    f"for: '{text[:60]}...'"
                )
                time.sleep(RETRY_INTERVAL_SEC)

        # All retries exhausted — log and fall back to original
        issue_found = True
        with open(issue_file, "a", encoding="utf-8") as file:
            file.write(
                f"Failed to translate after {MAX_RETRIES} attempts: "
                f"'{text[:100]}...'\n"
            )
            file.write(f"Last error: {last_error}\n")
            file.write("-" * 50 + "\n")
        return text  # Fallback to original

    async def translate_lines(all_lines_text, desc):
        """Translate a flat list of text strings with retry support."""
        translator = Translator()
        translated = []
        for text in tqdm(all_lines_text, desc=desc, unit="line"):
            result = await translate_single(translator, text)
            translated.append(result)
        return translated

    async def translate_table(table, table_idx):
        """
        Translate all cells in a table (list of rows) with retry support.
        Returns a new table with translated cell text.
        """
        translator = Translator()
        translated_table = []
        total_cells = sum(len(row) for row in table)
        pbar = tqdm(total=total_cells, desc=f"Table {table_idx + 1}", unit="cell")

        for row in table:
            translated_row = []
            for cell in row:
                if cell.strip():
                    result = await translate_single(translator, cell)
                    translated_row.append(result)
                else:
                    translated_row.append(cell)
                pbar.update(1)
            translated_table.append(translated_row)

        pbar.close()
        return translated_table

    async def main_translation_task():
        # Flatten all lines for translation, keeping track of page boundaries
        all_texts = []
        page_line_lengths = []
        for page in pages:
            texts = [line['text'] for line in page['lines']]
            all_texts.extend(texts)
            page_line_lengths.append(len(texts))

        # Translate all lines at once (single progress bar)
        all_translated = await translate_lines(all_texts, "Translating lines")

        # Re-group translated lines back into pages
        translated_pages = []
        offset = 0
        global_table_idx = 0
        for page_idx, page in enumerate(pages):
            length = page_line_lengths[page_idx]
            trans_lines = all_translated[offset:offset + length]
            offset += length

            # Translate tables for this page
            trans_tables = []
            for tbl in page['tables']:
                translated_tbl = await translate_table(tbl, global_table_idx)
                trans_tables.append(translated_tbl)
                global_table_idx += 1

            translated_pages.append({
                'lines': trans_lines,
                'tables': trans_tables,
            })

        return translated_pages

    # Execute the async translation process
    translated_pages = asyncio.run(main_translation_task())
    
    # Create the new PDF with translated text + original formatting
    print("Creating translated PDF with source formatting...")
    try:
        create_pdf_with_formatted_text(pages, translated_pages, output_file)
        print(f"\nTranslation complete. The translated file is ready at: {output_file}")
    except Exception as e:
        print(f"\nError: Could not create the translated PDF: {e}")

    # Notify the user if issues were logged
    if issue_found:
        print(f"Note: Some issues occurred during translation. See '{issue_file}' for details.")

def process_file(file_path, src_lang, dest_lang):
    print(f"\n{'='*50}\nProcessing file: {file_path}\n{'='*50}")
    translate_pdf(file_path, src_lang, dest_lang)

def main():
    parser = argparse.ArgumentParser(description="Translate PDF files.")
    
    # Mutually exclusive group for file or directory input
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("-f", "--file", help="Path to a single source PDF file to translate")
    group.add_argument("-d", "--directory", help="Path to a directory containing PDF files to translate")
    
    parser.add_argument("--source", default="zh-cn", help="Source language code (default: zh-CN)")
    parser.add_argument("--target", default="en", help="Target language code (default: en)")
    
    args = parser.parse_args()
    
    if args.file:
        process_file(args.file, args.source, args.target)
    elif args.directory:
        if not os.path.isdir(args.directory):
            print(f"Error: Directory '{args.directory}' does not exist.")
            return
            
        pdf_files = glob.glob(os.path.join(args.directory, "*.pdf"))
        
        if not pdf_files:
            print(f"No .pdf files found in directory: {args.directory}")
            return
            
        print(f"Discovered {len(pdf_files)} .pdf files in '{args.directory}'.")
        for pdf in pdf_files:
            process_file(pdf, args.source, args.target)

if __name__ == "__main__":
    main()