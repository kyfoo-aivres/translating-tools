import argparse
import os
import shutil
import glob
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.units import inch
import pdfplumber
from googletrans import Translator
from tqdm import tqdm
import asyncio

def extract_text_from_pdf(pdf_path):
    """
    Extract text from PDF using pdfplumber.
    """
    text_blocks = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text_blocks.append(page_text)
    return text_blocks

def create_pdf_with_text(text_blocks, output_path):
    """
    Create a new PDF with the translated text using reportlab.
    """
    doc = SimpleDocTemplate(output_path, pagesize=letter)
    styles = getSampleStyleSheet()
    story = []

    for block in text_blocks:
        # Split block into paragraphs
        paragraphs = block.split('\n\n')
        for para in paragraphs:
            if para.strip():
                p = Paragraph(para.strip(), styles['Normal'])
                story.append(p)
                story.append(Spacer(1, 0.2 * inch))

    doc.build(story)

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

    # Extract text from the PDF
    print("Extracting text from PDF...")
    try:
        text_blocks = extract_text_from_pdf(input_file)
    except Exception as e:
        print(f"Error extracting text from PDF: {e}")
        return

    if not text_blocks:
        print("No text found in the PDF.")
        return

    print(f"Discovered {len(text_blocks)} text blocks to translate.")
    
    # Setup issue logging 
    if os.path.exists(issue_file):
        os.remove(issue_file) # Clean up old issues file if it exists
        
    issue_found = False

    async def translate_text_blocks(blocks, desc):
        nonlocal issue_found
        # Initialize the translator inside the event loop
        translator = Translator()
        
        translated_blocks = []
        # Proceed with the translation and show the progress bar using tqdm
        for block in tqdm(blocks, desc=desc, unit="block"):
            try:
                # Perform the translation
                translation = translator.translate(block, src=src_lang, dest=dest_lang)
                
                # Wait for the result if it's an async coroutine
                if asyncio.iscoroutine(translation):
                    translation = await translation
                    
                # Add the translated text
                if translation and hasattr(translation, 'text'):
                    translated_blocks.append(translation.text)
                else:
                    translated_blocks.append(block)  # Fallback to original
            except Exception as e:
                issue_found = True
                translated_blocks.append(block)  # Fallback to original
                # Log the issue into the issue file
                with open(issue_file, "a", encoding="utf-8") as file:
                    file.write(f"Failed to translate block ({desc}): '{block[:100]}...'\n")
                    file.write(f"Error details: {str(e)}\n")
                    file.write("-" * 50 + "\n")
        
        return translated_blocks
                    
    async def main_translation_task():
        translated_blocks = await translate_text_blocks(text_blocks, "Translating PDF")
        return translated_blocks

    # Execute the async translation process
    translated_blocks = asyncio.run(main_translation_task())
    
    # Create the new PDF with translated text
    print("Creating translated PDF...")
    try:
        create_pdf_with_text(translated_blocks, output_file)
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