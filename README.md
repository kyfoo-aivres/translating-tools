# Document Translation Scripts

This repository contains Python scripts for translating various document formats using Google Translate, while preserving formatting where possible.

## Available Scripts

### 1. Excel Translation (`translate_xlsx.py`)
Translates Excel `.xlsx` files while preserving workbook formatting, styles, and structure.

### 2. PowerPoint Translation (`translate_pptx.py`)
Translates Microsoft PowerPoint `.pptx` files, including slides and notes, while preserving formatting.

### 3. Word Document Translation (`translate_docx.py`)
Translates Microsoft Word `.docx` files, including text in paragraphs and tables, while preserving formatting.

### 4. PDF Translation (`translate_pdf.py`)
Extracts text from PDF files, translates it, and generates a new PDF with translated content. Note: Original layout and formatting cannot be preserved.

## Installation

Install the required Python dependencies from the repository requirements file:

```bash
python -m pip install -r requirements.txt
```

If you prefer to install them manually, use:

```bash
pip install googletrans==4.0.0rc1 tqdm openpyxl python-docx python-pptx pdfplumber reportlab
```

### Dependencies Details
- `googletrans`: Google Translate API client
- `tqdm`: Progress bars
- `openpyxl`: Excel file handling
- `python-docx`: Word document handling
- `python-pptx`: PowerPoint file handling
- `pdfplumber`: PDF text extraction
- `reportlab`: PDF generation

Built-in modules: `argparse`, `os`, `shutil`, `glob`, `asyncio`

## Usage

All scripts use similar command-line arguments:

- `-f, --file`: Path to a single file
- `-d, --directory`: Path to a directory containing files
- `--source`: Source language code. Defaults to `zh-CN` if omitted.
- `--target`: Target language code. Defaults to `en` if omitted.

### Default language settings

If you do not provide the language options, the scripts use these defaults:

- `--source zh-CN`
- `--target en`

### Language selection

You can override the defaults by specifying `--source` and `--target` with any supported Google Translate language code. Common examples include:

- `zh-CN` (Simplified Chinese)
- `en` (English)
- `ja` (Japanese)
- `de` (German)
- `fr` (French)
- `es` (Spanish)
- `ko` (Korean)

Examples:

```bash
# Use the built-in defaults
python translate_xlsx.py -f document.xlsx

# Explicitly translate from Chinese to Japanese
python translate_docx.py -f document.docx --source zh-CN --target ja

# Translate from English to French
python translate_pptx.py -f presentation.pptx --source en --target fr
```

### Excel Translation
```bash
# Single file
python translate_xlsx.py -f document.xlsx --source zh-CN --target en

# Directory batch
python translate_xlsx.py -d ./excel_files --source zh-CN --target en
```

### PowerPoint Translation
```bash
# Single file
python translate_pptx.py -f presentation.pptx --source zh-CN --target en

# Directory batch
python translate_pptx.py -d ./pptx_files --source zh-CN --target en
```

### Word Document Translation
```bash
# Single file
python translate_docx.py -f document.docx --source zh-CN --target en

# Directory batch
python translate_docx.py -d ./docx_files --source zh-CN --target en
```

### PDF Translation
```bash
# Single file
python translate_pdf.py -f document.pdf --source zh-CN --target en

# Directory batch
python translate_pdf.py -d ./pdf_files --source zh-CN --target en
```

### Convert PDF to MS Word
```bash
# In Kali-Linux
sudo apt update && sudo apt install calibre -y

# Convert PDF file to MS Word
ebook-convert GB300_BIOS_2.1.pdf GB300_BIOS_2.1.docx
```

## Output

- Translated files are saved with `_TARGETLANG` suffix (e.g., `document_en.xlsx`)
- Issues during translation are logged to `Issues_FILENAME.txt`
- For PDFs, a new PDF is created with basic text formatting

## Notes

- **Formatting Preservation**: Excel, PowerPoint, and Word scripts preserve original formatting. PDF translation creates a new document with basic layout.
- **Language Support**: Uses Google Translate, so supports all languages Google Translate does.
- **Error Handling**: Failed translations are logged and the original text is kept as fallback.
- **Async Processing**: Uses asyncio for efficient translation requests.
- **Progress Bars**: Shows translation progress with tqdm.

## Troubleshooting

- Ensure all dependencies are installed
- Check internet connection for Google Translate API
- For PDFs with images/scanned content, text extraction may fail
- Large files may take time to process
- `-h`, `--help`: show help information
- `-f`, `--file INPUT_FILE`: path to a single Excel file (`.xlsx`)
- `-d`, `--directory INPUT_DIR`: path to a directory containing `.xlsx` files for batch translation
- `--source SOURCE`: source language code (default: `zh-CN`)
- `--target TARGET`: target language code (default: `en`)
