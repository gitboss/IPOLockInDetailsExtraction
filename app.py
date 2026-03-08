#!/usr/bin/env python3
"""
IPO Lock-in Expiry Processor v2.0
==================================
Clean implementation replicating the exact process from the current project.

Usage:
    # Process single file
    python app.py AAKAAR-CML68761.pdf --nse --dryrun
    python app.py 544324-CITICHEM-Annexure-I.pdf --bse --GEMAPPROVED

    # Process all files in exchange folder
    python app.py --bse --dryrun
    python app.py --nse
"""

import os
import sys
import argparse
import re
import subprocess
from pathlib import Path
from typing import Optional, Tuple

# Import extraction libraries
try:
    import fitz  # PyMuPDF
    HAVE_FITZ = True
except ImportError:
    HAVE_FITZ = False

try:
    from PIL import Image
    HAVE_PIL = True
except ImportError:
    HAVE_PIL = False

try:
    import pdfplumber
    HAVE_PDFPLUMBER = True
except ImportError:
    HAVE_PDFPLUMBER = False

# Import local modules
from config import BASE_DIR, DOWNLOADS_DIR, FINALIZED_DIR, EXCHANGES, PDF_LAYOUT_JAR
import db
from parser_lockin import parse_lockin_file
from parser_shp import parse_shp_file
from validator import validate_all_rules
from database import get_master_data, save_processing_log, update_processing_log_error
from models import ProcessingStatus
from finalizer import finalize_files, check_can_finalize

# Exit Codes
EXIT_SUCCESS = 0
EXIT_FILE_NOT_FOUND = 1
EXIT_PARSE_ERROR = 2
EXIT_VALIDATION_FAILED = 3
EXIT_GEMINI_ERROR = 4
EXIT_DB_ERROR = 5


class IPOProcessor:
    """Main processor class that replicates the current project's extraction workflow"""

    def __init__(self, args):
        # Determine exchange
        if args.nse:
            self.exchange = "NSE"
        elif args.bse:
            self.exchange = "BSE"
        else:
            print("❌ Error: Must specify --nse or --bse")
            sys.exit(EXIT_VALIDATION_FAILED)

        self.file_name = args.file_name
        self.dry_run = args.dryrun
        self.no_db = args.nodb
        self.verbose = args.verbose
        self.gemini_approved = args.GEMAPPROVED
        self.movefiles = args.movefiles
        self.manual_override = (args.manual_override or "").split(",") if args.manual_override else []
        self.reason = args.reason

        # File paths (will be set during validation)
        self.lockin_pdf_path = None
        self.shp_pdf_path = None
        self.symbol = None
        self.code = None
        self.unique_symbol = None

        # Text file paths
        self.lockin_java_txt = None
        self.lockin_pdfplumber_txt = None
        self.shp_java_txt = None
        self.shp_pdfplumber_txt = None

        # PNG path
        self.lockin_png_path = None

        # Step 2: Master data (from sme_ipo_master)
        self.allotment_date = None
        self.processing_log_id = None  # Saved after database insert
        self.declared_total = None
        self.anchor_letter_url = None

        # Step 2: Parsed data
        self.lockin_data = None
        self.shp_data = None

        # Step 2: Validation results
        self.validations = []
        self.all_rules_passed = False

    def print_header(self):
        """Print formatted header"""
        print("=" * 70)
        print("IPO Lock-in Processor v2.0")
        print("=" * 70)
        print(f"Exchange: {self.exchange}")

        if self.file_name:
            print(f"File: {self.file_name}")
        else:
            print("File: ALL FILES IN EXCHANGE FOLDER")

        mode_parts = []
        if self.dry_run:
            mode_parts.append("DRY RUN")
        if self.no_db:
            mode_parts.append("NO DB")
        if self.gemini_approved:
            mode_parts.append("GEMINI APPROVED")
        if not mode_parts:
            mode_parts.append("NORMAL")

        print(f"Mode: {' | '.join(mode_parts)}")
        print("=" * 70)
        print("\nSTEPS:")

    def log_step(self, step_num: int, status: str, message: str):
        """Log a processing step"""
        prefix = "WOULD: " if self.dry_run and status == "⚙" else ""
        print(f"  {step_num}. {status} {prefix}{message}")

    def parse_filename(self) -> Tuple[Optional[str], Optional[str]]:
        """
        Parse filename to extract symbol/code based on exchange.
        Returns: (code, symbol) for BSE or (None, symbol) for NSE
        """
        ex_config = EXCHANGES[self.exchange]
        match = re.match(ex_config['lockin_pattern'], self.file_name)

        if not match:
            return None, None

        if self.exchange == "NSE":
            # NSE: AAKAAR-CML68761.pdf → symbol=AAKAAR
            symbol = match.group(1)
            return None, symbol
        else:  # BSE
            # BSE: 544324-CITICHEM-Annexure-I.pdf → code=544324, symbol=CITICHEM
            code = match.group(1)
            symbol = match.group(2)
            return code, symbol

    def validate_files(self, step_num: int) -> int:
        """Check all required files exist (replicates current validation)"""
        self.log_step(step_num, "⚙", "Validating file paths")
        step_num += 1

        if not self.file_name:
            print("\n⚠️  Batch processing (all files) not yet implemented in Step 1.")
            print("   Please specify a filename for now.")
            sys.exit(EXIT_SUCCESS)

        # Build paths based on exchange
        ex_config = EXCHANGES[self.exchange]
        ex_lower = self.exchange.lower()

        # Lock-in PDF path
        lockin_dir = DOWNLOADS_DIR / ex_lower / "pdf" / "lockin"
        self.lockin_pdf_path = lockin_dir / self.file_name

        if not self.lockin_pdf_path.exists():
            print(f"\n❌ File not found: {self.lockin_pdf_path}")
            sys.exit(EXIT_FILE_NOT_FOUND)

        # Parse filename
        self.code, self.symbol = self.parse_filename()

        if self.symbol is None:
            print(f"\n❌ Filename does not match expected pattern for {self.exchange}: {self.file_name}")
            print(f"   Expected pattern: {ex_config['lockin_pattern']}")
            sys.exit(EXIT_VALIDATION_FAILED)

        # Build unique_symbol
        if self.exchange == "NSE":
            self.unique_symbol = f"NSE:{self.symbol}"
        else:  # BSE
            self.unique_symbol = f"BSE:{self.code}"

        # SHP PDF path
        shp_dir = DOWNLOADS_DIR / ex_lower / "pdf" / "shp"

        if self.exchange == "NSE":
            shp_filename = ex_config['shp_pattern'].format(symbol=self.symbol)
        else:  # BSE
            shp_filename = ex_config['shp_pattern'].format(code=self.code, symbol=self.symbol)

        self.shp_pdf_path = shp_dir / shp_filename

        if not self.shp_pdf_path.exists():
            print(f"\n❌ File not found: {self.shp_pdf_path}")
            sys.exit(EXIT_FILE_NOT_FOUND)

        # Log success
        self.log_step(step_num, "✓", f"Lock-in PDF found: {self.lockin_pdf_path.relative_to(BASE_DIR)}")
        step_num += 1
        self.log_step(step_num, "✓", f"SHP PDF found: {self.shp_pdf_path.relative_to(BASE_DIR)}")
        step_num += 1
        self.log_step(step_num, "✓", f"Parsed symbol: {self.unique_symbol}")
        step_num += 1

        return step_num

    def extract_text_java(self, pdf_path: Path) -> str:
        """
        Extract text using pdf-layout-tool JAR (EXACT replication of current method)
        Returns text or ERROR message
        """
        jar_path = BASE_DIR / PDF_LAYOUT_JAR

        if not jar_path.exists():
            return f"ERROR: JAR not found at {jar_path}"

        try:
            result = subprocess.run(
                ['java', '-jar', str(jar_path), str(pdf_path)],
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode == 0 and result.stdout.strip():
                return result.stdout
            else:
                error_msg = result.stderr[:200] if result.stderr else "No output"
                return f"ERROR: {error_msg}"

        except subprocess.TimeoutExpired:
            return "ERROR: Timeout after 30s"
        except Exception as e:
            return f"ERROR: {e}"

    def extract_text_pdfplumber(self, pdf_path: Path) -> str:
        """Extract text using pdfplumber (EXACT replication)"""
        if not HAVE_PDFPLUMBER:
            return "ERROR: pdfplumber not available"

        try:
            with pdfplumber.open(pdf_path) as pdf:
                all_text = []
                for page in pdf.pages:
                    text = page.extract_text() or ""
                    all_text.append(text)
                return "\n".join(all_text)
        except Exception as e:
            return f"ERROR: {e}"

    def generate_text_files(self, step_num: int) -> int:
        """
        Generate TXT files from PDFs (EXACT replication of pdf_to_text.py process)
        Creates both _java.txt and _pdfplumber.txt files
        """
        ex_lower = self.exchange.lower()

        # Output directories
        lockin_txt_dir = DOWNLOADS_DIR / ex_lower / "pdf" / "lockin" / "txt"
        shp_txt_dir = DOWNLOADS_DIR / ex_lower / "pdf" / "shp" / "txt"

        # Output filenames
        lockin_stem = self.lockin_pdf_path.stem
        shp_stem = self.shp_pdf_path.stem

        # Java TXT files
        self.lockin_java_txt = lockin_txt_dir / f"{lockin_stem}_java.txt"
        self.shp_java_txt = shp_txt_dir / f"{shp_stem}_java.txt"

        # PDFPlumber TXT files
        self.lockin_pdfplumber_txt = lockin_txt_dir / f"{lockin_stem}_pdfplumber.txt"
        self.shp_pdfplumber_txt = shp_txt_dir / f"{shp_stem}_pdfplumber.txt"

        # Process each file type
        files_to_extract = [
            (self.lockin_pdf_path, self.lockin_java_txt, self.lockin_pdfplumber_txt, lockin_txt_dir, "Lock-in"),
            (self.shp_pdf_path, self.shp_java_txt, self.shp_pdfplumber_txt, shp_txt_dir, "SHP"),
        ]

        for pdf_path, java_txt, pdfplumber_txt, txt_dir, doc_type in files_to_extract:
            # Check if Java TXT exists
            if java_txt.exists() and java_txt.stat().st_size > 0:
                self.log_step(step_num, "✓", f"{doc_type} Java TXT exists: {java_txt.relative_to(BASE_DIR)}")
                step_num += 1
            else:
                self.log_step(step_num, "⚙", f"Extracting {doc_type} text with Java...")
                step_num += 1

                if not self.dry_run:
                    txt_dir.mkdir(parents=True, exist_ok=True)

                    # Extract with Java
                    text_java = self.extract_text_java(pdf_path)

                    if text_java.startswith("ERROR"):
                        print(f"\n❌ {text_java}")
                        sys.exit(EXIT_PARSE_ERROR)

                    # Save to file
                    java_txt.write_text(text_java, encoding='utf-8')

                    # Check for scanned image
                    if len(text_java) < 100:
                        print(f"\n  ⚠️  PDF appears to be scanned image (no extractable text): {pdf_path.name}")
                        print(f"     OCR required. File marked for manual review.")
                        self.log_step(step_num, "⚠️", f"Scanned image detected: {java_txt.name}")
                    else:
                        self.log_step(step_num, "✓", f"Java TXT created: {java_txt.relative_to(BASE_DIR)} ({len(text_java)} chars)")
                else:
                    self.log_step(step_num, "✓", f"Java TXT created: {java_txt.relative_to(BASE_DIR)}")

                step_num += 1

            # Check if PDFPlumber TXT exists
            if pdfplumber_txt.exists() and pdfplumber_txt.stat().st_size > 0:
                self.log_step(step_num, "✓", f"{doc_type} PDFPlumber TXT exists: {pdfplumber_txt.relative_to(BASE_DIR)}")
                step_num += 1
            else:
                self.log_step(step_num, "⚙", f"Extracting {doc_type} text with PDFPlumber...")
                step_num += 1

                if not self.dry_run:
                    txt_dir.mkdir(parents=True, exist_ok=True)

                    # Extract with PDFPlumber
                    text_pdfplumber = self.extract_text_pdfplumber(pdf_path)

                    if text_pdfplumber.startswith("ERROR"):
                        print(f"\n⚠️  PDFPlumber extraction failed: {text_pdfplumber}")
                        # Don't exit - Java extraction is primary

                    # Save to file
                    pdfplumber_txt.write_text(text_pdfplumber, encoding='utf-8')
                    self.log_step(step_num, "✓", f"PDFPlumber TXT created: {pdfplumber_txt.relative_to(BASE_DIR)} ({len(text_pdfplumber)} chars)")
                else:
                    self.log_step(step_num, "✓", f"PDFPlumber TXT created: {pdfplumber_txt.relative_to(BASE_DIR)}")

                step_num += 1

        return step_num

    def generate_png(self, step_num: int) -> int:
        """
        Generate PNG from PDF (replicates current PNG generation)
        NSE: Extract LAST page
        BSE: Extract ALL pages and stitch
        """
        ex_config = EXCHANGES[self.exchange]
        ex_lower = self.exchange.lower()

        png_dir = DOWNLOADS_DIR / ex_lower / "pdf" / "lockin" / "png"
        png_filename = self.lockin_pdf_path.stem + ".png"
        self.lockin_png_path = png_dir / png_filename

        if self.lockin_png_path.exists():
            self.log_step(step_num, "✓", f"PNG exists: {self.lockin_png_path.relative_to(BASE_DIR)}")
            return step_num + 1

        self.log_step(step_num, "⚙", f"Generating PNG from PDF ({ex_config['png_pages']} page(s))...")
        step_num += 1

        if not self.dry_run:
            if not HAVE_FITZ:
                print("\n❌ Error: PyMuPDF (fitz) not installed. Run: pip install pymupdf")
                sys.exit(EXIT_PARSE_ERROR)

            png_dir.mkdir(parents=True, exist_ok=True)

            try:
                doc = fitz.open(str(self.lockin_pdf_path))

                if ex_config['png_pages'] == 'last':
                    # NSE: Extract last page only
                    page = doc[-1]
                    pix = page.get_pixmap(dpi=150)
                    pix.save(str(self.lockin_png_path))
                    self.log_step(step_num, "✓", f"PNG generated (last page): {self.lockin_png_path.relative_to(BASE_DIR)}")

                elif ex_config['png_pages'] == 'all':
                    # BSE: Extract all pages and stitch
                    if not HAVE_PIL:
                        print("\n❌ Error: Pillow not installed. Run: pip install Pillow")
                        sys.exit(EXIT_PARSE_ERROR)

                    images = []
                    for page in doc:
                        pix = page.get_pixmap(dpi=150)
                        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                        images.append(img)

                    if len(images) > 1:
                        # Stitch vertically
                        total_height = sum(i.height for i in images)
                        max_width = max(i.width for i in images)
                        stitched = Image.new('RGB', (max_width, total_height))

                        y_offset = 0
                        for img in images:
                            stitched.paste(img, (0, y_offset))
                            y_offset += img.height

                        stitched.save(str(self.lockin_png_path))
                        self.log_step(step_num, "✓", f"PNG generated (stitched {len(images)} pages): {self.lockin_png_path.relative_to(BASE_DIR)}")
                    elif len(images) == 1:
                        images[0].save(str(self.lockin_png_path))
                        self.log_step(step_num, "✓", f"PNG generated (1 page): {self.lockin_png_path.relative_to(BASE_DIR)}")
                    else:
                        print("\n❌ Error: PDF has no pages")
                        sys.exit(EXIT_PARSE_ERROR)

                doc.close()

            except Exception as e:
                print(f"\n❌ Error generating PNG: {e}")
                sys.exit(EXIT_PARSE_ERROR)
        else:
            self.log_step(step_num, "✓", f"PNG generated: {self.lockin_png_path.relative_to(BASE_DIR)}")

        return step_num + 1

    def connect_database(self, step_num: int) -> int:
        """Establish database connection"""
        if self.no_db:
            self.log_step(step_num, "⊗", "Database connection skipped (--nodb flag)")
            return step_num + 1

        self.log_step(step_num, "⚙", "Connecting to database...")
        step_num += 1

        if not self.dry_run:
            conn = db.get_db_connection()
            if conn:
                self.log_step(step_num, "✓", "Database connection established")
                conn.close()
            else:
                print("\n❌ Error: Database connection failed")
                sys.exit(EXIT_DB_ERROR)
        else:
            self.log_step(step_num, "✓", "Database connection established")

        return step_num + 1

    def get_master_info(self, step_num: int) -> int:
        """Get allotment_date and declared_total from sme_ipo_master"""
        self.log_step(step_num, "⚙", f"Querying sme_ipo_master for {self.unique_symbol}...")
        step_num += 1

        if not self.dry_run and not self.no_db:
            master_data = get_master_data(self.unique_symbol)

            if master_data:
                self.allotment_date, self.declared_total, self.anchor_letter_url = master_data
                self.log_step(step_num, "✓", f"Master data found: Allotment={self.allotment_date}, Declared={self.declared_total:,}")
            else:
                print(f"\n⚠️  Warning: No master data found for {self.unique_symbol} in sme_ipo_master")
                print("   Continuing without allotment_date and declared_total (some validations will be skipped)")
                self.allotment_date = None
                self.declared_total = None
                self.anchor_letter_url = None
        else:
            self.log_step(step_num, "✓", f"Master data retrieved (dry-run/nodb mode)")
            self.allotment_date = None
            self.declared_total = 10000000  # Dummy for dry-run
            self.anchor_letter_url = None

        step_num += 1
        return step_num

    def parse_files(self, step_num: int) -> int:
        """Parse lock-in and SHP TXT files (Step 2)"""
        self.log_step(step_num, "⚙", "Parsing lock-in TXT file...")
        step_num += 1

        if not self.dry_run:
            try:
                self.lockin_data = parse_lockin_file(self.lockin_java_txt, self.allotment_date)
                self.log_step(step_num, "✓", f"Lock-in parsed: {len(self.lockin_data.rows)} rows, Total={self.lockin_data.computed_total:,}, Locked={self.lockin_data.locked_total:,}")
            except Exception as e:
                print(f"\n❌ Error parsing lock-in file: {e}")
                sys.exit(EXIT_PARSE_ERROR)
        else:
            self.log_step(step_num, "✓", "Lock-in parsed (dry-run mode)")
            self.lockin_data = None

        step_num += 1

        self.log_step(step_num, "⚙", "Parsing SHP TXT file...")
        step_num += 1

        if not self.dry_run:
            try:
                # DUAL-HINT STRATEGY: Pass BOTH declared total (from DB) and computed total (from PDF)
                # Priority: computed_total (most reliable) → declared_total (may have inaccuracies) → largest number
                declared_total = self.declared_total  # From sme_ipo_master (may have inaccuracies)
                computed_total = self.lockin_data.computed_total if self.lockin_data else None  # From lock-in PDF (most reliable)
                known_locked = self.lockin_data.locked_total if self.lockin_data else None

                self.shp_data = parse_shp_file(
                    self.shp_java_txt,
                    known_total=declared_total,
                    total_hint_computed=computed_total,
                    known_locked=known_locked
                )
                self.log_step(step_num, "✓", f"SHP parsed: Total={self.shp_data.total_shares:,}, Promoter={self.shp_data.promoter_shares:,}, Public={self.shp_data.public_shares:,}")
            except Exception as e:
                print(f"\n❌ Error parsing SHP file: {e}")
                sys.exit(EXIT_PARSE_ERROR)
        else:
            self.log_step(step_num, "✓", "SHP parsed (dry-run mode)")
            self.shp_data = None

        step_num += 1
        return step_num

    def validate_data(self, step_num: int) -> int:
        """Validate extracted data against rules (Step 2)"""
        self.log_step(step_num, "⚙", "Running validation rules...")
        step_num += 1

        if not self.dry_run:
            # Run validations
            if not self.declared_total:
                print("\n⚠️  Warning: No declared_total from master, RULE2 will be skipped")
                # Set a dummy value to avoid errors
                self.declared_total = self.lockin_data.computed_total if self.lockin_data else 0

            self.validations = validate_all_rules(
                self.lockin_data,
                self.shp_data,
                self.declared_total,
                self.anchor_letter_url
            )

            # Check results
            passed_count = sum(1 for v in self.validations if v.passed)
            total_count = len(self.validations)
            self.all_rules_passed = (passed_count == total_count)

            self.log_step(step_num, "✓" if self.all_rules_passed else "⚠️", f"Validation: {passed_count}/{total_count} rules passed")

            # Show individual results
            for validation in self.validations:
                icon = "  ✓" if validation.passed else "  ✗"
                print(f"{icon} {validation.rule_id}: {validation.message}")

        else:
            self.log_step(step_num, "✓", "Validation completed (dry-run mode)")
            self.validations = []
            self.all_rules_passed = True

        step_num += 1
        return step_num

    def save_to_database(self, step_num: int) -> int:
        """Save processing results to database"""
        if self.no_db or self.dry_run:
            self.log_step(step_num, "⊗", "Database save skipped (--nodb or --dryrun)")
            return step_num + 1

        self.log_step(step_num, "⚙", "Saving results to database...")
        step_num += 1

        # Create ProcessingStatus object
        status = ProcessingStatus(
            unique_symbol=self.unique_symbol,
            exchange=self.exchange,
            file_name=self.file_name,
            lockin_data=self.lockin_data,
            shp_data=self.shp_data,
            allotment_date=self.allotment_date,
            declared_total=self.declared_total,
            validations=self.validations,
            all_rules_passed=self.all_rules_passed,
            lockin_pdf=str(self.lockin_pdf_path),
            shp_pdf=str(self.shp_pdf_path),
            lockin_txt_java=str(self.lockin_java_txt),
            shp_txt_java=str(self.shp_java_txt),
            lockin_png=str(self.lockin_png_path),
        )

        processing_log_id = save_processing_log(status)

        if processing_log_id:
            self.processing_log_id = processing_log_id  # Store for finalization
            self.log_step(step_num, "✓", f"Saved to database (ID={processing_log_id})")
        else:
            print("\nERROR saving to database")
            sys.exit(EXIT_DB_ERROR)

        step_num += 1
        return step_num

    def finalize_processing(self, step_num: int) -> int:
        """Finalize files by moving to finalized/ folders"""
        # Check if can finalize
        can_finalize, reason = check_can_finalize(
            self.all_rules_passed,
            'VALIDATING'  # Status before finalization
        )

        if not can_finalize:
            # Include specific failed rules with messages in the error message
            failed_validations = [v for v in self.validations if not v.passed]
            if failed_validations:
                failed_details = [f"{v.rule_id}: {v.message}" for v in failed_validations]
                skip_reason = f"Finalization skipped: {reason} | {' | '.join(failed_details)}"
            else:
                skip_reason = f"Finalization skipped: {reason}"
            self.log_step(step_num, "⊗", skip_reason)
            if not self.no_db and self.processing_log_id:
                update_processing_log_error(self.processing_log_id, skip_reason)
            return step_num + 1

        if self.no_db:
            self.log_step(step_num, "⊗", "Finalization skipped (--nodb)")
            return step_num + 1

        if not self.movefiles:
            skip_reason = "Finalization skipped (--movefiles not enabled)"
            self.log_step(step_num, "⊗", skip_reason)
            if not self.no_db and self.processing_log_id:
                update_processing_log_error(self.processing_log_id, skip_reason)
            return step_num + 1

        self.log_step(step_num, "⚙", "Finalizing files...")
        step_num += 1

        # Finalize files
        success = finalize_files(
            lockin_pdf=self.lockin_pdf_path,
            shp_pdf=self.shp_pdf_path,
            lockin_txt_java=self.lockin_java_txt,
            shp_txt_java=self.shp_java_txt,
            lockin_png=self.lockin_png_path,
            exchange=self.exchange,
            processing_log_id=self.processing_log_id,
            dryrun=self.dry_run
        )

        if success:
            if not self.dry_run:
                self.log_step(step_num, "✓", "Files moved to finalized/ and database updated")
            else:
                self.log_step(step_num, "✓", "Finalization preview shown (dry-run)")
        else:
            print("\nERROR during finalization (files restored)")
            sys.exit(EXIT_DB_ERROR)

        step_num += 1
        return step_num

    def process_folder(self) -> int:
        """Process all files in the exchange folder"""
        from pathlib import Path

        # Get folder path
        folder = Path(f"downloads/{self.exchange.lower()}/pdf/lockin")

        if not folder.exists():
            print(f"\n❌ Folder not found: {folder}")
            return EXIT_VALIDATION_FAILED

        # Get all PDF files (pattern depends on exchange)
        if self.exchange == "BSE":
            # BSE files: SYMBOL-Annexure-I.pdf
            pdf_files = sorted(folder.glob("*-Annexure-I.pdf"))
        else:
            # NSE files: SYMBOL-CML*.pdf or just SYMBOL.pdf
            pdf_files = sorted(folder.glob("*.pdf"))

        if not pdf_files:
            print(f"\n❌ No lock-in PDF files found in {folder}")
            return EXIT_VALIDATION_FAILED

        print(f"\n📁 FOLDER MODE: Processing {len(pdf_files)} files from {self.exchange}\n")

        # Process each file
        success_count = 0
        error_count = 0

        for pdf_file in pdf_files:
            print(f"\n{'='*70}")
            print(f"Processing: {pdf_file.name}")
            print('='*70)

            # Create new processor for this file
            import argparse
            args = argparse.Namespace(
                file_name=pdf_file.name,
                nse=(self.exchange == "NSE"),
                bse=(self.exchange == "BSE"),
                dryrun=self.dry_run,
                nodb=self.no_db,
                verbose=self.verbose,
                GEMAPPROVED=self.gemini_approved,
                movefiles=self.movefiles,
                manual_override=None,
                reason=None
            )

            processor = IPOProcessor(args)
            exit_code = processor.process()

            if exit_code == EXIT_SUCCESS:
                success_count += 1
            else:
                error_count += 1

        # Print folder summary
        print(f"\n{'='*70}")
        print("FOLDER PROCESSING COMPLETE")
        print('='*70)
        print(f"Total files: {len(pdf_files)}")
        print(f"  ✓ Success: {success_count}")
        print(f"  ✗ Errors:  {error_count}")
        print('='*70)

        return EXIT_SUCCESS

    def process(self) -> int:
        """Main processing pipeline"""
        self.print_header()

        step_num = 1

        if self.file_name:
            # ===================================================================
            # STEP 1: File preparation
            # ===================================================================
            step_num = self.validate_files(step_num)
            step_num = self.generate_text_files(step_num)
            step_num = self.generate_png(step_num)
            step_num = self.connect_database(step_num)

            # ===================================================================
            # STEP 2: Parse and validate
            # ===================================================================
            step_num = self.get_master_info(step_num)
            step_num = self.parse_files(step_num)
            step_num = self.validate_data(step_num)
            step_num = self.save_to_database(step_num)

            # ===================================================================
            # STEP 3: Finalization
            # ===================================================================
            step_num = self.finalize_processing(step_num)

        else:
            # ===================================================================
            # FOLDER MODE: Process all files in the exchange folder
            # ===================================================================
            return self.process_folder()

        # ===================================================================
        # Summary
        # ===================================================================
        print("\n" + "=" * 70)
        if self.all_rules_passed:
            if not self.dry_run and not self.no_db:
                print("SUCCESS PROCESSING COMPLETE - Files finalized")
            else:
                print("SUCCESS ALL VALIDATIONS PASSED")
        else:
            failed = [v.rule_id for v in self.validations if not v.passed]
            print(f"WARN VALIDATION ISSUES - Failed rules: {', '.join(failed)}")
        print("=" * 70)

        if self.dry_run:
            print("\nNote: Dry-run mode - shown above what would happen")
        elif self.lockin_data and self.shp_data:
            print(f"\nExtraction Summary:")
            print(f"  • Lock-in Total:   {self.lockin_data.computed_total:,} shares")

            # Calculate percentages with zero checks
            locked_pct = (self.lockin_data.locked_total/self.lockin_data.computed_total*100) if self.lockin_data.computed_total > 0 else 0
            promoter_pct = (self.shp_data.promoter_shares/self.shp_data.total_shares*100) if self.shp_data.total_shares > 0 else 0
            public_pct = (self.shp_data.public_shares/self.shp_data.total_shares*100) if self.shp_data.total_shares > 0 else 0

            print(f"  • Lock-in Locked:  {self.lockin_data.locked_total:,} shares ({locked_pct:.1f}%)")
            print(f"  • Lock-in Free:    {self.lockin_data.free_total:,} shares")
            print(f"  • SHP Promoter:    {self.shp_data.promoter_shares:,} shares ({promoter_pct:.1f}%)")
            print(f"  • SHP Public:      {self.shp_data.public_shares:,} shares ({public_pct:.1f}%)")

        if self.all_rules_passed and not self.dry_run and not self.no_db:
            print(f"\nFiles moved to: finalized/")
            print(f"Database ID: {self.processing_log_id}")
            print(f"Status: FINALIZED")
        elif not self.all_rules_passed:
            print("\nWARN Fix validation issues before finalization")

        return EXIT_SUCCESS


def main():
    parser = argparse.ArgumentParser(
        description='IPO Lock-in Expiry Processor v2.0',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Single file processing
  python app_new.py AAKAAR-CML68761.pdf --nse --dryrun
  python app_new.py 544324-CITICHEM-Annexure-I.pdf --bse --GEMAPPROVED

  # Process all files in exchange folder
  python app_new.py --bse --dryrun
  python app_new.py --nse
        """
    )

    # Positional argument
    parser.add_argument('file_name', nargs='?',
                       help='Lock-in PDF filename (optional - omit to process all files)')

    # Exchange (mutually exclusive, required)
    exchange_group = parser.add_mutually_exclusive_group(required=True)
    exchange_group.add_argument('--nse', action='store_true', help='Process NSE exchange')
    exchange_group.add_argument('--bse', action='store_true', help='Process BSE exchange')

    # Processing flags
    parser.add_argument('--GEMAPPROVED', action='store_true',
                       help='Perform paid GEMINI extraction (requires API key)')
    parser.add_argument('--dryrun', action='store_true',
                       help='Simulate without actual operations (verbose mode)')
    parser.add_argument('--nodb', action='store_true',
                       help='Skip database operations')
    parser.add_argument('--verbose', action='store_true',
                       help='Detailed logging')
    parser.add_argument('--movefiles', action='store_true',
                       help='Enable file movement to finalized/ folder (disabled by default)')

    # Manual override
    parser.add_argument('--manual_override', type=str,
                       help='Override rules (e.g., RULE3,RULE6)')
    parser.add_argument('--reason', type=str,
                       help='Reason for manual override (required with --manual_override)')

    args = parser.parse_args()

    # Validate manual override
    if args.manual_override and not args.reason:
        parser.error("--manual_override requires --reason")

    # Run processor
    processor = IPOProcessor(args)
    exit_code = processor.process()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
