# IPO Lock-in Processor v2.0 - Step 1 Implementation

## What This Replicates

This new implementation **exactly replicates** the following processes from your current project:

### ✅ Text Extraction (from `pdf_to_text.py`)
- Uses **pdf-layout-tool-1.0.0-all.jar** (layout-preserving extraction)
- Creates **`*_java.txt`** files from PDFs
- Also creates **`*_pdfplumber.txt`** files as backup
- Handles scanned images (warns when text <100 bytes)

### ✅ PNG Generation
- **NSE**: Extracts last page from lock-in PDF
- **BSE**: Extracts all pages and stitches them vertically
- Uses PyMuPDF (fitz) + Pillow (PIL)

### ✅ Folder Structure
```
downloads/
    nse/pdf/lockin/        *.pdf
    nse/pdf/lockin/txt/    *_java.txt, *_pdfplumber.txt
    nse/pdf/lockin/png/    *.png
    nse/pdf/shp/           *.pdf
    nse/pdf/shp/txt/       *_java.txt, *_pdfplumber.txt
    bse/pdf/lockin/        *.pdf
    bse/pdf/lockin/txt/    *_java.txt, *_pdfplumber.txt
    bse/pdf/lockin/png/    *.png
    bse/pdf/shp/           *.pdf
    bse/pdf/shp/txt/       *_java.txt, *_pdfplumber.txt
```

### ✅ Filename Patterns
- **NSE**: `AAKAAR-CML68761.pdf` → unique_symbol = `NSE:AAKAAR`
- **BSE**: `544324-CITICHEM-Annexure-I.pdf` → unique_symbol = `BSE:544324`

## Installation

1. **Copy .env configuration**:
   ```bash
   cp .env.example ../.env
   # Edit ../.env with your database credentials
   ```

2. **Install dependencies**:
   ```bash
   pip install pymupdf pillow pdfplumber python-dotenv mysql-connector-python
   ```

3. **Ensure Java JAR exists**:
   Place `pdf-layout-tool-1.0.0-all.jar` in the parent directory (`ScripUnlockDetails/`)

## Usage

### Single File Processing

```bash
# NSE file (dry-run mode)
python app.py AAKAAR-CML68761.pdf --nse --dryrun

# BSE file (actual processing)
python app.py 544324-CITICHEM-Annexure-I.pdf --bse

# Skip database operations
python app.py 544324-CITICHEM-Annexure-I.pdf --bse --nodb

# With GEMINI extraction (requires --GEMAPPROVED flag)
python app.py 544324-CITICHEM-Annexure-I.pdf --bse --GEMAPPROVED
```

### Batch Processing (Coming in Next Step)

```bash
# Process all NSE files
python app.py --nse

# Process all BSE files
python app.py --bse --dryrun
```

## What Step 1 Does

1. ✅ **Validates file paths**
   - Checks lock-in PDF exists
   - Checks SHP PDF exists
   - Parses filename to extract symbol/code

2. ✅ **Generates text files**
   - Creates `*_java.txt` using pdf-layout-tool JAR
   - Creates `*_pdfplumber.txt` using pdfplumber
   - Detects scanned images (warns if text <100 bytes)

3. ✅ **Generates PNG**
   - NSE: Last page only
   - BSE: All pages stitched vertically

4. ✅ **Connects to database**
   - Tests connection with retry logic
   - Skipped if `--nodb` flag used

## Output Example

```
======================================================================
IPO Lock-in Processor v2.0
======================================================================
Exchange: BSE
File: 544324-CITICHEM-Annexure-I.pdf
Mode: NORMAL
======================================================================

STEPS:
  1. ⚙ Validating file paths
  2. ✓ Lock-in PDF found: downloads/bse/pdf/lockin/544324-CITICHEM-Annexure-I.pdf
  3. ✓ SHP PDF found: downloads/bse/pdf/shp/544324-CITICHEM-Annexure-II.pdf
  4. ✓ Parsed symbol: BSE:544324
  5. ⚙ Extracting Lock-in text with Java...
  6. ✓ Java TXT created: downloads/bse/pdf/lockin/txt/544324-CITICHEM-Annexure-I_java.txt (15432 chars)
  7. ⚙ Extracting Lock-in text with PDFPlumber...
  8. ✓ PDFPlumber TXT created: downloads/bse/pdf/lockin/txt/544324-CITICHEM-Annexure-I_pdfplumber.txt (14987 chars)
  9. ⚙ Extracting SHP text with Java...
  10. ✓ Java TXT created: downloads/bse/pdf/shp/txt/544324-CITICHEM-Annexure-II_java.txt (3421 chars)
  11. ⚙ Extracting SHP text with PDFPlumber...
  12. ✓ PDFPlumber TXT created: downloads/bse/pdf/shp/txt/544324-CITICHEM-Annexure-II_pdfplumber.txt (3198 chars)
  13. ⚙ Generating PNG from PDF (all page(s))...
  14. ✓ PNG generated (stitched 3 pages): downloads/bse/pdf/lockin/png/544324-CITICHEM-Annexure-I.png
  15. ⚙ Connecting to database...
  16. ✓ Database connection established

======================================================================
✅ STEP 1 COMPLETE - Ready for parsing
======================================================================

Files prepared:
  • Lock-in Java TXT:       downloads/bse/pdf/lockin/txt/544324-CITICHEM-Annexure-I_java.txt
  • Lock-in PDFPlumber TXT: downloads/bse/pdf/lockin/txt/544324-CITICHEM-Annexure-I_pdfplumber.txt
  • SHP Java TXT:           downloads/bse/pdf/shp/txt/544324-CITICHEM-Annexure-II_java.txt
  • SHP PDFPlumber TXT:     downloads/bse/pdf/shp/txt/544324-CITICHEM-Annexure-II_pdfplumber.txt
  • Lock-in PNG:            downloads/bse/pdf/lockin/png/544324-CITICHEM-Annexure-I.png

Next: Implement parsing logic (Step 2)
```

## Testing

Test the database connection:
```bash
python db.py
```

Test with dry-run mode (shows what would happen without doing it):
```bash
python app.py 544324-CITICHEM-Annexure-I.pdf --bse --dryrun --verbose
```

## Next Steps

- **Step 2**: Parse lock-in details from `*_java.txt` files
- **Step 3**: Parse SHP data from SHP `*_java.txt` files
- **Step 4**: Implement validation rules (RULE1-RULE10)
- **Step 5**: GEMINI extraction (when --GEMAPPROVED)
- **Step 6**: Save to database
- **Step 7**: Finalize files (move to finalized/)
- **Step 8**: Dashboard UI

## Files Created

- `app.py` - Main processor (replicates extraction workflow)
- `config_new.py` - Configuration (folder structure, patterns)
- `db.py` - Database utilities (connection pooling, transactions)
- `.env.example` - Environment template
- `README.md` - This file

## Key Differences from Current Project

✅ **Same functionality**, but:
- Single entry point (`app.py` instead of multiple scripts)
- Clean separation (config, db, processing)
- Better error handling with exit codes
- Transaction support (all-or-nothing)
- Dry-run mode for testing
- Progress tracking with step numbers
