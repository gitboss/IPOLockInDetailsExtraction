-- IPO Lock-in Processor v2.0 - Database Schema
-- Clean table design with proper normalization

-- ============================================================================
-- Processing Log Table
-- ============================================================================
-- Tracks each file processing attempt with all extraction results

CREATE TABLE IF NOT EXISTS ipo_processing_log (
    id INT AUTO_INCREMENT PRIMARY KEY,

    -- Identification
    unique_symbol VARCHAR(50) NOT NULL,
    exchange ENUM('BSE', 'NSE') NOT NULL,
    file_name VARCHAR(255) NOT NULL,

    -- Processing status
    status ENUM('NEW', 'PARSING', 'VALIDATING', 'FINALIZED', 'FAILED') NOT NULL DEFAULT 'NEW',

    -- File paths
    lockin_pdf_path VARCHAR(500),
    shp_pdf_path VARCHAR(500),
    lockin_txt_java_path VARCHAR(500),
    lockin_txt_pdfplumber_path VARCHAR(500),
    shp_txt_java_path VARCHAR(500),
    shp_txt_pdfplumber_path VARCHAR(500),
    lockin_png_path VARCHAR(500),

    -- Lock-in extraction results
    computed_total BIGINT,           -- Sum of all shares from rows
    locked_total BIGINT,             -- Sum of locked shares
    free_total BIGINT,               -- Sum of free shares

    -- SHP extraction results
    shp_total_shares BIGINT,         -- Total from SHP
    shp_locked_shares BIGINT,        -- Locked from SHP
    shp_promoter_shares BIGINT,      -- Promoter shareholding
    shp_public_shares BIGINT,        -- Public shareholding
    shp_others_shares BIGINT,        -- Others (C1+C2+C3+...)

    -- From sme_ipo_master (copied for quick access)
    allotment_date DATE,
    declared_total BIGINT,           -- post_issue_shares from master
    anchor_letter_url VARCHAR(500),  -- For RULE6 validation

    -- Validation results (stored as JSON for flexibility)
    validation_results JSON,         -- {"RULE1": {"passed": true, "message": "..."}, ...}
    all_rules_passed BOOLEAN DEFAULT FALSE,
    failed_rules TEXT,               -- Comma-separated list of failed rules

    -- Processing metadata
    processed_at DATETIME,
    finalized_at DATETIME,
    error_message TEXT,

    -- GEMINI OCR flag (reuses sme_ipo_lockin_ocr cache)
    gemini_extracted BOOLEAN DEFAULT FALSE,

    -- Indexes
    INDEX idx_unique_symbol (unique_symbol),
    INDEX idx_status (status),
    INDEX idx_exchange (exchange),
    INDEX idx_all_rules_passed (all_rules_passed),

    -- Ensure one processing record per file
    UNIQUE KEY unique_file (exchange, file_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ============================================================================
-- Lock-in Rows Table
-- ============================================================================
-- Detail rows extracted from lock-in PDF

CREATE TABLE IF NOT EXISTS ipo_lockin_rows (
    id INT AUTO_INCREMENT PRIMARY KEY,
    processing_log_id INT NOT NULL,

    -- Share details
    shares BIGINT NOT NULL,
    distinctive_from BIGINT,
    distinctive_to BIGINT,
    security_type VARCHAR(100),

    -- Lock-in dates
    lockin_date_from DATE,
    lockin_date_to DATE,

    -- Other fields
    share_form VARCHAR(100),

    -- Status and bucket
    status ENUM('LOCKED', 'FREE') NOT NULL,
    bucket ENUM('3_year_plus', '2_year_plus', '1_year_plus', '1_year_minus', 'anchor_90', 'anchor_30', 'free') DEFAULT 'free',

    -- Row order (for maintaining original sequence)
    row_order INT,

    -- Foreign key
    FOREIGN KEY (processing_log_id) REFERENCES ipo_processing_log(id) ON DELETE CASCADE,

    -- Indexes
    INDEX idx_processing_log (processing_log_id),
    INDEX idx_status (status),
    INDEX idx_bucket (bucket)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ============================================================================
-- Notes about existing tables (DO NOT DROP/MODIFY)
-- ============================================================================

-- sme_ipo_master
-- - Contains: allotment_date, post_issue_shares (declared_total), anchor_letter_url
-- - Used for: RULE6 validation, date calculations

-- sme_ipo_lockin_ocr
-- - Contains: GEMINI extraction cache (100+ files)
-- - Reuse for: GEMINI results when --GEMAPPROVED flag is used
-- - Structure: TBD based on existing schema


-- ============================================================================
-- Sample Queries
-- ============================================================================

-- Get processing status for a symbol
-- SELECT * FROM ipo_processing_log WHERE unique_symbol = 'BSE:544324';

-- Get all lock-in rows for a processing
-- SELECT * FROM ipo_lockin_rows WHERE processing_log_id = 1 ORDER BY row_order;

-- Get symbols that passed all rules
-- SELECT unique_symbol, exchange, file_name
-- FROM ipo_processing_log
-- WHERE all_rules_passed = TRUE AND status = 'FINALIZED';

-- Get symbols with specific failed rules
-- SELECT unique_symbol, failed_rules, error_message
-- FROM ipo_processing_log
-- WHERE all_rules_passed = FALSE
-- ORDER BY processed_at DESC;
