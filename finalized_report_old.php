<?php
// VERSION: 2026-03-07-v23
$REPORT_VERSION = "finalized_report.php v23 (2026-03-07)";
// Merged report + API - single file, no external dependency
// v11: Fixed reconcile button condition (locked_forever != 1 catches both 0 and null)
// v12: Reconcile button now actually GENERATES candidates via API, not just fetches existing ones
// v13: Reconcile button also shows when total_match=0 or shp_match=0 (not just when SHP data is missing)
// v14: Added gemini_split_match check, removed locked_forever check (show button for any validation error)
// v15: Require hasData before showing reconcile button (prevent showing on empty records)
// v16: FIX: Check gemini_split_match === false (PHP converts 0 to boolean false)

$env_path = __DIR__ . '/.env';
$env = [];
if (file_exists($env_path)) {
  foreach (file($env_path, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES) as $line) {
    $line = trim($line);
    if ($line === '' || $line[0] === '#')
      continue;
    if (strpos($line, '=') === false)
      continue;
    [$k, $v] = explode('=', $line, 2);
    $env[trim($k)] = trim($v);
  }
}

$recon_include = __DIR__ . '/reconciliation_phase1/finalized_report_reconciliation_include.php';
if (file_exists($recon_include)) {
  require_once $recon_include;
}

/**
 * Factory: create a PDO from an env array.
 * Pure enough to be called with a test env in unit tests.
 */
function make_pdo(array $env): PDO
{
  return new PDO(
    'mysql:host=' . ($env['DB_HOST'] ?? 'localhost') .
    ';dbname=' . ($env['DB_NAME'] ?? '') . ';charset=utf8mb4',
    $env['DB_USER'] ?? '',
    $env['DB_PASSWORD'] ?? '',
    [
      PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
      PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC
    ]
  );
}

// json_path_for_scrip() removed — V2 has no JSON files on disk.

/**
 * Compute days_locked and lock_bucket for a row (matches insert_unlock.py logic)
 * Returns: [days_locked (int|null), lock_bucket (string)]
 */
function compute_lock_bucket($row_class, $lock_from, $lock_upto, $allotment_date, $type_raw)
{
  // Free rows or no upto date -> free bucket
  if ($row_class === 'free' || empty($lock_upto)) {
    return [null, 'free'];
  }

  // Determine start date (lock_from or allotment_date fallback)
  $start_date = !empty($lock_from) ? $lock_from : $allotment_date;
  if (empty($start_date)) {
    return [null, 'unknown'];
  }

  try {
    $from = new DateTime($start_date);
    $to = new DateTime($lock_upto);
    $days = (int) $from->diff($to)->days;

    // Sanity check
    if ($days < 0 || $days > 9999) {
      return [$days, 'unknown'];
    }

    // Match Python BUCKETS exactly (checked for ALL rows, not just anchor class)
    if ($days >= 15 && $days <= 45) {
      return [$days, 'anchor_30'];
    }
    if ($days >= 75 && $days <= 105) {
      return [$days, 'anchor_90'];
    }
    if ($days >= 330 && $days <= 400) {
      return [$days, '1_year'];
    }
    if ($days >= 690 && $days <= 780) {
      return [$days, '2_year'];
    }
    if ($days >= 1055 && $days <= 1145) {
      return [$days, '3_year'];
    }

    return [$days, 'unknown'];
  } catch (Exception $e) {
    return [null, 'unknown'];
  }
}

function candidate_promotability(array $candidate): array
{
  $reasons = [];
  $payloadRaw = $candidate['payload_json'] ?? null;
  $payload = [];
  if (is_string($payloadRaw)) {
    $payload = json_decode($payloadRaw, true) ?: [];
  } elseif (is_array($payloadRaw)) {
    $payload = $payloadRaw;
  }

  $header = is_array($payload['header'] ?? null) ? $payload['header'] : [];
  $rows = is_array($payload['rows'] ?? null) ? $payload['rows'] : [];
  if (empty($rows)) {
    $reasons[] = 'No lock-in rows';
  }

  $rowSum = 0;
  $lockedSum = 0;
  foreach ($rows as $idx => $r) {
    $shares = (int) ($r['shares'] ?? 0);
    $rowClass = strtolower(trim((string) ($r['row_class'] ?? '')));
    $bucket = strtolower(trim((string) ($r['lock_bucket'] ?? '')));
    $rowSum += $shares;
    if ($rowClass !== 'free') {
      $lockedSum += $shares;
    }
    if ($bucket === '' || $bucket === null) {
      $reasons[] = 'Row ' . ($idx + 1) . ': missing bucket';
    } elseif ($rowClass === 'free' && $bucket !== 'free') {
      $reasons[] = 'Row ' . ($idx + 1) . ': free row bucket not free';
    }
    // Note: 'unknown' is a valid bucket type (only null/empty is invalid)
  }
  $freeSum = $rowSum - $lockedSum;
  if (($lockedSum + $freeSum) !== $rowSum) {
    $reasons[] = 'free+locked mismatch';
  }

  $computed = $header['computed_total'] ?? null;
  if ($computed === null || $computed === '') {
    $reasons[] = 'Missing lock-in total';
  } elseif ((int) $computed !== (int) $rowSum) {
    $reasons[] = 'Lock-in rows total mismatch';
  }

  $shpTotal = $header['total_shares'] ?? null;
  $shpLocked = $header['shp_locked_total'] ?? null;
  $promoter = $header['promoter_shares'] ?? null;
  $public = $header['public_shares'] ?? null;
  $other = $header['other_shares'] ?? 0;

  if ($shpTotal === null || $shpTotal === '') {
    $reasons[] = 'Missing SHP total';
  } elseif ((int) $shpTotal !== (int) $rowSum) {
    $reasons[] = 'SHP total != lock-in total';
  }

  if ($shpLocked === null || $shpLocked === '') {
    $reasons[] = 'Missing SHP locked';
  } elseif ((int) $shpLocked !== (int) $lockedSum) {
    $reasons[] = 'SHP locked != lock-in locked';
  }

  if ($promoter === null || $public === null || $shpTotal === null || $shpTotal === '') {
    $reasons[] = 'Missing SHP split values';
  } else {
    $splitSum = (int) $promoter + (int) $public + (int) $other;
    if ($splitSum !== (int) $shpTotal) {
      $reasons[] = 'Promoter+Public+Other != SHP total';
    }
  }

  $status = (string) ($candidate['status'] ?? '');
  $isValid = (int) ($candidate['is_valid'] ?? 0);
  if ($status !== 'VALIDATED' || $isValid !== 1) {
    $reasons[] = "Candidate status is $status";
  }

  $notes = $candidate['validation_notes'] ?? null;
  if ($notes) {
    $parsed = is_string($notes) ? json_decode($notes, true) : $notes;
    if (is_array($parsed)) {
      foreach ($parsed as $n) {
        if (is_string($n) && $n !== '')
          $reasons[] = $n;
      }
    }
  }

  $uniq = [];
  foreach ($reasons as $r) {
    $uniq[$r] = true;
  }
  $finalReasons = array_keys($uniq);
  return [
    'promotable' => count($finalReasons) === 0,
    'reasons' => $finalReasons,
  ];
}

// ── POST / AJAX API handler (exits before HTML) ──────────────────────────────
if ($_SERVER['REQUEST_METHOD'] === 'POST') {
  header('Content-Type: application/json; charset=utf-8');
  try {
    $pdo = make_pdo($env);
    $action = $_POST['action'] ?? '';

    if (function_exists('recon_phase1_handle_action') && recon_phase1_handle_action($pdo, $action)) {
      exit;
    }

    // ── V2: get_scrip_edit — load edit form data from DB (no JSON file) ──
    if ($action === 'get_json') {
      // V2: read from DB, not from disk. Action name kept for JS compat.
      $id = (int) ($_POST['scrip_id'] ?? 0);
      $stmt = $pdo->prepare(
        'SELECT d.id, d.declared_total, d.shp_locked_total, d.computed_total, d.png_files,
                d.exchange, d.symbol, d.pdf_file
         FROM sme_ipo_lockin_details d WHERE d.id=?'
      );
      $stmt->execute([$id]);
      $row = $stmt->fetch();
      if (!$row)
        throw new Exception('Scrip not found');
      $r2 = $pdo->prepare('SELECT shares, lock_upto AS date, lock_from AS date_from, type_raw, row_class FROM sme_ipo_lockin_rows WHERE scrip_id=?');
      $r2->execute([$id]);
      $rows = $r2->fetchAll();
      $png_files = json_decode($row['png_files'] ?? '[]', true) ?? [];
      echo json_encode([
        'declared_total' => $row['declared_total'] ? (int) $row['declared_total'] : null,
        'shp_locked_total' => $row['shp_locked_total'] ? (int) $row['shp_locked_total'] : null,
        'computed_total' => $row['computed_total'] ? (int) $row['computed_total'] : null,
        'png_files' => $png_files,
        'rows' => $rows,
      ], JSON_UNESCAPED_UNICODE);
      exit;
    }

    // ── V2: save_db — write edits directly to DB, set manual_lock=1 ────────
    if ($action === 'save_db') {
      $id = (int) ($_POST['scrip_id'] ?? 0);
      $payload = json_decode($_POST['json_data'] ?? '', true);
      if ($payload === null)
        throw new Exception('Invalid JSON payload');

      $declared = isset($payload['declared_total']) ? (int) $payload['declared_total'] : null;
      $shp = isset($payload['shp_locked_total']) ? (int) $payload['shp_locked_total'] : null;
      $computed = array_sum(array_column($payload['rows'] ?? [], 'shares'));

      // Fetch allotment_date for days_locked computation
      $stmt = $pdo->prepare('
        SELECT d.exchange, d.exchange_code, d.symbol, m.allotment_date
        FROM sme_ipo_lockin_details d
        LEFT JOIN sme_ipo_master m
          ON (d.exchange = "BSE" AND CAST(m.bse_script_code AS CHAR) COLLATE utf8mb4_unicode_ci = d.exchange_code COLLATE utf8mb4_unicode_ci)
          OR (d.exchange = "NSE" AND UPPER(m.nse_symbol) COLLATE utf8mb4_unicode_ci = d.symbol COLLATE utf8mb4_unicode_ci)
        WHERE d.id=?
      ');
      $stmt->execute([$id]);
      $scrip = $stmt->fetch(PDO::FETCH_ASSOC);
      if (!$scrip)
        throw new Exception('Scrip not found');
      $allotment_date = $scrip['allotment_date'] ?? null;

      $pdo->beginTransaction();
      // Update header row
      $upd = $pdo->prepare(
        'UPDATE sme_ipo_lockin_details
         SET declared_total=?, shp_locked_total=?, computed_total=?,
             manual_lock=1, manual_locked_at=NOW(),
             status=IF(status NOT IN ("MANUAL_LOCKED"), "MANUAL_LOCKED", status),
             processed_at=NOW()
         WHERE id=?'
      );
      $upd->execute([$declared, $shp, $computed, $id]);

      // Replace rows
      $pdo->prepare('DELETE FROM sme_ipo_lockin_rows WHERE scrip_id=?')->execute([$id]);
      $ins = $pdo->prepare(
        'INSERT INTO sme_ipo_lockin_rows (scrip_id,shares,lock_upto,lock_from,days_locked,lock_bucket,type_raw,row_class)
         VALUES (?,?,?,?,?,?,?,?)'
      );
      $debug_rows = [];
      foreach ($payload['rows'] ?? [] as $r) {
        // Handle both field name conventions: Python (to_date/from_date) and JS (date/date_from)
        // This ensures backward compatibility with existing code while supporting Python parsing
        $lock_upto = ($r['date'] ?? $r['to_date'] ?? '') ?: null;
        $lock_from_val = ($r['date_from'] ?? $r['from_date'] ?? '') ?: null;

        // Compute days_locked and lock_bucket for this row
        [$days, $bucket] = compute_lock_bucket(
          $r['row_class'] ?? 'locked',
          $lock_from_val ?? '',
          $lock_upto ?? '',
          $allotment_date,
          $r['type_raw'] ?? ''
        );

        $ins->execute([
          $id,
          (int) ($r['shares'] ?? 0),
          $lock_upto,
          $lock_from_val,
          $days,
          $bucket,
          substr($r['type_raw'] ?? '', 0, 100),
          $r['row_class'] ?? 'locked',
        ]);
      }
      $pdo->commit();

      echo json_encode([
        'ok' => true,
        'computed_total' => $computed
      ]);
      exit;
    }

    if ($action === 'run_insert') {
      // V2: save_db already writes the full record and sets manual_lock=1 + MANUAL_LOCKED.
      // run_insert is a no-op kept for backward compatibility; never pass unique_symbol to app.py.
      $sym = trim($_POST['unique_symbol'] ?? '');
      if (!preg_match('/^(BSE|NSE):[A-Za-z0-9_\\-\\.]+$/', $sym))
        throw new Exception('Invalid unique_symbol');
      echo json_encode(['ok' => true, 'output' => 'V2: DB already updated by save_db.']);
      exit;
    }

    if ($action === 'get_scrip') {
      $id = (int) ($_POST['scrip_id'] ?? 0);
      $unique_symbol = trim($_POST['unique_symbol'] ?? '');

      if ($id > 0) {
        $stmt = $pdo->prepare("SELECT id FROM sme_ipo_lockin_details WHERE id=?");
        $stmt->execute([$id]);
        $row = $stmt->fetch();
        if (!$row) {
          if ($unique_symbol) {
            $id = 0;
          } else {
            throw new Exception('Scrip not found');
          }
        }
      }

      if ($id === 0 && $unique_symbol) {
        $stmt = $pdo->prepare("SELECT id FROM sme_ipo_lockin_details WHERE unique_symbol=?");
        $stmt->execute([$unique_symbol]);
        $row = $stmt->fetch();
        if (!$row)
          throw new Exception('Scrip not found');
        $id = $row['id'];
      }

      $stmt = $pdo->prepare("
                SELECT d.id, d.exchange, d.exchange_code, d.symbol, d.unique_symbol,
                       d.pdf_file, d.computed_total, d.declared_total,
                       d.shp_locked_total, d.total_match, d.shp_match,
                       d.engines_used, d.status, d.locked_forever, d.locked_at,
                       d.manual_lock, d.finalized, d.png_files,
                       d.gemini_lockin_match, d.gemini_shp_match, d.gemini_split_match, d.gemini_verified_at,
                       d.promoter_shares, d.public_shares, d.other_shares, d.total_shares,
                       m.allotment_date
                FROM sme_ipo_lockin_details d
                LEFT JOIN sme_ipo_master m
                    ON (d.exchange='BSE' AND CAST(m.bse_script_code AS CHAR) COLLATE utf8mb4_unicode_ci = d.exchange_code COLLATE utf8mb4_unicode_ci)
                    OR (d.exchange='NSE' AND UPPER(m.nse_symbol) COLLATE utf8mb4_unicode_ci = d.symbol COLLATE utf8mb4_unicode_ci)
                WHERE d.id=?");
      $stmt->execute([$id]);
      $s = $stmt->fetch();
      if (!$s)
        throw new Exception('Scrip not found');
      // Keep total_match and shp_match as strings "OK"/"MISMATCH" for JS comparison
      $s['locked_forever'] = (bool) ($s['locked_forever'] ?? 0);
      $s['manual_lock'] = (bool) ($s['manual_lock'] ?? 0);
      $s['finalized'] = (bool) ($s['finalized'] ?? 0);
      $s['png_files'] = json_decode($s['png_files'] ?? '[]', true) ?? [];
      $s['gemini_lockin_match'] = $s['gemini_lockin_match'] === null ? null : (bool) $s['gemini_lockin_match'];
      $s['gemini_shp_match'] = $s['gemini_shp_match'] === null ? null : (bool) $s['gemini_shp_match'];
      $s['gemini_split_match'] = $s['gemini_split_match'] === null ? null : (bool) $s['gemini_split_match'];
      if ($s['allotment_date'])
        $s['allotment_date'] = (new DateTime($s['allotment_date']))->format('Y-m-d');
      // For main list: return GROUPED rows (cleaner display, less data transfer)
      $r2 = $pdo->prepare('
        SELECT
          MIN(lock_from) as lock_from,
          lock_upto,
          days_locked,
          lock_bucket,
          MIN(type_raw) as type_raw,
          row_class,
          SUM(shares) as shares,
          COUNT(*) as _count
        FROM sme_ipo_lockin_rows
        WHERE scrip_id=?
        GROUP BY lock_upto, row_class, days_locked, lock_bucket
        ORDER BY row_class, lock_upto
      ');
      $r2->execute([$id]);
      $s['rows'] = $r2->fetchAll();
      echo json_encode($s, JSON_UNESCAPED_UNICODE | JSON_HEX_TAG | JSON_HEX_APOS | JSON_HEX_QUOT);
      exit;
    }

    if ($action === 'rollback_symbol') {
      $unique_symbol = trim($_POST['unique_symbol'] ?? '');
      $exchange = trim($_POST['exchange'] ?? '');

      if (!preg_match('/^(BSE|NSE):[A-Za-z0-9_\\-\\.]+$/', $unique_symbol)) {
        throw new Exception('Invalid unique_symbol');
      }
      if (!in_array($exchange, ['BSE', 'NSE'], true)) {
        throw new Exception('Invalid exchange');
      }

      $cmd = 'python3 ' . escapeshellarg(__DIR__ . '/finalize_symbol.py')
        . ' --symbol ' . escapeshellarg($unique_symbol)
        . ' --exchange ' . escapeshellarg($exchange)
        . ' --rollback 2>&1';

      $output = [];
      $exitCode = 0;
      exec($cmd, $output, $exitCode);
      $text = implode("\n", $output);

      if ($exitCode !== 0) {
        throw new Exception("Rollback failed (exit=$exitCode): " . $text);
      }

      echo json_encode(['ok' => true, 'output' => $text], JSON_UNESCAPED_UNICODE);
      exit;
    }

    throw new Exception("Unknown action: $action");
  } catch (Exception $e) {
    http_response_code(400);
    echo json_encode(['error' => $e->getMessage()]);
    exit;
  }
}

$data_json = '[]';
try {
  $pdo = make_pdo($env);

  $scrips = $pdo->query("
        SELECT d.id, d.exchange, d.exchange_code, d.symbol, d.unique_symbol,
               d.pdf_file, d.computed_total, d.declared_total,
               d.shp_locked_total, d.total_match, d.shp_match,
               d.engines_used, d.status, d.locked_forever, d.locked_at,
               d.manual_lock, d.finalized, d.png_files,
               d.gemini_lockin_match, d.gemini_shp_match, d.gemini_split_match, d.gemini_verified_at,
               d.promoter_shares, d.public_shares, d.other_shares, d.total_shares,
               m.allotment_date, m.listing_date_actual
        FROM sme_ipo_lockin_details d
        LEFT JOIN sme_ipo_master m
            ON (d.exchange = 'BSE' AND CAST(m.bse_script_code AS CHAR) COLLATE utf8mb4_unicode_ci = d.exchange_code COLLATE utf8mb4_unicode_ci)
            OR (d.exchange = 'NSE' AND UPPER(m.nse_symbol) COLLATE utf8mb4_unicode_ci = d.symbol COLLATE utf8mb4_unicode_ci)
        ORDER BY m.listing_date_actual DESC
    ")->fetchAll();

  $rows_raw = $pdo->query("
        SELECT scrip_id,
               MIN(lock_from) as lock_from,
               lock_upto,
               days_locked,
               lock_bucket,
               MIN(type_raw) as type_raw,
               row_class,
               SUM(shares) as shares,
               COUNT(*) as _count
        FROM sme_ipo_lockin_rows
        GROUP BY scrip_id, lock_upto, row_class, days_locked, lock_bucket
        ORDER BY scrip_id, row_class, lock_upto
    ")->fetchAll();

  $rows_by_scrip = [];
  foreach ($rows_raw as $r) {
    $rows_by_scrip[$r['scrip_id']][] = $r;
  }

  // Candidate summary (Phase 1 reconciliation with strict promotability checks)
  $cand_summary = [];
  if ($pdo->query("SHOW TABLES LIKE 'sme_ipo_extraction_candidates'")->fetch()) {
    $cand_rows = $pdo->query("
      SELECT id, scrip_id, source_pipeline, status, is_valid, validation_notes, payload_json, created_at,
             total_match, shp_match, computed_total, declared_total
      FROM sme_ipo_extraction_candidates
      WHERE status IN ('NEW','VALIDATED','REJECTED','PROMOTED')
      ORDER BY scrip_id, id DESC
    ")->fetchAll();
    foreach ($cand_rows as $cr) {
      $sid = (int) $cr['scrip_id'];
      if (!isset($cand_summary[$sid])) {
        $cand_summary[$sid] = [
          'promotable_count' => 0,
          'latest_promotable_id' => null,
          'latest_promotable_source' => null,
          'latest_promotable_status' => null,
          'latest_reason' => null,
          'snapshots' => [],
          'candidate_total_match' => null,
          'candidate_shp_match' => null,
        ];
      }

      // Skip promotability check for PROMOTED candidates (they're already promoted!)
      // We only need to check NEW/VALIDATED/REJECTED candidates for promotability
      $candidate_status = (string) ($cr['status'] ?? '');
      if ($candidate_status !== 'PROMOTED') {
        $eval = candidate_promotability($cr);
        if ($cand_summary[$sid]['latest_reason'] === null && !$eval['promotable']) {
          $cand_summary[$sid]['latest_reason'] = implode('; ', array_slice($eval['reasons'], 0, 3));
        }
      } else {
        // For PROMOTED candidates, create a passing evaluation
        $eval = ['promotable' => true, 'reasons' => []];
      }
      if ($eval['promotable']) {
        $cand_summary[$sid]['promotable_count'] += 1;
        if ($cand_summary[$sid]['latest_promotable_id'] === null) {
          $cand_summary[$sid]['latest_promotable_id'] = (int) $cr['id'];
          $cand_summary[$sid]['latest_promotable_source'] = $cr['source_pipeline'] ?? null;
          $cand_summary[$sid]['latest_promotable_status'] = $cr['status'] ?? null;
        }
        if (count($cand_summary[$sid]['snapshots']) < 2) {
          $payload = is_string($cr['payload_json']) ? (json_decode($cr['payload_json'], true) ?: []) : (is_array($cr['payload_json']) ? $cr['payload_json'] : []);
          $h = is_array($payload['header'] ?? null) ? $payload['header'] : [];
          $cand_summary[$sid]['snapshots'][] = [
            'id' => (int) $cr['id'],
            'source' => $cr['source_pipeline'] ?? '',
            'computed_total' => $h['computed_total'] ?? null,
            'declared_total' => $h['declared_total'] ?? null,
            'shp_locked_total' => $h['shp_locked_total'] ?? null,
            'promoter_shares' => $h['promoter_shares'] ?? null,
            'public_shares' => $h['public_shares'] ?? null,
            'other_shares' => $h['other_shares'] ?? null,
            'total_shares' => $h['total_shares'] ?? null,
            'status' => $cr['status'] ?? '',
            'created_at' => $cr['created_at'] ?? null,
          ];
        }
      }

      // v19: Set candidate verification fields from DB columns (only for first/valid candidate)
      if ($cand_summary[$sid]['candidate_total_match'] === null && $cr['total_match'] !== null) {
        $cand_summary[$sid]['candidate_total_match'] = (bool) $cr['total_match'];
      }
      if ($cand_summary[$sid]['candidate_shp_match'] === null && $cr['shp_match'] !== null) {
        $cand_summary[$sid]['candidate_shp_match'] = (bool) $cr['shp_match'];
      }
    }
  }

  foreach ($scrips as &$s) {
    $s['rows'] = $rows_by_scrip[$s['id']] ?? [];
    // Keep total_match and shp_match as strings "OK"/"MISMATCH" for JS comparison
    $s['locked_forever'] = (bool) ($s['locked_forever'] ?? 0);
    $s['manual_lock'] = (bool) ($s['manual_lock'] ?? 0);
    $s['finalized'] = (bool) ($s['finalized'] ?? 0);
    $s['png_files'] = json_decode($s['png_files'] ?? '[]', true) ?? [];
    $s['gemini_lockin_match'] = $s['gemini_lockin_match'] === null ? null : (bool) $s['gemini_lockin_match'];
    $s['gemini_shp_match'] = $s['gemini_shp_match'] === null ? null : (bool) $s['gemini_shp_match'];
    $s['gemini_split_match'] = $s['gemini_split_match'] === null ? null : (bool) $s['gemini_split_match'];
    $sid = (int) $s['id'];
    $s['candidate_promotable_count'] = $cand_summary[$sid]['promotable_count'] ?? 0;
    $s['candidate_promotable_id'] = $cand_summary[$sid]['latest_promotable_id'] ?? null;
    $s['candidate_promotable_source'] = $cand_summary[$sid]['latest_promotable_source'] ?? null;
    $s['candidate_promotable_status'] = $cand_summary[$sid]['latest_promotable_status'] ?? null;
    $s['candidate_not_promotable_reason'] = $cand_summary[$sid]['latest_reason'] ?? null;
    $s['candidate_snapshots'] = $cand_summary[$sid]['snapshots'] ?? [];

    // v19: Get candidate verification fields from candidates table (populated by bse_lockin_comparison_next.py / lockin_shp_comparision_next.py)
    $s['candidate_total_match'] = $cand_summary[$sid]['candidate_total_match'] ?? null;
    $s['candidate_shp_match'] = $cand_summary[$sid]['candidate_shp_match'] ?? null;

    // v18: Hide promote button if DB already has matching SHP data
    if ($s['candidate_promotable_count'] > 0 && !empty($s['candidate_snapshots'])) {
      $snap = $s['candidate_snapshots'][0];
      $db_p = (int) ($s['promoter_shares'] ?? 0);
      $db_pu = (int) ($s['public_shares'] ?? 0);
      $db_o = (int) ($s['other_shares'] ?? 0);
      $sn_p = (int) ($snap['promoter_shares'] ?? 0);
      $sn_pu = (int) ($snap['public_shares'] ?? 0);
      $sn_o = (int) ($snap['other_shares'] ?? 0);

      if ($db_p > 0 && $db_p === $sn_p && $db_pu === $sn_pu && $db_o === $sn_o) {
        $s['candidate_promotable_count'] = 0;
        $s['candidate_promotable_id'] = null;
        $s['candidate_not_promotable_reason'] = 'Already promoted';
      }
    }

    if ($s['allotment_date'])
      $s['allotment_date'] = (new DateTime($s['allotment_date']))->format('Y-m-d');
  }

  $data_json = json_encode($scrips, JSON_UNESCAPED_UNICODE | JSON_HEX_TAG | JSON_HEX_APOS | JSON_HEX_QUOT);
} catch (Exception $e) {
  $data_json = json_encode([['error' => $e->getMessage()]]);
}
?>
<!DOCTYPE html>
<html lang="en">

<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>🔒 SME IPO Lock-in Report</title>
  <link
    href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&family=Syne:wght@600;800&display=swap"
    rel="stylesheet">
  <style>
    :root {
      --bg: #0a0c0f;
      --surface: #111418;
      --card: #161b22;
      --border: #21262d;
      --border2: #30363d;
      --text: #e6edf3;
      --muted: #7d8590;
      --accent: #f78166;
      --green: #3fb950;
      --yellow: #d29922;
      --blue: #388bfd;
      --purple: #bc8cff;
      --red: #f85149;
      --cyan: #39c5cf;
      --mono: 'JetBrains Mono', monospace;
      --sans: 'Syne', sans-serif;
    }

    * {
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }

    body {
      background: var(--bg);
      color: var(--text);
      font-family: var(--mono);
      font-size: 12px;
      line-height: 1.5;
    }

    /* ?? Header ?? */
    .page-header {
      background: var(--surface);
      border-bottom: 1px solid var(--border);
      padding: 14px 24px;
      display: flex;
      align-items: center;
      gap: 16px;
      position: sticky;
      top: 0;
      z-index: 100;
    }

    .page-header h1 {
      font-family: var(--sans);
      font-size: 16px;
      font-weight: 800;
    }

    .page-header h1 span {
      color: var(--accent);
    }

    .header-right {
      margin-left: auto;
      display: flex;
      gap: 12px;
      align-items: center;
    }

    .stat-pill {
      background: var(--card);
      border: 1px solid var(--border2);
      border-radius: 6px;
      padding: 4px 10px;
      font-size: 11px;
      color: var(--muted);
    }

    .stat-pill strong {
      color: var(--text);
    }

    /* ?? Controls ?? */
    .controls {
      background: var(--surface);
      border-bottom: 1px solid var(--border);
      padding: 10px 24px;
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      align-items: center;
      position: sticky;
      top: 50px;
      z-index: 99;
    }

    .controls input,
    .controls select {
      background: var(--card);
      border: 1px solid var(--border2);
      color: var(--text);
      font-family: var(--mono);
      font-size: 12px;
      padding: 5px 10px;
      border-radius: 6px;
      outline: none;
    }

    .controls input:focus,
    .controls select:focus {
      border-color: var(--blue);
    }

    .controls input[type=search] {
      width: 180px;
    }

    .controls label {
      color: var(--muted);
      font-size: 11px;
      display: flex;
      align-items: center;
      gap: 6px;
    }

    #count-label {
      margin-left: auto;
      color: var(--muted);
      font-size: 11px;
    }

    /* ?? Main container ?? */
    .report-body {
      padding: 20px 24px;
      max-width: 1400px;
      margin: 0 auto;
    }

    /* ?? Scrip card ?? */
    .scrip-card {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 10px;
      margin-bottom: 20px;
      overflow: hidden;
    }

    /* Card header */
    .card-header {
      padding: 12px 16px;
      display: flex;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
      border-bottom: 1px solid var(--border);
      background: var(--card);
    }

    .card-symbol {
      font-family: var(--sans);
      font-size: 18px;
      font-weight: 800;
    }

    .badge {
      font-size: 10px;
      padding: 2px 7px;
      border-radius: 4px;
      font-weight: 700;
      letter-spacing: .5px;
    }

    .ex-BSE {
      background: #1a2332;
      color: var(--blue);
    }

    .ex-NSE {
      background: #1f2419;
      color: var(--green);
    }

    .st-PASS {
      background: #1a2e1a;
      color: var(--green);
    }

    .st-SHP_PASS {
      background: #1a2e2a;
      color: #5dffcc;
    }

    .st-FAIL {
      background: #2e1a1a;
      color: var(--red);
    }

    .st-NO_TOTAL {
      background: #2a2516;
      color: var(--yellow);
    }

    .st-SHP_FAIL {
      background: #2e1a1a;
      color: var(--red);
    }

    .st-MANUAL_LOCKED {
      background: #1a2a3a;
      color: var(--cyan);
    }

    .st-AUTO_LOCKED {
      background: #0f2d1c;
      color: #79f2a8;
    }

    .rc-locked {
      color: var(--accent);
    }

    .rc-anchor {
      color: var(--purple);
    }

    .rc-free {
      color: var(--muted);
    }

    /* Card meta row */
    .card-meta {
      padding: 10px 16px;
      display: flex;
      gap: 20px;
      flex-wrap: wrap;
      align-items: center;
      border-bottom: 1px solid var(--border);
      font-size: 11px;
    }

    .meta-item {
      display: flex;
      flex-direction: column;
      gap: 1px;
    }

    .meta-item .ml {
      color: var(--muted);
      font-size: 10px;
      text-transform: uppercase;
      letter-spacing: .5px;
    }

    .meta-item .mv {
      font-size: 13px;
      font-weight: 700;
    }

    .mv-blue {
      color: var(--blue);
    }

    .mv-red {
      color: var(--accent);
    }

    .mv-green {
      color: var(--green);
    }

    .mv-yellow {
      color: var(--yellow);
    }

    .mv-muted {
      color: var(--muted);
      font-size: 11px !important;
    }

    /* Links row */
    .card-links {
      padding: 8px 16px;
      display: flex;
      gap: 8px;
      border-bottom: 1px solid var(--border);
      background: #0d1117;
    }

    .link-btn {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      background: var(--card);
      border: 1px solid var(--border2);
      color: var(--blue);
      text-decoration: none;
      padding: 3px 10px;
      border-radius: 5px;
      font-size: 11px;
      font-family: var(--mono);
      transition: border-color .15s;
    }

    .link-btn:hover {
      border-color: var(--blue);
      color: var(--text);
    }

    /* Rows table */
    .card-table {
      width: 100%;
      border-collapse: collapse;
      table-layout: fixed;
    }

    .card-table th {
      text-align: left;
      padding: 7px 12px;
      background: #0d1117;
      color: var(--muted);
      font-size: 10px;
      text-transform: uppercase;
      letter-spacing: .5px;
      border-bottom: 1px solid var(--border2);
      white-space: nowrap;
      overflow: hidden;
    }

    .card-table col.c-class {
      width: 80px;
    }

    .card-table col.c-shares {
      width: 130px;
    }

    .card-table col.c-from {
      width: 110px;
    }

    .card-table col.c-upto {
      width: 110px;
    }

    .card-table col.c-days {
      width: 70px;
    }

    .card-table col.c-bucket {
      width: 110px;
    }

    .card-table col.c-type {
      width: auto;
    }

    .card-table th.num {
      text-align: right;
    }

    .card-table td {
      padding: 7px 12px;
      border-bottom: 1px solid var(--border);
      vertical-align: middle;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .card-table td.num {
      text-align: right;
      font-variant-numeric: tabular-nums;
    }

    .card-table tr:last-child td {
      border-bottom: none;
    }

    .card-table tr:hover td {
      background: var(--card);
    }

    .bucket-pill {
      font-size: 10px;
      padding: 2px 7px;
      border-radius: 10px;
      font-weight: 600;
      white-space: nowrap;
    }

    .bk-anchor_30 {
      background: #2a1f3d;
      color: var(--purple);
    }

    .bk-anchor_90 {
      background: #271d3a;
      color: #a37eee;
    }

    .bk-1_year {
      background: #1a2e1a;
      color: var(--green);
    }

    .bk-2_year {
      background: #162a16;
      color: #3da53d;
    }

    .bk-3_year {
      background: #122212;
      color: #379137;
    }

    .bk-free {
      background: #1e1e1e;
      color: var(--muted);
    }

    .bk-unknown {
      background: #261e10;
      color: var(--yellow);
    }

    /* No rows */
    .no-rows {
      padding: 16px;
      color: var(--muted);
      text-align: center;
      font-size: 12px;
    }

    /* Loading */
    #loading {
      position: fixed;
      inset: 0;
      background: var(--bg);
      display: flex;
      align-items: center;
      justify-content: center;
      flex-direction: column;
      gap: 12px;
      z-index: 999;
    }

    .spinner {
      width: 32px;
      height: 32px;
      border: 3px solid var(--border2);
      border-top-color: var(--accent);
      border-radius: 50%;
      animation: spin .7s linear infinite;
    }

    @keyframes spin {
      to {
        transform: rotate(360deg);
      }
    }

    /* Scrollbar */
    ::-webkit-scrollbar {
      width: 6px;
    }

    ::-webkit-scrollbar-track {
      background: var(--bg);
    }

    ::-webkit-scrollbar-thumb {
      background: var(--border2);
      border-radius: 3px;
    }

    /* Jump to top */
    #top-btn {
      position: fixed;
      bottom: 20px;
      right: 20px;
      background: var(--card);
      border: 1px solid var(--border2);
      color: var(--muted);
      width: 36px;
      height: 36px;
      border-radius: 50%;
      cursor: pointer;
      font-size: 16px;
      display: flex;
      align-items: center;
      justify-content: center;
      transition: all .15s;
      z-index: 50;
    }

    #top-btn:hover {
      border-color: var(--accent);
      color: var(--accent);
    }

    .match-ok {
      color: var(--green);
    }

    .match-fail {
      color: var(--red);
    }

    .match-none {
      color: var(--muted);
    }

    /* Responsive Table */
    .table-wrap {
      overflow-x: auto;
      -webkit-overflow-scrolling: touch;
    }

    .card-table {
      min-width: 600px;
    }

    /* Responsive Cards */
    /* Edit button */
    .edit-btn {
      margin-left: auto;
      background: var(--card);
      border: 1px solid var(--border2);
      color: var(--blue);
      font-family: var(--mono);
      font-size: 11px;
      padding: 3px 10px;
      border-radius: 5px;
      cursor: pointer;
      transition: border-color .15s, color .15s;
    }

    .edit-btn:hover {
      border-color: var(--blue);
      color: var(--text);
    }

    /* Edit overlay */
    #edit-overlay {
      display: none;
      position: fixed;
      inset: 0;
      z-index: 200;
      background: rgba(0, 0, 0, .75);
      align-items: stretch;
    }

    .edit-panel {
      display: flex;
      flex-direction: column;
      background: var(--surface);
      overflow: hidden;
    }

    #edit-left {
      width: 45%;
      border-right: 1px solid var(--border);
      min-width: 0;
    }

    #edit-right {
      width: 55%;
      min-width: 0;
    }

    .edit-panel-header {
      background: var(--card);
      border-bottom: 1px solid var(--border);
      padding: 10px 14px;
      display: flex;
      align-items: center;
      gap: 8px;
      font-family: var(--sans);
      font-size: 14px;
      font-weight: 700;
      flex-shrink: 0;
    }

    .edit-close-btn {
      margin-left: auto;
      background: none;
      border: none;
      color: var(--muted);
      font-size: 18px;
      cursor: pointer;
      padding: 0 4px;
    }

    .edit-close-btn:hover {
      color: var(--red);
    }

    /* PNG pane */
    #edit-png-wrap {
      overflow: auto;
      display: block;
    }

    #edit-png {
      max-width: 100%;
      height: auto;
      cursor: zoom-in;
      transition: transform 0.15s ease;
    }

    .png-nav {
      flex-shrink: 0;
      border-top: 1px solid var(--border);
      padding: 6px 14px;
      display: flex;
      gap: 8px;
      align-items: center;
      font-size: 11px;
      color: var(--muted);
    }

    .png-nav button {
      background: var(--card);
      border: 1px solid var(--border2);
      color: var(--text);
      font-family: var(--mono);
      font-size: 11px;
      padding: 2px 8px;
      border-radius: 4px;
      cursor: pointer;
    }

    .png-nav button:hover {
      border-color: var(--blue);
    }

    /* PNG dark mode */
    .png-dark #edit-png {
      filter: invert(1) hue-rotate(180deg);
    }

    .png-dark #edit-png-wrap {
      background: #000;
    }

    /* Form pane */
    #edit-form-wrap {
      flex: 1;
      overflow-y: auto;
      padding: 14px;
    }

    .edit-section {
      margin-bottom: 14px;
    }

    .edit-section-title {
      color: var(--muted);
      font-size: 10px;
      text-transform: uppercase;
      letter-spacing: .5px;
      margin-bottom: 6px;
    }

    .edit-meta-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 6px;
    }

    .edit-field {
      display: flex;
      flex-direction: column;
      gap: 3px;
    }

    .edit-field label {
      color: var(--muted);
      font-size: 10px;
    }

    .edit-input,
    .edit-select {
      background: var(--card);
      border: 1px solid var(--border2);
      color: var(--text);
      font-family: var(--mono);
      font-size: 12px;
      padding: 4px 8px;
      border-radius: 4px;
      width: 100%;
      outline: none;
    }

    .edit-input:focus,
    .edit-select:focus {
      border-color: var(--blue);
    }

    /* Rows table */
    .edit-rows-table {
      width: 100%;
      border-collapse: collapse;
      font-size: 11px;
      margin-top: 6px;
    }

    .edit-rows-table th {
      color: var(--muted);
      text-align: left;
      padding: 4px 6px;
      font-size: 10px;
      text-transform: uppercase;
      letter-spacing: .4px;
      border-bottom: 1px solid var(--border);
    }

    .edit-rows-table td {
      padding: 3px 4px;
      border-bottom: 1px solid var(--border);
      vertical-align: middle;
    }

    .edit-rows-table td .edit-input {
      padding: 3px 5px;
    }

    .del-row-btn {
      background: none;
      border: none;
      color: var(--red);
      cursor: pointer;
      font-size: 14px;
      padding: 0 4px;
      line-height: 1;
    }

    .add-row-btn {
      margin-top: 6px;
      background: var(--card);
      border: 1px solid var(--border2);
      color: var(--green);
      font-family: var(--mono);
      font-size: 11px;
      padding: 3px 10px;
      border-radius: 4px;
      cursor: pointer;
    }

    /* Footer bar */
    .edit-footer {
      flex-shrink: 0;
      border-top: 1px solid var(--border);
      padding: 10px 14px;
      display: flex;
      gap: 8px;
      align-items: center;
    }

    #edit-status {
      flex: 1;
      font-size: 11px;
      color: var(--muted);
    }

    .edit-status-ok {
      color: var(--green) !important;
    }

    .edit-status-error {
      color: var(--red) !important;
    }

    #edit-save-btn {
      background: var(--blue);
      border: none;
      color: #fff;
      font-family: var(--mono);
      font-size: 12px;
      font-weight: 700;
      padding: 6px 18px;
      border-radius: 5px;
      cursor: pointer;
    }

    #edit-save-btn:disabled {
      opacity: .5;
      cursor: default;
    }

    #edit-loading-msg {
      padding: 40px;
      color: var(--muted);
      text-align: center;
    }

    @media (max-width: 768px) {
      .page-header {
        flex-direction: column;
        align-items: flex-start;
        gap: 10px;
        padding: 12px 16px;
      }

      .header-right {
        margin-left: 0;
        flex-wrap: wrap;
      }

      .controls {
        position: sticky;
        top: 110px;
        padding: 10px 12px;
        gap: 8px;
      }

      .controls input[type=search] {
        width: 100%;
        order: -1;
      }

      .controls label {
        font-size: 10px;
      }

      .controls select {
        padding: 4px 6px;
        font-size: 11px;
      }

      #count-label {
        width: 100%;
        margin-left: 0;
        margin-top: 4px;
      }

      .report-body {
        padding: 12px;
      }

      .card-header {
        padding: 10px 12px;
      }

      .card-symbol {
        font-size: 16px;
      }

      .card-meta {
        padding: 8px 12px;
        gap: 12px;
      }

      .card-meta .meta-item {
        min-width: 80px;
      }

      .card-links {
        padding: 8px 12px;
        flex-wrap: wrap;
      }
    }
  </style>
</head>

<body>

  <div id="loading">
    <div class="spinner"></div>
    <div style="color:var(--muted);font-size:12px">Loading report...</div>
  </div>

  <div class="page-header">
    <h1>🔒 SME IPO <span>Lock-in</span> Report</h1>
    <div class="header-right">
      <div class="stat-pill" id="stat-total">- scrips</div>
      <div class="stat-pill" id="stat-bse">📊 BSE -</div>
      <div class="stat-pill" id="stat-nse">📈 NSE -</div>
      <div class="stat-pill" style="color:var(--muted);font-size:10px"><?php echo $REPORT_VERSION; ?></div>
      <a href="lockin_viewer.html" class="link-btn">👁 Viewer</a>
    </div>
  </div>

  <div class="controls">
    <input type="search" id="search" placeholder="Search symbol or BSE code..." autocomplete="off">
    <label>Exchange
      <select id="filter-exchange">
        <option value="">All</option>
        <option value="BSE">BSE</option>
        <option value="NSE">NSE</option>
      </select>
    </label>
    <label>Status
      <select id="filter-status">
        <option value="">All</option>
        <option value="PASS">PASS</option>
        <option value="SHP_PASS">SHP_PASS</option>
        <option value="SHP_FAIL">SHP_FAIL</option>
        <option value="FAIL">FAIL</option>
        <option value="NO_TOTAL">NO_TOTAL</option>
        <option value="MANUAL_LOCKED">MANUAL_LOCKED</option>
        <option value="AUTO_LOCKED">AUTO_LOCKED</option>
      </select>
    </label>
    <label>Finalized
      <select id="filter-finalized">
        <option value="">All</option>
        <option value="1">Finalized</option>
        <option value="0">Not Finalized</option>
      </select>
    </label>
    <label>Bucket
      <select id="filter-bucket">
        <option value="">All</option>
        <option value="anchor_30">Anchor 30d</option>
        <option value="anchor_90">Anchor 90d</option>
        <option value="1_year">1 Year</option>
        <option value="2_year">2 Year</option>
        <option value="3_year">3 Year</option>
        <option value="unknown">Unknown</option>
      </select>
    </label>
    <label>Sort
      <select id="sort-by">
        <option value="listing_date_actual" selected>Listing Date ↓</option>
        <option value="symbol">Symbol</option>
        <option value="allotment_date">Allotment Date</option>
        <option value="exchange">Exchange</option>
        <option value="status">Status</option>
        <option value="locked_shares">Locked Shares</option>
      </select>
    </label>
    <span id="count-label"></span>
  </div>

  <div class="report-body" id="report-body"></div>
  <button id="top-btn" onclick="window.scrollTo({top:0,behavior:'smooth'})">^</button>

  <!-- ── Edit overlay ─────────────────────────────────────────────────────── -->
  <div id="edit-overlay">
    <div class="edit-panel" id="edit-left">
      <div class="edit-panel-header">
        <span>📄 Lock-in Document</span>
        <span id="edit-png-label"
          style="font-size:11px;color:var(--muted);font-family:var(--mono);font-weight:400"></span>

        <button id="png-dark-toggle" style="margin-left:auto;background:var(--card);border:1px solid var(--border2);
                 color:var(--text);font-family:var(--mono);font-size:11px;
                 padding:3px 10px;border-radius:4px;cursor:pointer" onclick="togglePngDark()">
          🌙 Dark
        </button>
      </div>
      <div id="edit-png-wrap">
        <div id="edit-loading-msg">Loading...</div>
        <img id="edit-png" src="" alt="Lock-in document" style="display:none">
      </div>
      <div class="png-nav" id="edit-png-nav" style="display:none">
        <button onclick="pngNav(-1)">← Prev</button>
        <span id="edit-png-counter"></span>
        <button onclick="pngNav(1)">Next →</button>
      </div>
    </div>
    <div class="edit-panel" id="edit-right">
      <div class="edit-panel-header">
        ✏️ Edit — <span id="edit-symbol-label" style="color:var(--accent)"></span>
        <button class="edit-close-btn" onclick="closeEditOverlay()" title="Close">✕</button>
      </div>
      <div id="edit-form-wrap">
        <!-- Meta fields -->
        <div class="edit-section">
          <div class="edit-section-title">Metadata</div>
          <div class="edit-meta-grid">
            <div class="edit-field"><label>Declared Total</label><input class="edit-input" id="ef-declared" type="text"
                placeholder="e.g. 1000000"></div>
            <div class="edit-field"><label>SHP Locked Total</label><input class="edit-input" id="ef-shp" type="text"
                placeholder="e.g. 800000 (optional)"></div>
            <div class="edit-field"><label>Computed Total (auto)</label><input class="edit-input" id="ef-computed"
                readonly style="color:var(--muted)"></div>
          </div>
        </div>
        <!-- Rows -->
        <div class="edit-section">
          <div class="edit-section-title">Lock-in Rows</div>
          <table class="edit-rows-table">
            <thead>
              <tr>
                <th>Shares</th>
                <th>Lock Upto</th>
                <th>Lock From</th>
                <th>Type Raw</th>
                <th>Class</th>
                <th></th>
              </tr>
            </thead>
            <tbody id="edit-rows-tbody"></tbody>
          </table>
          <button class="add-row-btn" onclick="addEditRow()">+ Add Row</button>
        </div>
      </div>
      <div class="edit-footer">
        <span id="edit-status"></span>
        <button id="edit-save-btn" onclick="saveEdit()">Save &amp; Reprocess</button>
      </div>
      <div id="edit-recon-box"
        style="display:flex;gap:8px;align-items:center;padding:10px 16px;border-top:1px solid var(--border2);flex-wrap:wrap">
        <input id="recon-by" class="edit-input" type="text" value="web_user" placeholder="promoted_by"
          style="max-width:160px;font-family:var(--mono);font-size:11px">
        <button id="recon-load-btn" onclick="loadCandidates()">Review Candidates</button>
        <select id="recon-candidate-select" class="edit-select" style="min-width:320px;max-width:420px">
          <option value="">(no candidates loaded)</option>
        </select>
        <button id="recon-promote-btn" onclick="promoteSelectedCandidate()">Promote Candidate</button>
      </div>
    </div>
  </div>

  <script>
    let allScrips = [];

    function fmt(n) {
      if (n == null || n === '') return '-';
      return Number(n).toLocaleString('en-IN');
    }

    function getEffectiveStatus(s) {
      if (s.manual_lock) return 'MANUAL_LOCKED';
      if (s.locked_forever) return 'AUTO_LOCKED';
      return s.status || '';
    }

    function apiPost(params) {
      return fetch(window.location.pathname, {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: new URLSearchParams(params)
      }).then(async r => {
        const data = await r.json();
        if (!r.ok) throw new Error(data.error || 'Server error');
        return data;
      });
    }

    function enrichScrip(s) {
      const locked = (s.rows || []).filter(r => r.row_class !== 'free');
      const free = (s.rows || []).filter(r => r.row_class === 'free');
      s.locked_shares = locked.reduce((a, r) => a + (+r.shares || 0), 0);
      s.free_shares = free.reduce((a, r) => a + (+r.shares || 0), 0);
      s.effective_status = getEffectiveStatus(s);
      return s;
    }

    // ── Card renderer (extracted for single-card refresh after save) ──────────────
    function renderScripCard(s) {
      const pdfFile = (s.pdf_file || '').replace(/\\/g, '/');
      const pdfName = pdfFile ? pdfFile.split('/').pop() : '';
      const stem = pdfName.replace(/\.pdf$/i, '');
      const isFinalized = !!s.finalized;
      const shpName = s.exchange === 'BSE' ? pdfName.replace("I.", "II.") : "SHP-" + s.symbol + ".pdf";
      const pdfBase = isFinalized
        ? (s.exchange === 'BSE' ? 'finalized/bse/pdf/lockin/' : 'finalized/nse/pdf/lockin/')
        : (s.exchange === 'BSE' ? 'downloads-bse/' : 'downloads/unlock/pdf/');
      const shpBase = isFinalized
        ? (s.exchange === 'BSE' ? 'finalized/bse/pdf/shp/' : 'finalized/nse/pdf/shp/')
        : (s.exchange === 'BSE' ? 'downloads-bse/' : 'downloads/unlock/shp/');
      const pngBase = isFinalized
        ? (s.exchange === 'BSE' ? 'finalized/bse/png/' : 'finalized/nse/png/')
        : (s.exchange === 'BSE' ? 'downloads-bse/png/' : 'downloads/unlock/pdf/png/');

      // Text extract paths
      const lockinTextBase = s.exchange === 'BSE' ? 'lockin_text_extracts_bse/' : 'lockin_text_extracts/';
      const shpTextBase = s.exchange === 'BSE' ? 'shp_text_extracts_bse/' : 'shp_text_extracts/';

      // SHP text file naming: BSE uses Annexure-II pattern, NSE uses SHP-{symbol} only
      const shpStem = s.exchange === 'BSE'
        ? stem.replace('Annexure-I', 'Annexure-II')
        : `SHP-${s.symbol}`;  // NSE: use symbol only, not full stem

      const linksHtml = pdfName ? `
    <div class="card-links">
      <a class="link-btn" href="${pdfBase}${pdfName}" target="_blank">📄 PDF</a>
      <a class="link-btn" href="${shpBase}${shpName}" target="_blank">📊 SHP PDF</a>
      <a class="link-btn" href="${pngBase}${stem}.png" target="_blank">🖼 PNG</a>
      <span style="color:var(--muted);margin:0 4px">|</span>
      <a class="link-btn" href="${lockinTextBase}${stem}_pdfplumber.txt" target="_blank">📝 Lock-in (plumber)</a>
      <a class="link-btn" href="${lockinTextBase}${stem}_java.txt" target="_blank">📝 Lock-in (java)</a>
      <span style="color:var(--muted);margin:0 4px">|</span>
      <a class="link-btn" href="${shpTextBase}${shpStem}_pdfplumber.txt" target="_blank">📝 SHP (plumber)</a>
      <a class="link-btn" href="${shpTextBase}${shpStem}_java.txt" target="_blank">📝 SHP (java)</a>
    </div>` : '';

      const totalShares = s.computed_total || 0;
      const lockedShares = s.locked_shares || 0;
      const freeShares = s.free_shares || 0;
      const lockedPct = totalShares ? ((lockedShares / totalShares) * 100).toFixed(1) : '-';
      const effectiveStatus = s.effective_status || getEffectiveStatus(s);
      const promotableCount = Number(s.candidate_promotable_count || 0);
      const promotableId = s.candidate_promotable_id ? Number(s.candidate_promotable_id) : null;
      const promotableSource = s.candidate_promotable_source || '';
      const notPromotableReason = s.candidate_not_promotable_reason || '';
      const promotableBadge = (promotableCount > 0 && !isFinalized)
        ? `<span class="badge" style="background:#1f3a2b;color:#9ff3c7;border-color:#2d5a41">PROMOTABLE ${promotableCount}</span>`
        : (!isFinalized && notPromotableReason ? `<span class="badge" style="background:#402525;color:#ffb3b3;border-color:#6a3a3a" title="${String(notPromotableReason).replace(/"/g, '&quot;')}">NOT PROMOTABLE</span>` : '');
      const promoteBtn = (promotableCount > 0 && promotableId)
        ? `<button class="edit-btn" style="background:#1f3a2b;border-color:#2d5a41" onclick="quickPromote(${s.id}, ${promotableId})" title="Promote latest ${promotableSource} candidate">⬆ Promote</button>`
        : '';

      // Reconcile button: show when reconciliation is needed (missing SHP data or mismatched data)
      // ALL 6 validation rules must pass to hide the button:
      // Rule 1: Lock-in total = Sum of rows (computed_total = Σ(rows.shares))
      // Rule 2: Free + Locked = Total (free_shares + locked_shares = total_shares)
      // Rule 3: SHP total = Lock-in total (shp_total_shares = lockin_total_shares)
      // Rule 4: SHP locked = Lock-in locked (shp_locked_shares = lockin_locked_shares)
      // Rule 5: SHP split = SHP total (promoter + public + other = shp_total_shares)
      // Rule 6: All rows have buckets (lock_bucket ≠ null AND lock_bucket ≠ '' - "unknown" is VALID)
      const hasData = (Number(s.total_shares) > 0 || Number(s.computed_total) > 0);
      const hasAllShp =
        s.promoter_shares !== null &&
        s.public_shares !== null &&
        s.other_shares !== null &&
        s.shp_locked_total !== null;

      const shpLocked = Number(s.shp_locked_total) || 0;
      const promoterShares = Number(s.promoter_shares) || 0;
      const publicShares = Number(s.public_shares) || 0;
      const otherShares = Number(s.other_shares) || 0;
      const computedTotal = Number(s.computed_total) || 0;

      // Rule 1: Lock-in total = Sum of rows
      const rows = s.rows || [];
      const rowsSum = rows.reduce((sum, r) => sum + (Number(r.shares) || 0), 0);
      const rule1_lockinTotalMatches = (computedTotal === rowsSum);

      // Rule 2: Free + Locked = Total
      const rule2_lockInBalanced = (freeShares + lockedShares === totalShares);

      // Rule 3: SHP total = Lock-in total
      const rule3_shpTotalMatchesLockin = (totalShares === computedTotal);

      // Rule 4: SHP locked = Lock-in locked
      const rule4_shpLockedMatches = (shpLocked === lockedShares);

      // Rule 5: SHP split = SHP total
      const rule5_shpSplitMatches = ((promoterShares + publicShares + otherShares) === totalShares);

      // Rule 6: All rows have buckets (not null, not empty - "unknown" is VALID)
      const rule6_allRowsHaveBuckets = rows.every(r => {
        const bucket = r.lock_bucket;
        return bucket !== null && bucket !== undefined && String(bucket).trim() !== '';
      });

      const hasMissingShp = !hasAllShp;
      const hasMismatch =
        (hasAllShp && !rule1_lockinTotalMatches) ||
        (hasAllShp && !rule2_lockInBalanced) ||
        (hasAllShp && !rule3_shpTotalMatchesLockin) ||
        (hasAllShp && !rule4_shpLockedMatches) ||
        (hasAllShp && !rule5_shpSplitMatches) ||
        !rule6_allRowsHaveBuckets;

      const needsReconciliation = hasMissingShp || hasMismatch;
      // v19: Check if candidate from bse_lockin_comparison_next.py / lockin_shp_comparision_next.py already has valid data
      const candidateHasValidData = (s.candidate_total_match === true && s.candidate_shp_match === true);
      // Hide reconcile button if promotable candidate exists (show Promote instead)
      const hasPromotableCandidate = (promotableCount > 0 && promotableId);
      // v19: Don't show reconcile if candidate already has valid total_match AND shp_match
      const canReconcile = !isFinalized && hasData && needsReconciliation && !hasPromotableCandidate && !candidateHasValidData;
      const reconcileBtn = canReconcile
        ? `<button class="edit-btn" style="background:#b36200;border-color:#d47600;color:#fff" onclick="reconcileSymbol(${s.id}, '${s.exchange}:${s.symbol}')" title="Generate reconciliation candidate from java extraction">🔧 Reconcile</button>`
        : '';

      const matchStr = (() => {
        const st = effectiveStatus;
        if (st === 'PASS' || st === 'SHP_PASS') return `<span class="match-ok">OK MATCH</span>`;
        if (st === 'FAIL' || st === 'SHP_FAIL') return `<span class="match-fail">FAIL</span>`;
        if (st === 'MANUAL_LOCKED') return `<span class="match-ok">MANUAL LOCK</span>`;
        if (st === 'AUTO_LOCKED') return `<span class="match-ok">AUTO LOCK</span>`;
        return `<span class="match-none">${st}</span>`;
      })();

      // Finalized status and reason
      const finalizedStr = isFinalized
        ? `<span class="match-ok">FINALIZED</span>`
        : `<span class="match-fail">NOT FINALIZED</span>`;

      const finalizedReason = (() => {
        if (isFinalized) return '';
        if (s.manual_lock) return '(Manual lock required)';
        if (s.total_match === 'MISMATCH') return '(Total mismatch)';
        if (s.shp_match === 'MISMATCH') return '(SHP mismatch)';
        if (!s.declared_total) return '(No declared total)';
        return '(Pending validation)';
      })();

      // Calculate SHP Split Match
      const ps = Number(s.promoter_shares) || 0;
      const pubs = Number(s.public_shares) || 0;
      const tot = Number(s.total_shares) || 0;
      const shpSplitMatch = (ps + pubs) === tot && tot > 0;
      const shpSplitStr = shpSplitMatch
        ? `<span class="match-ok">MATCH</span>`
        : `<span class="match-fail">MISMATCH</span>`;

      // Calculate percentages
      const psPct = tot ? ((ps / tot) * 100).toFixed(1) : '0.0';
      const pubsPct = tot ? ((pubs / tot) * 100).toFixed(1) : '0.0';

      const shpLockedStr = s.shp_locked_total
        ? (() => {
          if (s.shp_match === true) return `${fmt(s.shp_locked_total)} <span class="match-ok">OK</span>`;
          if (s.shp_match === false) return `${fmt(s.shp_locked_total)} <span class="match-fail">FAIL</span>`;
          return `${fmt(s.shp_locked_total)} <span class="match-none">N/A</span>`;
        })()
        : '-';

      const snapshots = Array.isArray(s.candidate_snapshots) ? s.candidate_snapshots : [];
      const snapshotHtml = (!isFinalized && snapshots.length) ? `
        <div style="padding:8px 16px 0 16px">
          <div style="font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;margin-bottom:4px">Candidate Snapshots</div>
          <table class="card-table">
            <thead><tr>
              <th>Snapshot</th><th>Source</th><th class="num">Lock-in Total</th><th class="num">SHP Locked</th>
              <th class="num">Promoter</th><th class="num">Public</th><th class="num">Other</th><th class="num">SHP Total</th>
            </tr></thead>
            <tbody>
              ${snapshots.map((c, i) => `<tr>
                <td>#${c.id} ${i === 0 ? '<span class="match-ok">latest</span>' : ''}</td>
                <td>${c.source || '-'}</td>
                <td class="num">${fmt(c.computed_total)}</td>
                <td class="num">${fmt(c.shp_locked_total)}</td>
                <td class="num">${fmt(c.promoter_shares)}</td>
                <td class="num">${fmt(c.public_shares)}</td>
                <td class="num">${fmt(c.other_shares)}</td>
                <td class="num">${fmt(c.total_shares)}</td>
              </tr>`).join('')}
            </tbody>
          </table>
        </div>` : '';

      // Rows already grouped by server (get_scrip action) for efficient display
      // Editor will fetch ungrouped rows via get_json action
      const rowsHtml = (s.rows || []).length === 0
        ? `<div class="no-rows">No lock-in rows extracted</div>`
        : `<div class="table-wrap"><table class="card-table">
        <colgroup>
          <col class="c-class"><col class="c-shares"><col class="c-from">
          <col class="c-upto"><col class="c-days"><col class="c-bucket"><col class="c-type">
        </colgroup>
        <thead><tr>
          <th>Class</th><th class="num">Shares</th><th>Lock From</th>
          <th>Lock Upto</th><th class="num">Days</th><th>Bucket</th><th>Type</th>
        </tr></thead>
        <tbody>
          ${(s.rows || []).map(r => `<tr>
            <td class="rc-${r.row_class}">${r.row_class}</td>
            <td class="num">${fmt(r.shares)}${(+r._count || 0) > 1 ? ` <small style="color:var(--muted)">(${r._count})</small>` : ''}</td>
            <td>${r.lock_from || '<span style="color:var(--muted)">-</span>'}</td>
            <td>${r.lock_upto || '<span style="color:var(--muted)">-</span>'}</td>
            <td class="num">${r.days_locked != null ? r.days_locked + 'd' : '<span style="color:var(--muted)">-</span>'}</td>
            <td><span class="bucket-pill bk-${r.lock_bucket || 'free'}">${r.lock_bucket || '-'}</span></td>
            <td style="color:var(--muted);max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${r.type_raw || ''}">${r.type_raw || '-'}</td>
          </tr>`).join('')}
        </tbody>
      </table></div>`;

      return `
  <div class="scrip-card" id="sc-${s.id}">
    <div class="card-header">
      <span class="card-symbol">${s.symbol}</span>
      <span class="badge ex-${s.exchange}">${s.exchange}</span>
      <span class="badge st-${effectiveStatus}">${effectiveStatus}</span>
      ${s.locked_forever ? `<span class="badge st-AUTO_LOCKED">AUTO LOCKED</span>` : ''}
      ${s.manual_lock ? `<span class="badge st-MANUAL_LOCKED">MANUAL LOCKED</span>` : ''}
      ${s.exchange_code ? `<span style="color:var(--muted);font-size:11px">${s.exchange_code}</span>` : ''}
      <span style="font-size:11px">${matchStr}</span>
      <span style="font-size:11px">${finalizedStr} ${finalizedReason}</span>
      ${promotableBadge}
      ${(!isFinalized && !promotableCount && notPromotableReason) ? `<span style="font-size:11px;color:#ffb3b3;max-width:420px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${String(notPromotableReason).replace(/"/g, '&quot;')}">Reason: ${notPromotableReason}</span>` : ''}
      ${reconcileBtn}
      ${promoteBtn}
      <button class="edit-btn" onclick="openEditOverlay(${s.id})" title="${isFinalized ? 'Rollback finalized symbol' : 'Edit record'}">${isFinalized ? '↩ Rollback' : '✏️ Edit'}</button>
    </div>
    <div class="card-meta" style="display:grid;grid-template-columns:110px 180px 120px 140px 120px 100px;gap:12px 20px;padding:8px 16px;font-size:11px">
      <div style="grid-column:1/-1;display:contents">
        <div style="color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:0.5px;padding-bottom:2px">Allotment</div>
        <div style="color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:0.5px;text-align:right;padding-bottom:2px">Locked</div>
        <div style="color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:0.5px;text-align:right;padding-bottom:2px">Free</div>
        <div style="color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:0.5px;text-align:right;padding-bottom:2px">Total Shares</div>
        <div style="color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:0.5px;text-align:right;padding-bottom:2px">Declared</div>
        <div style="color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:0.5px;text-align:center;padding-bottom:2px">SHP Split</div>

        <div style="color:var(--blue);font-weight:700;font-size:13px">${s.allotment_date || '-'}</div>
        <div style="text-align:right;color:var(--accent);font-weight:700;font-size:13px;white-space:nowrap">${fmt(lockedShares)} <small style="font-weight:400;color:var(--muted)">(${lockedPct}%)</small></div>
        <div style="text-align:right;color:var(--green);font-weight:700;font-size:13px">${fmt(freeShares)}</div>
        <div style="text-align:right;font-weight:700;font-size:13px">${fmt(totalShares)}</div>
        <div style="text-align:right;color:var(--muted);font-size:11px">${fmt(s.declared_total)}</div>
        <div style="text-align:center">${shpSplitStr}</div>
      </div>

      <div style="grid-column:1/-1;height:6px"></div>

      <div style="grid-column:1/-1;display:contents">
        <div style="color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:0.5px;padding-bottom:2px">Engine</div>
        <div style="color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:0.5px;text-align:right;padding-bottom:2px">Promoter</div>
        <div style="color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:0.5px;text-align:right;padding-bottom:2px">Public</div>
        <div style="color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:0.5px;text-align:right;padding-bottom:2px">Total SHP</div>
        <div style="color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:0.5px;text-align:right;padding-bottom:2px;grid-column:span 2">SHP Locked</div>

        <div style="color:var(--muted)">${s.engines_used || 'pdfplumber'}</div>
        <div style="text-align:right;font-weight:700;font-size:13px;white-space:nowrap;${shpSplitMatch ? '' : 'color:var(--red)'}">${fmt(s.promoter_shares)} <small style="font-weight:400;color:var(--muted)">(${psPct}%)</small></div>
        <div style="text-align:right;font-weight:700;font-size:13px;white-space:nowrap;${shpSplitMatch ? '' : 'color:var(--red)'}">${fmt(s.public_shares)} <small style="font-weight:400;color:var(--muted)">(${pubsPct}%)</small></div>
        <div style="text-align:right;font-weight:700;font-size:13px">${fmt(s.total_shares)}</div>
        <div style="text-align:right;grid-column:span 2">${shpLockedStr}</div>
      </div>
    </div>
    ${linksHtml}
    ${snapshotHtml}
    ${rowsHtml}
  </div>`;
    }

    // ── Data load ─────────────────────────────────────────────────────────────────
    function loadData() {
      try {
        allScrips = <?php echo $data_json; ?>;
        if (allScrips.length && allScrips[0].error) throw new Error(allScrips[0].error);
        allScrips.forEach(enrichScrip);
        const bse = allScrips.filter(s => s.exchange === 'BSE').length;
        const nse = allScrips.filter(s => s.exchange === 'NSE').length;
        document.getElementById('stat-total').innerHTML = `<strong>${allScrips.length}</strong> scrips`;
        document.getElementById('stat-bse').innerHTML = `BSE <strong>${bse}</strong>`;
        document.getElementById('stat-nse').innerHTML = `NSE <strong>${nse}</strong>`;
        document.getElementById('loading').style.display = 'none';
        render();
      } catch (e) {
        document.getElementById('loading').innerHTML =
          `<div style="color:var(--red);text-align:center"><div style="font-size:24px">!</div><div>${e.message}</div></div>`;
      }
    }

    function render() {
      const q = document.getElementById('search').value.trim().toLowerCase();
      const exch = document.getElementById('filter-exchange').value;
      const status = document.getElementById('filter-status').value;
      const finalizedFilter = document.getElementById('filter-finalized').value;
      const bucket = document.getElementById('filter-bucket').value;
      const sortBy = document.getElementById('sort-by').value;

      let scrips = allScrips.filter(s => {
        if (q) {
          // Search in symbol OR exchange_code (BSE code)
          const symbolMatch = s.symbol.toLowerCase().includes(q);
          const exchangeCodeMatch = (s.exchange_code || '').toLowerCase().includes(q);
          if (!symbolMatch && !exchangeCodeMatch) return false;
        }
        if (exch && s.exchange !== exch) return false;
        const st = s.effective_status || getEffectiveStatus(s);
        if (status && st !== status) return false;
        if (finalizedFilter !== '' && String(s.finalized ? 1 : 0) !== finalizedFilter) return false;
        if (bucket && !(s.rows || []).some(r => r.lock_bucket === bucket)) return false;
        return true;
      });
      scrips.sort((a, b) => {

        const av = a[sortBy] ?? '';
        const bv = b[sortBy] ?? '';

        // numeric fields
        if (typeof av === 'number' && typeof bv === 'number') {
          return sortBy === 'listing_date_actual' ? bv - av : av - bv;
        }

        // date or string fields
        if (sortBy === 'listing_date_actual') {
          return String(bv).localeCompare(String(av)); // DESC
        }

        return String(av).localeCompare(String(bv)); // ASC default
      });
      document.getElementById('count-label').textContent = `${scrips.length} / ${allScrips.length}`;
      const body = document.getElementById('report-body');
      if (!scrips.length) { body.innerHTML = '<div style="padding:40px;text-align:center;color:var(--muted)">No results</div>'; return; }
      body.innerHTML = scrips.map(s => renderScripCard(s)).join('');
    }

    // ── Edit overlay state ────────────────────────────────────────────────────────
    let _editScripId = null, _editData = null, _pngFiles = [], _pngIdx = 0, _editCandidates = [];

    function openEditOverlay(scripId) {
      _editScripId = scripId;
      const ov = document.getElementById('edit-overlay');
      ov.style.display = 'flex';
      document.getElementById('edit-loading-msg').style.display = '';
      document.getElementById('edit-png').style.display = 'none';
      document.getElementById('edit-png-nav').style.display = 'none';
      document.getElementById('edit-status').textContent = '';
      const btn = document.getElementById('edit-save-btn');
      const reconBox = document.getElementById('edit-recon-box');
      const s = allScrips.find(x => x.id == scripId);
      const isFinalized = !!(s && s.finalized);
      btn.disabled = false;
      btn.dataset.mode = isFinalized ? 'rollback' : 'save';
      btn.textContent = isFinalized ? 'Rollback Symbol' : 'Save & Lock';
      if (reconBox) reconBox.style.display = isFinalized ? 'none' : 'flex';
      _editCandidates = [];
      const sel = document.getElementById('recon-candidate-select');
      if (sel) sel.innerHTML = '<option value="">(no candidates loaded)</option>';
      document.getElementById('edit-symbol-label').textContent = s ? `${s.exchange}:${s.symbol}` : `#${scripId}`;

      // V2: get_json action now returns DB data (no JSON file)
      apiPost({ action: 'get_json', scrip_id: scripId })
        .then(d => {
          _editData = d;
          // PNG files come from DB png_files column (populated by plumber.py)
          _pngFiles = (s && s.png_files) ? s.png_files : (d.png_files || []);
          _pngIdx = 0;
          document.getElementById('edit-loading-msg').style.display = 'none';
          updatePng();
          document.getElementById('ef-declared').value = d.declared_total ?? '';
          document.getElementById('ef-shp').value = d.shp_locked_total ?? '';
          buildRowsTable(d.rows || []);
        })
        .catch(err => { document.getElementById('edit-loading-msg').textContent = '⚠ ' + err.message; });
    }

    function closeEditOverlay() {
      document.getElementById('edit-overlay').style.display = 'none';
      _editScripId = null; _editJsonData = null;
    }

    async function loadCandidates() {
      if (!_editScripId) return;
      const s = allScrips.find(x => x.id == _editScripId);
      setEditStatus('Loading candidates…', '');
      const resp = await apiPost({ action: 'get_candidates', scrip_id: _editScripId, unique_symbol: s ? s.unique_symbol : '' });
      _editCandidates = resp.candidates || [];
      const sel = document.getElementById('recon-candidate-select');
      sel.innerHTML = '';
      if (!_editCandidates.length) {
        sel.innerHTML = '<option value="">(no candidates found)</option>';
        setEditStatus('No candidates found for this scrip.', '');
        return;
      }
      _editCandidates.forEach(c => {
        let payload = c.payload_json;
        if (typeof payload === 'string') {
          try { payload = JSON.parse(payload); } catch (e) { payload = {}; }
        }
        const h = (payload && payload.header) ? payload.header : {};
        const label = `#${c.id} ${c.source_pipeline} ${c.status} | computed=${h.computed_total ?? '-'} promoter=${h.promoter_shares ?? '-'} public=${h.public_shares ?? '-'} | ${c.created_at}`;
        const opt = document.createElement('option');
        opt.value = c.id;
        opt.textContent = label;
        sel.appendChild(opt);
      });
      setEditStatus(`Loaded ${_editCandidates.length} candidate(s).`, 'ok');
    }

    async function promoteSelectedCandidate() {
      if (!_editScripId) return;
      const sel = document.getElementById('recon-candidate-select');
      const candidateId = parseInt(sel.value || '0', 10);
      if (!candidateId) {
        setEditStatus('Select a candidate first.', 'error');
        return;
      }
      const by = (document.getElementById('recon-by').value || 'web_user').trim() || 'web_user';
      setEditStatus('Promoting candidate…', '');
      await apiPost({ action: 'promote_candidate', candidate_id: candidateId, promoted_by: by });

      const s = allScrips.find(x => x.id == _editScripId);
      const updated = await apiPost({ action: 'get_scrip', scrip_id: _editScripId, unique_symbol: s ? s.unique_symbol : '' });
      enrichScrip(updated);
      const idx = allScrips.findIndex(x => x.id == _editScripId);
      if (idx >= 0) allScrips[idx] = updated;
      render();
      setEditStatus(`✓ Candidate #${candidateId} promoted.`, 'ok');
    }

    async function quickPromote(scripId, candidateId) {
      const s = allScrips.find(x => x.id == scripId);
      if (!s || !candidateId) return;
      const by = (prompt('Promoted by:', 'web_user') || 'web_user').trim() || 'web_user';
      if (!confirm(`Promote candidate #${candidateId} for ${s.unique_symbol}?`)) return;
      try {
        await apiPost({ action: 'promote_candidate', candidate_id: candidateId, promoted_by: by });
        const updated = await apiPost({ action: 'get_scrip', scrip_id: scripId, unique_symbol: s.unique_symbol });
        enrichScrip(updated);
        const idx = allScrips.findIndex(x => x.id == scripId);
        if (idx >= 0) allScrips[idx] = { ...allScrips[idx], ...updated, candidate_promotable_count: 0, candidate_promotable_id: null };
        render();
      } catch (e) {
        alert('Promotion failed: ' + e.message);
      }
    }

    async function reconcileSymbol(scripId, uniqueSymbol) {
      const s = allScrips.find(x => x.id == scripId);
      if (!s) return;

      if (!confirm(`Generate reconciliation candidate for ${uniqueSymbol}?\n\nThis will run java extraction and create a new candidate.`)) return;

      try {
        // First, generate a new candidate
        alert('Generating candidate from java extraction...');
        await apiPost({ action: 'generate_candidate', unique_symbol: uniqueSymbol });

        // Now fetch the newly generated candidates
        const result = await apiPost({ action: 'get_candidates', scrip_id: scripId, unique_symbol: uniqueSymbol });
        const candidates = result.candidates || [];

        if (candidates.length === 0) {
          alert('No candidates found after generation. Check if java text files exist for this symbol.');
          return;
        }

        // Show candidates in a simple selection dialog
        const candidateList = candidates.map((c, idx) => {
          const payload = typeof c.payload_json === 'string' ? JSON.parse(c.payload_json) : c.payload_json;
          const locked = payload?.shp_locked_total || 'N/A';
          const promoter = payload?.promoter_shares || 'N/A';
          const public_val = payload?.public_shares || 'N/A';
          const status = c.status || 'N/A';
          const valid = c.is_valid === 1 ? '✓' : '✗';
          return `[${idx + 1}] ID=${c.id} ${c.source_pipeline}/${c.source_script} (${c.created_at})\n    Locked: ${locked}, Promoter: ${promoter}, Public: ${public_val}\n    Valid: ${valid}, Status: ${status}`;
        }).join('\n\n');

        const choice = prompt(`Found ${candidates.length} candidate(s):\n\n${candidateList}\n\nEnter candidate number to promote (1-${candidates.length}), or cancel:`);
        if (!choice) return;

        const idx = parseInt(choice) - 1;
        if (idx < 0 || idx >= candidates.length) {
          alert('Invalid choice');
          return;
        }

        const selectedCandidate = candidates[idx];
        const by = (prompt('Promoted by:', 'web_user') || 'web_user').trim() || 'web_user';

        if (!confirm(`Promote candidate #${selectedCandidate.id}?`)) return;

        await apiPost({ action: 'promote_candidate', candidate_id: selectedCandidate.id, promoted_by: by });
        const updated = await apiPost({ action: 'get_scrip', scrip_id: scripId, unique_symbol: uniqueSymbol });
        enrichScrip(updated);
        const scriptIdx = allScrips.findIndex(x => x.id == scripId);
        if (scriptIdx >= 0) allScrips[scriptIdx] = { ...allScrips[scriptIdx], ...updated };
        render();
        alert('✓ Candidate promoted successfully!');
      } catch (e) {
        alert('Reconciliation failed: ' + e.message);
      }
    }

    function updatePng() {
      const img = document.getElementById('edit-png');
      const nav = document.getElementById('edit-png-nav');
      const lbl = document.getElementById('edit-png-label');
      if (!_pngFiles.length) { document.getElementById('edit-loading-msg').textContent = '(no PNG available)'; return; }
      img.src = _pngFiles[_pngIdx].replace(/\\/g, '/');
      img.style.display = '';
      lbl.textContent = _pngFiles.length > 1 ? `${_pngIdx + 1} / ${_pngFiles.length}` : '';
      nav.style.display = _pngFiles.length > 1 ? '' : 'none';
      document.getElementById('edit-png-counter').textContent = `${_pngIdx + 1} / ${_pngFiles.length}`;
      applyPngDark();
    }

    function pngNav(dir) {
      _pngIdx = (_pngIdx + dir + _pngFiles.length) % _pngFiles.length;
      updatePng();
    }

    // ── Row editor ────────────────────────────────────────────────────────────────
    function buildRowsTable(rows) {
      document.getElementById('edit-rows-tbody').innerHTML = '';
      rows.forEach(r => appendEditRow(r));
      updateComputedTotal();
    }

    function appendEditRow(r) {
      const tr = document.createElement('tr');
      tr.innerHTML = `
    <td><input class="edit-input row-shares" type="number" value="${r.shares || 0}" min="0" oninput="updateComputedTotal()"></td>
    <td><input class="edit-input row-date"      type="text" value="${r.date || ''}"      placeholder="YYYY-MM-DD"></td>
    <td><input class="edit-input row-date-from" type="text" value="${r.date_from || ''}" placeholder="YYYY-MM-DD"></td>
    <td><input class="edit-input row-type"      type="text" value="${(r.type_raw || '').replace(/"/g, '&quot;')}"></td>
    <td>
      <select class="edit-select row-class">
        <option value="locked" ${r.row_class === 'locked' ? 'selected' : ''}>locked</option>
        <option value="anchor" ${r.row_class === 'anchor' ? 'selected' : ''}>anchor</option>
        <option value="free"   ${r.row_class === 'free' ? 'selected' : ''}>free</option>
      </select>
    </td>
    <td><button class="del-row-btn" title="Delete row" onclick="this.closest('tr').remove();updateComputedTotal()">×</button></td>`;
      document.getElementById('edit-rows-tbody').appendChild(tr);
    }

    function addEditRow() {
      appendEditRow({ shares: 0, date: '', date_from: '', type_raw: '', row_class: 'locked' });
      updateComputedTotal();
    }

    function updateComputedTotal() {
      const sum = [...document.querySelectorAll('.row-shares')].reduce((s, i) => s + (parseInt(i.value) || 0), 0);
      document.getElementById('ef-computed').value = sum.toLocaleString('en-IN');
    }

    function collectEditedData() {
      const rows = [...document.querySelectorAll('#edit-rows-tbody tr')].map(tr => ({
        shares: parseInt(tr.querySelector('.row-shares').value) || 0,
        date: tr.querySelector('.row-date').value.trim(),
        date_from: tr.querySelector('.row-date-from').value.trim(),
        type_raw: tr.querySelector('.row-type').value.trim(),
        row_class: tr.querySelector('.row-class').value,
      }));
      const dt = document.getElementById('ef-declared').value.replace(/,/g, '').trim();
      const shp = document.getElementById('ef-shp').value.replace(/,/g, '').trim();
      return {
        rows,
        declared_total: dt ? (parseInt(dt) || null) : null,
        shp_locked_total: shp ? (parseInt(shp) || null) : null,
        computed_total: rows.reduce((s, r) => s + (r.shares || 0), 0),
      };
    }

    function setEditStatus(msg, type) {
      const el = document.getElementById('edit-status');
      el.textContent = msg;
      el.className = type === 'ok' ? 'edit-status-ok' : type === 'error' ? 'edit-status-error' : '';
    }

    async function saveEdit() {
      const btn = document.getElementById('edit-save-btn');
      btn.disabled = true; btn.textContent = 'Saving…';
      try {
        const s = allScrips.find(x => x.id == _editScripId);
        if (btn.dataset.mode === 'rollback' && s) {
          setEditStatus('Running rollback…', '');
          await apiPost({ action: 'rollback_symbol', unique_symbol: s.unique_symbol, exchange: s.exchange });
          setEditStatus('Refreshing card…', '');
          const updated = await apiPost({ action: 'get_scrip', scrip_id: _editScripId, unique_symbol: s.unique_symbol });
          enrichScrip(updated);
          const idx = allScrips.findIndex(x => x.id == _editScripId);
          if (idx >= 0) allScrips[idx] = updated;
          render();
          setEditStatus('✓ Rollback completed.', 'ok');
          btn.textContent = 'Rolled back ✓';
          setTimeout(closeEditOverlay, 2000);
          return;
        }

        const payload = collectEditedData();

        // V2: write directly to DB (no JSON file), set manual_lock=1
        setEditStatus('Writing to DB…', '');
        const saveResult = await apiPost({ action: 'save_db', scrip_id: _editScripId, json_data: JSON.stringify(payload) });

        setEditStatus('Refreshing card…', '');
        const updated = await apiPost({ action: 'get_scrip', scrip_id: _editScripId, unique_symbol: s.unique_symbol });
        enrichScrip(updated);

        const idx = allScrips.findIndex(x => x.id == _editScripId);
        if (idx >= 0) { allScrips.splice(idx, 1); allScrips.push(updated); }
        const oldCard = document.getElementById(`sc-${_editScripId}`);
        if (oldCard) oldCard.remove();
        document.getElementById('report-body').insertAdjacentHTML('beforeend', renderScripCard(updated));

        setEditStatus('✓ Saved & locked.', 'ok');
        btn.textContent = 'Saved ✓';
        setTimeout(closeEditOverlay, 2000);
      } catch (e) {
        setEditStatus('Error: ' + e.message, 'error');
        btn.disabled = false; btn.textContent = (btn.dataset.mode === 'rollback') ? 'Rollback Symbol' : 'Save & Lock';
      }
    }

    // Close on backdrop click
    document.getElementById('edit-overlay').addEventListener('click', e => {
      if (e.target === document.getElementById('edit-overlay')) closeEditOverlay();
    });

    ['search', 'filter-exchange', 'filter-status', 'filter-finalized', 'filter-bucket', 'sort-by'].forEach(id =>
      document.getElementById(id).addEventListener('input', render)
    );

    let _pngDark = false;

    function applyPngDark() {
      const leftPanel = document.getElementById('edit-left');
      const btn = document.getElementById('png-dark-toggle');

      if (_pngDark) {
        leftPanel.classList.add('png-dark');
        btn.textContent = '☀ Light';
      } else {
        leftPanel.classList.remove('png-dark');
        btn.textContent = '🌙 Dark';
      }
    }

    function togglePngDark() {
      _pngDark = !_pngDark;
      applyPngDark();
    }

    let _pngZoom = 1;

    const ZOOM_STEP = 0.25;
    const ZOOM_MAX = 3;
    const ZOOM_MIN = 1;

    function updatePngZoom() {
      const img = document.getElementById('edit-png');
      img.style.transform = `scale(${_pngZoom})`;
      img.style.transformOrigin = 'top left';
      img.style.cursor = _pngZoom > 1 ? 'zoom-out' : 'zoom-in';
    }

    document.getElementById('edit-png').addEventListener('click', function (e) {
      if (_pngZoom < ZOOM_MAX) {
        _pngZoom += ZOOM_STEP;
      } else {
        _pngZoom = 1; // reset when max reached
      }
      updatePngZoom();
    });

    // optional: right-click to zoom out
    document.getElementById('edit-png').addEventListener('contextmenu', function (e) {
      e.preventDefault();
      if (_pngZoom > ZOOM_MIN) {
        _pngZoom -= ZOOM_STEP;
        updatePngZoom();
      }
    });


    loadData();
  </script>
</body>

</html>