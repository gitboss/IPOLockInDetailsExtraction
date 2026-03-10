-- ============================================================
-- Bucket ENUM Migration Script
-- Updates ipo_lockin_rows.bucket column to new bucket names
-- 
-- Run this AFTER deploying Python/PHP code changes
-- ============================================================

-- Step 1: Add NEW enum values (can't remove old ones yet)
ALTER TABLE ipo_lockin_rows 
MODIFY COLUMN bucket ENUM(
    '3+YEARS',      -- old (keep temporarily)
    '2+YEARS',      -- old
    '1+YEAR',       -- old
    'ANCHOR_90DAYS',-- old
    'ANCHOR_30DAYS',-- old
    'FREE',         -- old
    '3_year_plus',  -- NEW
    '2_year_plus',  -- NEW
    '1_year_plus',  -- NEW
    '1_year_minus', -- NEW
    'anchor_90',    -- NEW
    'anchor_30',    -- NEW
    'free'          -- NEW
) DEFAULT 'free';

-- Step 2: Update existing rows - map old values to new values
UPDATE ipo_lockin_rows SET bucket = '3_year_plus' WHERE bucket = '3+YEARS';
UPDATE ipo_lockin_rows SET bucket = '2_year_plus' WHERE bucket = '2+YEARS';
UPDATE ipo_lockin_rows SET bucket = '1_year_plus' WHERE bucket = '1+YEAR';
UPDATE ipo_lockin_rows SET bucket = 'anchor_90' WHERE bucket = 'ANCHOR_90DAYS';
UPDATE ipo_lockin_rows SET bucket = 'anchor_30' WHERE bucket = 'ANCHOR_30DAYS';
UPDATE ipo_lockin_rows SET bucket = 'free' WHERE bucket = 'FREE';

-- Step 3: Remove OLD enum values (now that no rows use them)
ALTER TABLE ipo_lockin_rows 
MODIFY COLUMN bucket ENUM(
    '3_year_plus',
    '2_year_plus',
    '1_year_plus',
    '1_year_minus',
    'anchor_90',
    'anchor_30',
    'free'
) DEFAULT 'free';

-- Step 4: Verify migration
SELECT bucket, COUNT(*) as count 
FROM ipo_lockin_rows 
GROUP BY bucket 
ORDER BY bucket;

-- Expected output:
-- anchor_30      | XXX
-- anchor_90      | XXX
-- 1_year_minus   | XXX
-- 1_year_plus    | XXX
-- 2_year_plus    | XXX
-- 3_year_plus    | XXX
-- free           | XXX
