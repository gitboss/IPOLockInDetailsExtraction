"""
Configuration for IPO Lock-in Processor v2.0
Replicates folder structure and patterns from current project
"""

from pathlib import Path

# Base directories
BASE_DIR = Path(__file__).parent  # Points to IPOLockInDetailsExtraction/
DOWNLOADS_DIR = BASE_DIR / "downloads"
FINALIZED_DIR = BASE_DIR / "finalized"

# PDF extraction tool (EXACT path from current project)
PDF_LAYOUT_JAR = "pdf-layout-tool-1.0.0-all.jar"

# Exchange configurations
EXCHANGES = {
    'NSE': {
        # Filename pattern: AAKAAR-CML68761.pdf
        'lockin_pattern': r'^(.+)-CML(\d+)\.pdf$',
        # SHP pattern: SHP-{symbol}.pdf
        'shp_pattern': 'SHP-{symbol}.pdf',
        # Extract last page only for PNG
        'png_pages': 'last',
    },
    'BSE': {
        # Filename pattern: 544324-CITICHEM-Annexure-I.pdf
        'lockin_pattern': r'^(\d+)-(.+)-Annexure-I\.pdf$',
        # SHP pattern: {code}-{symbol}-Annexure-II.pdf
        'shp_pattern': '{code}-{symbol}-Annexure-II.pdf',
        # Extract all pages for PNG (stitch together)
        'png_pages': 'all',
    }
}

# Folder structure (mirrored for downloads and finalized)
"""
downloads/
    nse/
        pdf/
            lockin/
                *.pdf
                txt/
                    *_java.txt
                    *_pdfplumber.txt
                png/
                    *.png
            shp/
                *.pdf
                txt/
                    *_java.txt
                    *_pdfplumber.txt
    bse/
        pdf/
            lockin/
                *.pdf
                txt/
                    *_java.txt
                    *_pdfplumber.txt
                png/
                    *.png
            shp/
                *.pdf
                txt/
                    *_java.txt
                    *_pdfplumber.txt

finalized/
    {same structure as downloads}
"""
