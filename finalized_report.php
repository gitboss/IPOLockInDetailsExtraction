<?php
// VERSION: 2026-03-08-v3.0
$REPORT_VERSION = "finalized_report.php v3.0 (2026-03-08)";
// Replicates finalized_report_old.php look & feel, adapted for v2 DB schema
// Tables: ipo_processing_log (header) + ipo_lockin_rows (rows)

$env_path = __DIR__ . '/.env';
if (!file_exists($env_path))
  $env_path = __DIR__ . '/.env.example';
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

function has_scrip_meta_column(PDO $pdo): bool
{
  try {
    $stmt = $pdo->query("SHOW COLUMNS FROM ipo_processing_log LIKE 'scrip_meta'");
    return (bool) $stmt->fetch();
  } catch (Exception $e) {
    return false;
  }
}

function normalize_symbol_token($raw): string
{
  $v = strtoupper(trim((string) $raw));
  return preg_replace('/[^A-Z0-9\-]/', '', $v);
}

function rewrite_nse_basename(string $basename, string $oldSymbol, string $newSymbol): string
{
  $qOld = preg_quote($oldSymbol, '/');
  if (preg_match('/^' . $qOld . '-CML(\d+)\.pdf$/i', $basename, $m)) {
    return $newSymbol . '-CML' . $m[1] . '.pdf';
  }
  if (preg_match('/^SHP[-_]' . $qOld . '(.+)$/i', $basename, $m)) {
    return 'SHP-' . $newSymbol . $m[1];
  }
  if (stripos($basename, $oldSymbol) === 0) {
    return $newSymbol . substr($basename, strlen($oldSymbol));
  }
  return $basename;
}

function resolve_fs_path(string $baseDir, ?string $storedPath): ?string
{
  if (!$storedPath) {
    return null;
  }
  $p = str_replace('\\', '/', trim($storedPath));
  if ($p === '') {
    return null;
  }
  if (preg_match('/^[A-Za-z]:\//', $p) || strpos($p, '/') === 0) {
    if (strpos($p, '/nile/sme/notices/') === 0) {
      return $baseDir . substr($p, strlen('/nile/sme/notices'));
    }
    return $p;
  }
  return $baseDir . '/' . ltrim($p, '/');
}

function replace_basename_in_stored_path(?string $storedPath, string $newBase): ?string
{
  if (!$storedPath) {
    return $storedPath;
  }
  $p = str_replace('\\', '/', $storedPath);
  $dir = rtrim(dirname($p), '/');
  if ($dir === '.' || $dir === '') {
    return $newBase;
  }
  return $dir . '/' . $newBase;
}

// Lightweight API: toggle manual reviewed status from report UI
if ($_SERVER['REQUEST_METHOD'] === 'POST' && (($_GET['action'] ?? '') === 'toggle_manual_review')) {
  header('Content-Type: application/json');
  try {
    $pdo = make_pdo($env);
    if (!has_scrip_meta_column($pdo)) {
      throw new RuntimeException("scrip_meta column missing in ipo_processing_log");
    }

    $raw = file_get_contents('php://input');
    $payload = json_decode($raw ?: '{}', true);
    $id = isset($payload['id']) ? (int) $payload['id'] : 0;
    $manual_reviewed = !empty($payload['manual_reviewed']) ? 1 : 0;
    if ($id <= 0) {
      throw new InvalidArgumentException("Invalid id");
    }

    $stmt = $pdo->prepare("
      UPDATE ipo_processing_log
      SET scrip_meta = JSON_SET(COALESCE(scrip_meta, JSON_OBJECT()), '$.manual_reviewed', CAST(:manual_reviewed AS UNSIGNED))
      WHERE id = :id
    ");
    $stmt->execute([
      ':manual_reviewed' => $manual_reviewed,
      ':id' => $id
    ]);

    echo json_encode(['ok' => true, 'id' => $id, 'manual_reviewed' => $manual_reviewed]);
  } catch (Exception $e) {
    http_response_code(400);
    echo json_encode(['ok' => false, 'error' => $e->getMessage()]);
  }
  exit;
}

if ($_SERVER['REQUEST_METHOD'] === 'POST' && (($_GET['action'] ?? '') === 'rename_symbol')) {
  header('Content-Type: application/json');
  try {
    $pdo = make_pdo($env);
    $raw = file_get_contents('php://input');
    $payload = json_decode($raw ?: '{}', true);
    $id = isset($payload['id']) ? (int) $payload['id'] : 0;
    $newSymbol = normalize_symbol_token($payload['new_symbol'] ?? '');
    if ($id <= 0 || $newSymbol === '') {
      throw new InvalidArgumentException("Invalid id or symbol");
    }

    $pdo->beginTransaction();
    $stmt = $pdo->prepare("
      SELECT id, exchange, unique_symbol, file_name, finalized_at,
             lockin_pdf_path, shp_pdf_path, lockin_png_path,
             lockin_txt_java_path, lockin_txt_pdfplumber_path,
             shp_txt_java_path, shp_txt_pdfplumber_path
      FROM ipo_processing_log
      WHERE id = :id
      FOR UPDATE
    ");
    $stmt->execute([':id' => $id]);
    $rec = $stmt->fetch();
    if (!$rec) {
      throw new RuntimeException("Record not found");
    }
    if (($rec['exchange'] ?? '') !== 'NSE') {
      throw new RuntimeException("Rename supported only for NSE records");
    }
    if (!empty($rec['finalized_at'])) {
      throw new RuntimeException("Cannot rename finalized record");
    }

    // Mandatory NSE master check: new symbol must exist in sme_ipo_master.nse_symbol
    $masterChk = $pdo->prepare("
      SELECT 1
      FROM sme_ipo_master
      WHERE UPPER(CAST(nse_symbol AS CHAR)) = UPPER(:sym)
      LIMIT 1
    ");
    $masterChk->execute([':sym' => $newSymbol]);
    if (!$masterChk->fetch()) {
      throw new RuntimeException("NSE symbol not found in sme_ipo_master.nse_symbol: " . $newSymbol);
    }

    $oldSymbol = '';
    if (preg_match('/^NSE:(.+)$/i', (string) $rec['unique_symbol'], $m)) {
      $oldSymbol = normalize_symbol_token($m[1]);
    }
    if ($oldSymbol === '' && preg_match('/^([A-Z0-9\-]+)-CML\d+\.pdf$/i', (string) $rec['file_name'], $m)) {
      $oldSymbol = normalize_symbol_token($m[1]);
    }
    if ($oldSymbol === '') {
      throw new RuntimeException("Could not derive existing symbol");
    }
    if ($oldSymbol === $newSymbol) {
      $pdo->rollBack();
      echo json_encode(['ok' => true, 'id' => $id, 'symbol' => $newSymbol, 'message' => 'No change needed']);
      exit;
    }

    $oldFileName = (string) $rec['file_name'];
    if (!preg_match('/^[A-Z0-9\-]+-CML(\d+)\.pdf$/i', $oldFileName, $fm)) {
      throw new RuntimeException("Unexpected NSE file_name format: " . $oldFileName);
    }
    $newFileName = $newSymbol . '-CML' . $fm[1] . '.pdf';

    $dupeStmt = $pdo->prepare("
      SELECT id FROM ipo_processing_log
      WHERE exchange = 'NSE' AND file_name = :file_name AND id <> :id
      LIMIT 1
    ");
    $dupeStmt->execute([':file_name' => $newFileName, ':id' => $id]);
    if ($dupeStmt->fetch()) {
      throw new RuntimeException("Duplicate target file_name exists: " . $newFileName);
    }

    $pathCols = [
      'lockin_pdf_path',
      'shp_pdf_path',
      'lockin_png_path',
      'lockin_txt_java_path',
      'lockin_txt_pdfplumber_path',
      'shp_txt_java_path',
      'shp_txt_pdfplumber_path',
    ];

    $updates = [
      'unique_symbol' => 'NSE:' . $newSymbol,
      'file_name' => $newFileName,
    ];

    foreach ($pathCols as $col) {
      $oldPath = $rec[$col] ?? null;
      if (!$oldPath) {
        $updates[$col] = $oldPath;
        continue;
      }
      $oldBase = basename(str_replace('\\', '/', $oldPath));
      $newBase = rewrite_nse_basename($oldBase, $oldSymbol, $newSymbol);
      $updates[$col] = replace_basename_in_stored_path($oldPath, $newBase);
    }

    $renamed = [];
    $skipped = [];
    foreach ($pathCols as $col) {
      $oldStored = $rec[$col] ?? null;
      $newStored = $updates[$col] ?? null;
      if (!$oldStored || !$newStored || $oldStored === $newStored) {
        continue;
      }
      $oldFs = resolve_fs_path(__DIR__, $oldStored);
      $newFs = resolve_fs_path(__DIR__, $newStored);
      if (!$oldFs || !$newFs) {
        $skipped[] = "$col: unresolved path";
        continue;
      }
      if (!file_exists($oldFs)) {
        $skipped[] = "$col: source missing";
        continue;
      }
      if (file_exists($newFs)) {
        throw new RuntimeException("Target already exists for $col: " . basename($newFs));
      }
      $newDir = dirname($newFs);
      if (!is_dir($newDir)) {
        @mkdir($newDir, 0775, true);
      }
      if (!@rename($oldFs, $newFs)) {
        throw new RuntimeException("Failed to rename file for $col: " . basename($oldFs));
      }
      $renamed[] = "$col:" . basename($oldFs) . "->" . basename($newFs);
    }

    $upd = $pdo->prepare("
      UPDATE ipo_processing_log
      SET unique_symbol = :unique_symbol,
          file_name = :file_name,
          lockin_pdf_path = :lockin_pdf_path,
          shp_pdf_path = :shp_pdf_path,
          lockin_png_path = :lockin_png_path,
          lockin_txt_java_path = :lockin_txt_java_path,
          lockin_txt_pdfplumber_path = :lockin_txt_pdfplumber_path,
          shp_txt_java_path = :shp_txt_java_path,
          shp_txt_pdfplumber_path = :shp_txt_pdfplumber_path
      WHERE id = :id
    ");
    $upd->execute([
      ':unique_symbol' => $updates['unique_symbol'],
      ':file_name' => $updates['file_name'],
      ':lockin_pdf_path' => $updates['lockin_pdf_path'],
      ':shp_pdf_path' => $updates['shp_pdf_path'],
      ':lockin_png_path' => $updates['lockin_png_path'],
      ':lockin_txt_java_path' => $updates['lockin_txt_java_path'],
      ':lockin_txt_pdfplumber_path' => $updates['lockin_txt_pdfplumber_path'],
      ':shp_txt_java_path' => $updates['shp_txt_java_path'],
      ':shp_txt_pdfplumber_path' => $updates['shp_txt_pdfplumber_path'],
      ':id' => $id,
    ]);

    $pdo->commit();
    echo json_encode([
      'ok' => true,
      'id' => $id,
      'old_symbol' => $oldSymbol,
      'new_symbol' => $newSymbol,
      'file_name' => $newFileName,
      'renamed_files' => $renamed,
      'skipped' => $skipped,
    ]);
  } catch (Exception $e) {
    if (isset($pdo) && $pdo instanceof PDO && $pdo->inTransaction()) {
      $pdo->rollBack();
    }
    http_response_code(400);
    echo json_encode(['ok' => false, 'error' => $e->getMessage()]);
  }
  exit;
}

if ($_SERVER['REQUEST_METHOD'] === 'POST' && (($_GET['action'] ?? '') === 'update_bucket')) {
  header('Content-Type: application/json');
  try {
    $pdo = make_pdo($env);
    $raw = file_get_contents('php://input');
    $payload = json_decode($raw ?: '{}', true);
    $processingId = isset($payload['processing_id']) ? (int) $payload['processing_id'] : 0;
    $rowId = isset($payload['row_id']) ? (int) $payload['row_id'] : 0;
    $bucket = strtolower(trim((string) ($payload['bucket'] ?? '')));
    $allowed = ['3_year_plus', '2_year_plus', '1_year_plus', '1_year_minus', 'anchor_90', 'anchor_30', 'free'];

    if ($processingId <= 0 || $rowId <= 0 || !in_array($bucket, $allowed, true)) {
      throw new InvalidArgumentException("Invalid payload");
    }

    $stmt = $pdo->prepare("
      SELECT p.finalized_at
      FROM ipo_lockin_rows r
      INNER JOIN ipo_processing_log p ON p.id = r.processing_log_id
      WHERE r.id = :row_id AND r.processing_log_id = :processing_id
      LIMIT 1
    ");
    $stmt->execute([
      ':row_id' => $rowId,
      ':processing_id' => $processingId,
    ]);
    $chk = $stmt->fetch();
    if (!$chk) {
      throw new RuntimeException("Row not found");
    }
    if (!empty($chk['finalized_at'])) {
      throw new RuntimeException("Finalized scrip rows cannot be edited");
    }

    $upd = $pdo->prepare("UPDATE ipo_lockin_rows SET bucket = :bucket WHERE id = :row_id AND processing_log_id = :processing_id");
    $upd->execute([
      ':bucket' => $bucket,
      ':row_id' => $rowId,
      ':processing_id' => $processingId,
    ]);

    echo json_encode(['ok' => true, 'processing_id' => $processingId, 'row_id' => $rowId, 'bucket' => $bucket]);
  } catch (Exception $e) {
    http_response_code(400);
    echo json_encode(['ok' => false, 'error' => $e->getMessage()]);
  }
  exit;
}

if ($_SERVER['REQUEST_METHOD'] === 'POST' && (($_GET['action'] ?? '') === 'revalidate_snapshot')) {
  header('Content-Type: application/json');
  try {
    $pdo = make_pdo($env);
    $raw = file_get_contents('php://input');
    $payload = json_decode($raw ?: '{}', true);
    $id = isset($payload['id']) ? (int) $payload['id'] : 0;
    if ($id <= 0) {
      throw new InvalidArgumentException("Invalid id");
    }

    $stmt = $pdo->prepare("
      SELECT p.id, p.exchange, p.unique_symbol, p.status, p.finalized_at,
             p.computed_total, p.locked_total, p.free_total,
             p.shp_total_shares, p.shp_locked_shares, p.shp_promoter_shares, p.shp_public_shares, p.shp_others_shares,
             p.allotment_date, p.declared_total, p.anchor_letter_url
      FROM ipo_processing_log p
      WHERE p.id = :id
      LIMIT 1
    ");
    $stmt->execute([':id' => $id]);
    $rec = $stmt->fetch();
    if (!$rec) {
      throw new RuntimeException("Record not found");
    }
    if (!empty($rec['finalized_at'])) {
      throw new RuntimeException("Finalized records cannot be revalidated from overlay");
    }

    $rowsStmt = $pdo->prepare("
      SELECT shares, status, bucket, lockin_date_from, lockin_date_to
      FROM ipo_lockin_rows
      WHERE processing_log_id = :id
      ORDER BY row_order ASC, id ASC
    ");
    $rowsStmt->execute([':id' => $id]);
    $rows = $rowsStmt->fetchAll();

    $computed = (int) ($rec['computed_total'] ?? 0);
    $locked = (int) ($rec['locked_total'] ?? 0);
    $free = (int) ($rec['free_total'] ?? 0);
    $declared = (int) ($rec['declared_total'] ?? 0);
    $shpTotal = (int) ($rec['shp_total_shares'] ?? 0);
    $shpLocked = (int) ($rec['shp_locked_shares'] ?? 0);
    $promoter = (int) ($rec['shp_promoter_shares'] ?? 0);
    $public = (int) ($rec['shp_public_shares'] ?? 0);
    $others = (int) ($rec['shp_others_shares'] ?? 0);

    $ruleResults = [];
    $failed = [];
    $passCount = 0;

    $addRule = function($idRule, $passed, $message, $expected = null, $actual = null) use (&$ruleResults, &$failed, &$passCount) {
      $ruleResults[$idRule] = [
        'passed' => (bool) $passed,
        'message' => (string) $message,
        'expected' => $expected,
        'actual' => $actual,
      ];
      if ($passed) $passCount++;
      else $failed[] = $idRule;
    };

    // RULE1
    $r1 = ($locked + $free) === $computed;
    $addRule('RULE1', $r1, "Locked (" . number_format($locked) . ") + Free (" . number_format($free) . ") = " . number_format($locked + $free) . (($r1 ? " ==" : " !=") . " Computed Total (" . number_format($computed) . ")"), $computed, $locked + $free);

    // RULE2 (snapshot, strict equality only)
    $r2 = ($computed === $declared);
    $addRule('RULE2', $r2, "Computed Total (" . number_format($computed) . ")" . ($r2 ? " ==" : " !=") . " Declared Total (" . number_format($declared) . ")", $declared, $computed);

    // RULE5
    $sumShp = $promoter + $public + $others;
    $r5 = ($sumShp === $shpTotal);
    $addRule('RULE5', $r5, "Promoter (" . number_format($promoter) . ") + Public (" . number_format($public) . ") + Others (" . number_format($others) . ") = " . number_format($sumShp) . ($r5 ? " ==" : " !=") . " SHP Total (" . number_format($shpTotal) . ")", $shpTotal, $sumShp);

    // RULE3
    $r3 = ($shpTotal === $computed);
    $addRule('RULE3', $r3, "SHP Total (" . number_format($shpTotal) . ")" . ($r3 ? " ==" : " !=") . " Lock-in Total (" . number_format($computed) . ")", $computed, $shpTotal);

    // RULE4
    $r4 = ($shpLocked === $locked);
    $addRule('RULE4', $r4, "SHP Locked (" . number_format($shpLocked) . ")" . ($r4 ? " ==" : " !=") . " Lock-in Locked (" . number_format($locked) . ")", $locked, $shpLocked);

    // RULE6
    $anchor30 = 0;
    $anchor90 = 0;
    $badRule7 = 0;
    $badRule8 = 0;
    $badRule10 = 0;
    $allotment = !empty($rec['allotment_date']) ? $rec['allotment_date'] : null;
    $legacyCutoff = '2024-12-02';
    $ex = strtoupper((string) ($rec['exchange'] ?? ''));
    foreach ($rows as $rw) {
      $bucket = strtolower((string) ($rw['bucket'] ?? ''));
      $status = strtoupper((string) ($rw['status'] ?? ''));
      if ($bucket === 'anchor_30') $anchor30++;
      if ($bucket === 'anchor_90') $anchor90++;

      if ($status === 'LOCKED') {
        $to = $rw['lockin_date_to'] ?? null;
        $from = $rw['lockin_date_from'] ?? null;
        if ($to && $bucket === 'free') $badRule7++;
        if (!$to) {
          $badRule10++;
        } else {
          $start = $from ?: $allotment;
          if ($start) {
            $d1 = strtotime((string) $start);
            $d2 = strtotime((string) $to);
            if ($d1 !== false && $d2 !== false && $d2 < $d1) $badRule8++;
          }
        }
      }
    }
    $hasAnchorRows = ($anchor30 + $anchor90) > 0;
    $hasAnchorUrl = !empty(trim((string) ($rec['anchor_letter_url'] ?? '')));
    $isLegacy = (!empty($allotment) && $allotment <= $legacyCutoff && in_array($ex, ['NSE', 'BSE'], true));
    if ($hasAnchorUrl && $anchor30 > 0 && $anchor90 > 0) {
      $addRule('RULE6', true, "Anchor letter URL exists and both anchor buckets found (anchor_30={$anchor30}, anchor_90={$anchor90})", 1, $anchor30 + $anchor90);
    } elseif ($hasAnchorUrl) {
      if ($isLegacy) {
        $addRule('RULE6', true, "Anchor letter URL exists but missing required anchor bucket(s): " .
          ($anchor30 === 0 && $anchor90 === 0 ? "anchor_30, anchor_90" : ($anchor30 === 0 ? "anchor_30" : "anchor_90")) .
          " (anchor_30={$anchor30}, anchor_90={$anchor90}) (legacy {$ex} exception: allotment_date {$allotment} <= {$legacyCutoff})", 1, $anchor30 + $anchor90);
      } else {
        $addRule('RULE6', false, "Anchor letter URL exists but missing required anchor bucket(s): " .
          ($anchor30 === 0 && $anchor90 === 0 ? "anchor_30, anchor_90" : ($anchor30 === 0 ? "anchor_30" : "anchor_90")) .
          " (anchor_30={$anchor30}, anchor_90={$anchor90})", 1, $anchor30 + $anchor90);
      }
    } elseif (!$hasAnchorUrl && !$hasAnchorRows) {
      $addRule('RULE6', true, "No anchor letter URL and no anchor rows (correct)", 0, 0);
    } else {
      if ($isLegacy) {
        $addRule('RULE6', true, "No anchor letter URL but " . ($anchor30 + $anchor90) . " anchor row(s) found (legacy {$ex} exception: allotment_date {$allotment} <= {$legacyCutoff})", 0, $anchor30 + $anchor90);
      } else {
        $addRule('RULE6', false, "No anchor letter URL but " . ($anchor30 + $anchor90) . " anchor row(s) found (unexpected)", 0, $anchor30 + $anchor90);
      }
    }

    // RULE7 / RULE8 / RULE10
    $addRule('RULE7', $badRule7 === 0, $badRule7 === 0 ? "All locked rows with lock-in dates have non-free buckets" : "Found {$badRule7} locked row(s) with lock-in date but bucket=free", 0, $badRule7);
    $addRule('RULE8', $badRule8 === 0, $badRule8 === 0 ? "No negative lock-period rows found" : "Found {$badRule8} row(s) with negative lock period", 0, $badRule8);
    $addRule('RULE10', $badRule10 === 0, $badRule10 === 0 ? "All locked rows have valid lock-in upto dates" : "Found {$badRule10} locked row(s) with missing/invalid lock-in upto date", 0, $badRule10);

    $totalRules = count($ruleResults);
    $allPassed = ($passCount === $totalRules);
    $failedCsv = implode(',', $failed);
    $validationJson = json_encode($ruleResults, JSON_UNESCAPED_UNICODE);
    $errorMessage = null;
    if (!$allPassed) {
      $parts = [];
      foreach ($failed as $fr) {
        $msg = $ruleResults[$fr]['message'] ?? '';
        $parts[] = $fr . ": " . $msg;
      }
      $errorMessage = "Finalization skipped: Not all validation rules passed";
      if ($parts) {
        $errorMessage .= " | " . implode(" | ", $parts);
      }
    }

    $upd = $pdo->prepare("
      UPDATE ipo_processing_log
      SET validation_results = :validation_results,
          all_rules_passed = :all_rules_passed,
          failed_rules = :failed_rules,
          error_message = :error_message,
          status = 'VALIDATING',
          processed_at = NOW()
      WHERE id = :id
    ");
    $upd->execute([
      ':validation_results' => $validationJson,
      ':all_rules_passed' => $allPassed ? 1 : 0,
      ':failed_rules' => $failedCsv !== '' ? $failedCsv : null,
      ':error_message' => $errorMessage,
      ':id' => $id,
    ]);

    echo json_encode([
      'ok' => true,
      'id' => $id,
      'all_rules_passed' => $allPassed,
      'passed_rules' => $passCount,
      'total_rules' => $totalRules,
      'failed_rules' => $failed,
    ]);
  } catch (Exception $e) {
    http_response_code(400);
    echo json_encode(['ok' => false, 'error' => $e->getMessage()]);
  }
  exit;
}

$data_json = '[]';
try {
  $pdo = make_pdo($env);
  $has_scrip_meta = has_scrip_meta_column($pdo);
  $manual_reviewed_select = $has_scrip_meta
    ? "COALESCE(CAST(JSON_UNQUOTE(JSON_EXTRACT(p.scrip_meta, '$.manual_reviewed')) AS UNSIGNED), 0) AS manual_reviewed"
    : "0 AS manual_reviewed";
  $scrip_meta_select = $has_scrip_meta
    ? "p.scrip_meta"
    : "NULL AS scrip_meta";

  $records = $pdo->query("
    SELECT
      p.id, p.unique_symbol, p.exchange, p.file_name, p.status,
      p.computed_total, p.locked_total, p.free_total,
      p.shp_total_shares, p.shp_locked_shares, p.shp_promoter_shares, p.shp_public_shares, p.shp_others_shares,
      p.allotment_date, p.declared_total,
      p.validation_results, p.all_rules_passed, p.failed_rules,
      p.processed_at, p.finalized_at,
      p.error_message,
      {$manual_reviewed_select},
      {$scrip_meta_select},
      p.lockin_pdf_path, p.shp_pdf_path, p.lockin_png_path,
      p.lockin_txt_java_path, p.shp_txt_java_path,
      m.company_name, m.ipo_name, m.listing_date_actual,
      m.nse_symbol, m.bse_script_code
    FROM ipo_processing_log p
    LEFT JOIN sme_ipo_master m
      ON (p.exchange COLLATE utf8mb4_unicode_ci = 'BSE' COLLATE utf8mb4_unicode_ci
          AND CAST(m.bse_script_code AS CHAR) COLLATE utf8mb4_unicode_ci = SUBSTRING_INDEX(p.unique_symbol, ':', -1) COLLATE utf8mb4_unicode_ci)
      OR (p.exchange COLLATE utf8mb4_unicode_ci = 'NSE' COLLATE utf8mb4_unicode_ci
          AND UPPER(CAST(m.nse_symbol AS CHAR)) COLLATE utf8mb4_unicode_ci = UPPER(SUBSTRING_INDEX(p.unique_symbol, ':', -1)) COLLATE utf8mb4_unicode_ci)
    ORDER BY p.processed_at DESC
  ")->fetchAll();

  $rows_raw = $pdo->query("
    SELECT processing_log_id,
           MIN(lockin_date_from) AS lock_from,
           lockin_date_to   AS lock_upto,
           status           AS row_class,
           bucket           AS lock_bucket,
           DATEDIFF(lockin_date_to, MIN(lockin_date_from)) AS days_locked,
           MIN(security_type) AS type_raw,
           SUM(shares)      AS shares,
           COUNT(*)         AS _count
    FROM ipo_lockin_rows
    GROUP BY processing_log_id, lockin_date_to, status, bucket
    ORDER BY processing_log_id, row_class, lockin_date_to
  ")->fetchAll();

  $rows_by_record = [];
  foreach ($rows_raw as $r) {
    // Normalise row_class to lowercase (LOCKED→locked, FREE→free)
    $r['row_class'] = strtolower($r['row_class'] ?? 'free');
    $r['lock_bucket'] = strtolower($r['lock_bucket'] ?? '');
    $rows_by_record[$r['processing_log_id']][] = $r;
  }

  $ungrouped_raw = $pdo->query("
    SELECT processing_log_id,
           id               AS row_id,
           lockin_date_from AS lock_from,
           lockin_date_to   AS lock_upto,
           status           AS row_class,
           bucket           AS lock_bucket,
           DATEDIFF(lockin_date_to, lockin_date_from) AS days_locked,
           security_type    AS type_raw,
           shares           AS shares,
           1                AS _count
    FROM ipo_lockin_rows
    ORDER BY processing_log_id, row_order ASC
  ")->fetchAll();

  $ungrouped_by_record = [];
  foreach ($ungrouped_raw as $r) {
    $r['row_class'] = strtolower($r['row_class'] ?? 'free');
    $r['lock_bucket'] = strtolower($r['lock_bucket'] ?? '');
    $ungrouped_by_record[$r['processing_log_id']][] = $r;
  }

  foreach ($records as &$rec) {
    $rec['rows'] = $rows_by_record[$rec['id']] ?? [];
    $rec['overlay_rows'] = $ungrouped_by_record[$rec['id']] ?? [];
    // [STRATEGY-TRACKING 2026-03-09] Decode validation_results JSON to access _strategies
    $rec['validation_results'] = $rec['validation_results'] ? json_decode($rec['validation_results'], true) : null;
    // Extract symbol and code from file_name (source of truth from ipo_processing_log)
    // BSE format: CODE-SYMBOL-Annexure-I.pdf
    // NSE format: SYMBOL-CML12345.pdf
    if (preg_match('/^([0-9]+)-([A-Z\-]+)-Annexure-I\.pdf$/', $rec['file_name'], $matches)) {
      $rec['exchange_code'] = $matches[1];  // e.g., 544324
      $rec['symbol'] = $matches[2];         // e.g., CITICHEM
    } elseif (preg_match('/^([A-Z0-9\-]+)-CML([0-9]+)\.pdf$/i', $rec['file_name'], $matches)) {
      $rec['symbol'] = strtoupper($matches[1]);       // e.g., NEPHRO
      $rec['exchange_code'] = 'CML' . $matches[2];    // e.g., CML62782
    } else {
      // Fallback: try to extract from unique_symbol
      $parts = explode(':', $rec['unique_symbol']);
      $rec['exchange_code'] = count($parts) > 1 ? $parts[1] : null;
      $rec['symbol'] = $rec['nse_symbol'] ?? $rec['exchange_code'];
    }
    $rec['company_name'] = $rec['company_name'] ?? $rec['ipo_name'] ?? null;
    $rec['listing_date_actual'] = $rec['listing_date_actual'] ?? null;
    $rec['promoter_shares'] = $rec['shp_promoter_shares'];
    $rec['public_shares'] = $rec['shp_public_shares'];
    $rec['other_shares'] = $rec['shp_others_shares'];
    $rec['total_shares'] = $rec['shp_total_shares'];
    $rec['shp_locked_total'] = $rec['shp_locked_shares'];
    $rec['finalized'] = !empty($rec['finalized_at']);
    $rec['manual_reviewed'] = !empty($rec['manual_reviewed']);
    $rec['scrip_meta'] = $rec['scrip_meta'] ? json_decode($rec['scrip_meta'], true) : null;
    $rec['manual_lock'] = false;
    $rec['locked_forever'] = false;
    $rec['total_match'] = ($rec['status'] === 'PASS' || $rec['status'] === 'SHP_PASS') ? 'OK' : 'MISMATCH';
    $rec['shp_match'] = ($rec['status'] === 'SHP_PASS') ? 'OK' : null;
    $rec['engines_used'] = 'pdfplumber+java';
    $rec['png_files'] = $rec['lockin_png_path'] ? [$rec['lockin_png_path']] : [];
    $rec['pdf_file'] = $rec['lockin_pdf_path'] ?? '';
    $rec['lockin_txt_java'] = $rec['lockin_txt_java_path'] ?? '';
    $rec['shp_txt_java'] = $rec['shp_txt_java_path'] ?? '';
    $rec['gemini_lockin_match'] = null;
    $rec['gemini_shp_match'] = null;
    $rec['gemini_split_match'] = null;
    $rec['candidate_promotable_count'] = 0;
    $rec['candidate_promotable_id'] = null;
    $rec['candidate_promotable_source'] = null;
    $rec['candidate_not_promotable_reason'] = null;
    $rec['candidate_snapshots'] = [];
    $rec['candidate_total_match'] = null;
    $rec['candidate_shp_match'] = null;
  }
  unset($rec);

  $data_json = json_encode(array_values($records), JSON_UNESCAPED_UNICODE | JSON_HEX_TAG | JSON_HEX_APOS | JSON_HEX_QUOT);
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

    .copy-chip {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 4px 8px;
      border: 1px solid var(--border2);
      border-radius: 6px;
      background: var(--surface);
      color: var(--text);
      font-size: 11px;
      cursor: pointer;
      user-select: none;
      max-width: 360px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .copy-chip:hover { border-color: var(--blue); }

    .manual-review-wrap {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      font-size: 11px;
      color: var(--muted);
      margin-left: 8px;
      user-select: none;
    }

    .manual-review-wrap input[type="checkbox"] {
      width: 14px;
      height: 14px;
      cursor: pointer;
      accent-color: var(--green);
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

    .c-class {
      width: 70px;
    }

    .c-shares {
      width: 100px;
    }

    .c-from {
      width: 90px;
    }

    .c-upto {
      width: 90px;
    }

    .c-days {
      width: 60px;
    }

    .c-bucket {
      width: 80px;
    }

    .c-type {
      width: 90px;
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

    .bk-anchor_30,
    .bk-anchor_30_days,
    .bk-anchor_30days {
      background: #2a1f3d;
      color: var(--purple);
    }

    .bk-anchor_90,
    .bk-anchor_90_days,
    .bk-anchor_90days {
      background: #271d3a;
      color: #a37eee;
    }

    .bk-1_year_minus,
    .bk-1-year-minus {
      background: #1a2e2e;
      color: #3dd5d5;
    }

    .bk-1_year_plus,
    .bk-1-year-plus,
    .bk-1+year,
    .bk-years_1_plus {
      background: #1a2e1a;
      color: var(--green);
    }

    .bk-2_year_plus,
    .bk-2-year-plus,
    .bk-2+years,
    .bk-years_2_plus {
      background: #162a16;
      color: #3da53d;
    }

    .bk-3_year_plus,
    .bk-3-year-plus,
    .bk-3+years,
    .bk-years_3_plus {
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
      <div class="stat-pill" id="stat-total">- records</div>
      <div class="stat-pill" id="stat-bse">📊 BSE -</div>
      <div class="stat-pill" id="stat-nse">📈 NSE -</div>
      <div class="stat-pill" style="color:var(--muted);font-size:10px"><?php echo $REPORT_VERSION; ?></div>
    </div>
  </div>

  <div class="controls">
    <input type="search" id="search" placeholder="Search symbol..." autocomplete="off">
    <label>Exchange
      <select id="filter-exchange">
        <option value="">All</option>
        <option value="BSE">BSE</option>
        <option value="NSE">NSE</option>
      </select>
    </label>
    <label>Finalized
      <select id="filter-finalized">
        <option value="">All</option>
        <option value="1">Finalized</option>
        <option value="0">Not Finalized</option>
      </select>
    </label>
    <label>Manual Review
      <select id="filter-manual-reviewed">
        <option value="">All</option>
        <option value="1">Reviewed</option>
        <option value="0">Not Reviewed</option>
      </select>
    </label>
    <label>Bucket
      <select id="filter-bucket">
        <option value="">All</option>
        <option value="anchor_30">Anchor 30d</option>
        <option value="anchor_90">Anchor 90d</option>
        <option value="1_year_minus">&lt;1 Year</option>
        <option value="1_year_plus">1 Year+</option>
        <option value="2_year_plus">2 Years+</option>
        <option value="3_year_plus">3 Years+</option>
        <option value="free">Free</option>
      </select>
    </label>
    <label>Hide Blank TXT
      <span style="display: inline-flex; gap: 8px; align-items: center;">
        <input type="checkbox" id="hide-blank-lockin" value="1"> LockIn
        <input type="checkbox" id="hide-blank-shp" value="1"> SHP
      </span>
    </label>
    <label>Sort
      <select id="sort-by">
        <option value="listing_date_actual" selected>Listing Date ↓</option>
        <option value="symbol">Symbol</option>
        <option value="allotment_date">Allotment Date</option>
        <option value="company_name">Company Name</option>
        <option value="exchange">Exchange</option>
        <option value="status">Status</option>
        <option value="locked_total">Locked Shares</option>
      </select>
    </label>
    <span id="count-label"></span>
  </div>

  <div class="report-body" id="report-body"></div>
  <button id="top-btn" onclick="window.scrollTo({top:0,behavior:'smooth'})">^</button>

  <!-- ── Edit overlay ── -->
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
        📋 Detail — <span id="edit-symbol-label" style="color:var(--accent)"></span>
        <button class="edit-btn" id="btn-revalidate-overlay" onclick="revalidateCurrentScrip()" title="ReValidate current snapshot (no re-parse)">♻ ReValidate</button>
        <button class="edit-close-btn" onclick="closeEditOverlay()" title="Close">✕</button>
      </div>
      <div id="edit-form-wrap">
        <div class="edit-section">
          <div class="edit-section-title">Metadata</div>
          <div class="edit-meta-grid">
            <div class="edit-field"><label>Computed Total</label><input class="edit-input" id="ef-computed" readonly
                style="color:var(--muted)"></div>
            <div class="edit-field"><label>Locked Total</label><input class="edit-input" id="ef-locked" readonly
                style="color:var(--accent)"></div>
            <div class="edit-field"><label>Free Total</label><input class="edit-input" id="ef-free" readonly
                style="color:var(--green)"></div>
            <div class="edit-field"><label>Declared Total</label><input class="edit-input" id="ef-declared" readonly
                style="color:var(--muted)"></div>
            <div class="edit-field"><label>SHP Total</label><input class="edit-input" id="ef-shp-total" readonly
                style="color:var(--muted)"></div>
            <div class="edit-field"><label>SHP Locked</label><input class="edit-input" id="ef-shp-locked" readonly
                style="color:var(--muted)"></div>
            <div class="edit-field"><label>Promoter</label><input class="edit-input" id="ef-promoter" readonly
                style="color:var(--muted)"></div>
            <div class="edit-field"><label>Public</label><input class="edit-input" id="ef-public" readonly
                style="color:var(--muted)"></div>
            <div class="edit-field"><label>Allotment Date</label><input class="edit-input" id="ef-allotment" readonly
                style="color:var(--blue)"></div>
            <div class="edit-field"><label>Processed At</label><input class="edit-input" id="ef-processed" readonly
                style="color:var(--muted)"></div>
            <div class="edit-field"><label>Lock-in Strategy</label><input class="edit-input" id="ef-lockin-strategy" readonly
                style="color:var(--purple)"></div>
            <div class="edit-field"><label>SHP Strategy</label><input class="edit-input" id="ef-shp-strategy" readonly
                style="color:var(--purple)"></div>
          </div>
        </div>
        <div class="edit-section">
          <div class="edit-section-title">Lock-in Rows</div>
          <div class="table-wrap">
            <table class="edit-rows-table">
              <colgroup>
                <col class="c-class">
                <col class="c-shares">
                <col class="c-from">
                <col class="c-upto">
                <col class="c-days">
                <col class="c-bucket">
                <col class="c-type">
              </colgroup>
              <thead>
                <tr>
                  <th>Status</th>
                  <th>Shares</th>
                  <th>Lock From</th>
                  <th>Lock Upto</th>
                  <th>Bucket</th>
                  <th>Type</th>
                </tr>
              </thead>
              <tbody id="edit-rows-tbody"></tbody>
            </table>
          </div>
        </div>
      </div>
      <div class="edit-footer">
        <span id="edit-status"></span>
        <button id="edit-save-btn" onclick="closeEditOverlay()">Close</button>
      </div>
    </div>
  </div>

  <script>
    let allScrips = [];

    function fmt(n) {
      if (n == null || n === '') return '-';
      return Number(n).toLocaleString('en-IN');
    }

    function fmtBucket(bucket) {
      if (!bucket) return '-';
      const map = {
        'anchor_30': 'Anchor 30d',
        'anchor_90': 'Anchor 90d',
        '1_year_minus': '<1 Year',
        '1_year_plus': '1 Year+',
        '2_year_plus': '2 Years+',
        '3_year_plus': '3 Years+',
        'free': 'Free',
        'unknown': 'Unknown'
      };
      return map[bucket.toLowerCase()] || bucket;
    }

    function normalizeWebPath(p) {
      if (!p) return '';
      let s = String(p).replace(/\\/g, '/').trim();

      // Convert server filesystem paths to public web paths.
      // Example: /home/bluenile/web/gifed.com/public_html/nile/... -> /nile/...
      const publicHtmlIdx = s.toLowerCase().indexOf('/public_html');
      if (publicHtmlIdx !== -1) {
        s = s.substring(publicHtmlIdx + '/public_html'.length);
      } else {
        s = s
          .replace(/^\/home\/[^/]+\/web\/[^/]+\/public_html/i, '')
          .replace(/^home\/[^/]+\/web\/[^/]+\/public_html/i, '');
      }

      if (s && !s.startsWith('/') && /^(nile|downloads|finalized)\//i.test(s)) {
        s = '/' + s;
      }
      return s;
    }

    function escapeHtml(str) {
      return String(str ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
    }

    function renderFinalizationIssue(s) {
      if (!s.error_message) return '';
      const raw = String(s.error_message);
      const parts = raw.split('|').map(p => p.trim()).filter(Boolean);
      const body = parts.length > 1
        ? `<ul style="margin:6px 0 0 16px;padding:0">${parts.map(p => `<li>${escapeHtml(p)}</li>`).join('')}</ul>`
        : `<div style="margin-top:6px">${escapeHtml(raw)}</div>`;

      const bucketSchemaHint = raw.toLowerCase().includes('persisted bucket validation failed')
        ? `<div style="margin-top:8px;font-weight:700;color:#991b1b">Action: DB bucket values are non-canonical. Apply bucket ENUM/data migration, then reprocess this symbol.</div>`
        : '';

      return `<div style="grid-column:1/-1;background:#451a1a;border:1px solid #991b1b;border-radius:6px;padding:8px 10px;margin-top:4px;font-size:11px;color:#fca5a5">
        <strong>Finalization Failed</strong>
        ${body}
        ${bucketSchemaHint}
      </div>`;
    }

    function getEffectiveStatus(s) {
      return s.status || '';
    }

    async function copyText(value) {
      try {
        await navigator.clipboard.writeText(value);
      } catch (e) {
        // no-op fallback (clipboard permission may be blocked)
      }
    }

    function copyEncoded(value) {
      if (!value) return;
      try {
        copyText(decodeURIComponent(value));
      } catch (e) {
        // ignore malformed encoding
      }
    }

    function buildEditorUrl(filePath, s, typeLabel) {
      const params = new URLSearchParams();
      params.set('file', filePath || '');
      params.set('symbol', s.symbol || '');
      params.set('code', s.exchange_code || '');
      params.set('company', s.company_name || '');
      params.set('type', typeLabel || 'TXT');
      return `txt_editor.php?${params.toString()}`;
    }

    function enrichScrip(s) {
      const locked = (s.rows || []).filter(r => r.row_class === 'locked' || r.row_class === 'anchor');
      const free = (s.rows || []).filter(r => r.row_class === 'free');
      s.locked_shares = locked.reduce((a, r) => a + (+r.shares || 0), 0);
      s.free_shares = free.reduce((a, r) => a + (+r.shares || 0), 0);
      s.effective_status = getEffectiveStatus(s);
      return s;
    }

    function renderScripCard(s) {
      const isFinalized = !!s.finalized;
      const effectiveStatus = s.effective_status || getEffectiveStatus(s);
      // Top summary block uses lock-in math (locked/free), so total should prefer lock-in computed total.
      const totalShares = Number(s.computed_total || s.total_shares) || 0;
      const lockedShares = s.locked_shares || 0;
      const freeShares = s.free_shares || 0;
      const lockedPct = totalShares ? ((lockedShares / totalShares) * 100).toFixed(1) : '-';

      const ps = Number(s.promoter_shares) || 0;
      const pubs = Number(s.public_shares) || 0;
      const tot = Number(s.total_shares) || 0;
      const shpSplitMatch = (ps + pubs) <= tot && tot > 0;
      const psPct = tot ? ((ps / tot) * 100).toFixed(1) : '0.0';
      const pubsPct = tot ? ((pubs / tot) * 100).toFixed(1) : '0.0';

      const shpSplitStr = shpSplitMatch
        ? `<span class="match-ok">MATCH</span>`
        : `<span class="match-fail">MISMATCH</span>`;

      const finalizedStr = isFinalized
        ? `<span class="match-ok">FINALIZED</span>`
        : `<span class="match-none">NOT FINALIZED</span>`;

      const errorMessageStr = renderFinalizationIssue(s);

      const validStr = (() => {
        const st = effectiveStatus.toUpperCase();
        if (st === 'PASS' || st === 'SHP_PASS') return `<span class="match-ok">OK MATCH</span>`;
        if (st === 'FAIL' || st === 'SHP_FAIL' || st === 'FAILED') return `<span class="match-fail">FAIL</span>`;
        if (st === 'MANUAL_LOCKED') return `<span class="match-ok">MANUAL LOCK</span>`;
        if (st === 'AUTO_LOCKED') return `<span class="match-ok">AUTO LOCK</span>`;
        return `<span class="match-none">${st}</span>`;
      })();

      // Build file paths - finalized files are moved to 'finalized/' subfolder in same directory
      const pdfFile = normalizeWebPath(s.pdf_file || s.lockin_pdf_path || '');
      // Prefer DB file_name to avoid stale basename from lockin_pdf_path.
      const pdfName = (s.file_name && String(s.file_name).trim()) ? String(s.file_name).trim() : (pdfFile ? pdfFile.split('/').pop() : '');
      const stem = pdfName ? pdfName.replace(/\.pdf$/i, '') : '';
      const shpName = s.exchange === 'BSE' ? pdfName.replace('I.', 'II.') : 'SHP-' + (s.symbol || '') + '.pdf';

      // Build base paths by extracting directory from stored paths
      const pdfBase = pdfFile ? pdfFile.substring(0, pdfFile.lastIndexOf('/') + 1) : '';
      const shpStored = normalizeWebPath(s.shp_pdf_path || '');
      const shpBase = shpStored ? shpStored.substring(0, shpStored.lastIndexOf('/') + 1) : pdfBase.replace('pdf/lockin', 'pdf/shp');
      const pngBase = Array.isArray(s.png_files) && s.png_files.length
        ? normalizeWebPath(s.png_files[0]).substring(0, normalizeWebPath(s.png_files[0]).lastIndexOf('/') + 1)
        : pdfBase.replace('pdf/lockin', 'pdf/lockin/png');

      // TXT file paths from database
      const lockinTxtFile = normalizeWebPath(s.lockin_txt_java || '');
      const shpTxtFile = normalizeWebPath(s.shp_txt_java || '');
      const lockinTxtBase = lockinTxtFile ? lockinTxtFile.substring(0, lockinTxtFile.lastIndexOf('/') + 1) : '';
      const shpTxtBase = shpTxtFile ? shpTxtFile.substring(0, shpTxtFile.lastIndexOf('/') + 1) : '';

      // For finalized files, insert '/finalized/' into the path
      const pdfPathFinalized = isFinalized && pdfBase ? pdfBase.replace(/\/pdf\/lockin\/$/, '/pdf/lockin/finalized/') : pdfBase;
      const shpPathFinalized = isFinalized && shpBase ? shpBase.replace(/\/pdf\/shp\/$/, '/pdf/shp/finalized/') : shpBase;
      const pngPathFinalized = isFinalized && pngBase ? pngBase.replace(/\/pdf\/lockin\/png\/$/, '/pdf/lockin/png/finalized/') : pngBase;
      const lockinTxtPathFinalized = isFinalized && lockinTxtBase ? lockinTxtBase.replace(/\/txt\/$/, '/txt/finalized/') : lockinTxtBase;
      const shpTxtPathFinalized = isFinalized && shpTxtBase ? shpTxtBase.replace(/\/txt\/$/, '/txt/finalized/') : shpTxtBase;

      // Get filenames
      const lockinTxtName = lockinTxtFile ? lockinTxtFile.split('/').pop() : (stem + '_java.txt');
      const shpStem = s.exchange === 'BSE' ? stem.replace('Annexure-I', 'Annexure-II') : 'SHP-' + (s.symbol || '');
      const shpTxtName = shpTxtFile ? shpTxtFile.split('/').pop() : (shpStem + '_java.txt');

      const lockinTxtHref = isFinalized
        ? `${lockinTxtPathFinalized}${lockinTxtName}`
        : buildEditorUrl(s.lockin_txt_java || lockinTxtFile, s, 'Lock-in TXT');
      const shpTxtHref = isFinalized
        ? `${shpTxtPathFinalized}${shpTxtName}`
        : buildEditorUrl(s.shp_txt_java || shpTxtFile, s, 'SHP TXT');

      const linksHtml = pdfName ? `
    <div class="card-links">
      <a class="link-btn" href="${pdfPathFinalized}${pdfName}" target="_blank">📄 PDF</a>
      <a class="link-btn" href="${shpPathFinalized}${shpName}" target="_blank">📊 SHP PDF</a>
      <a class="link-btn" href="${pngPathFinalized}${stem}.png" target="_blank">🖼 PNG</a>
      <span style="color:var(--muted);margin:0 4px">|</span>
      <a class="link-btn" href="${lockinTxtHref}" target="_blank">📝 Lock-in TXT</a>
      <a class="link-btn" href="${shpTxtHref}" target="_blank">📝 SHP TXT</a>
    </div>` : '';

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
            <td class="rc-${r.row_class || 'free'}">${r.row_class || '-'}</td>
            <td class="num">${fmt(r.shares)}${(+r._count || 0) > 1 ? ` <small style="color:var(--muted)">(${r._count})</small>` : ''}</td>
            <td>${r.lock_from || '<span style="color:var(--muted)">-</span>'}</td>
            <td>${r.lock_upto || '<span style="color:var(--muted)">-</span>'}</td>
            <td class="num">${r.days_locked != null ? r.days_locked + 'd' : '<span style="color:var(--muted)">-</span>'}</td>
            <td><span class="bucket-pill bk-${(r.lock_bucket || 'free').replace(/[^a-z0-9_]/g, '-')}">${fmtBucket(r.lock_bucket || '')}</span></td>
            <td style="color:var(--muted);max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${(r.type_raw || '').replace(/"/g, '&quot;')}">${r.type_raw || '-'}</td>
          </tr>`).join('')}
        </tbody>
      </table></div>`;

      const companyName = s.company_name || '';
      return `
  <div class="scrip-card" id="sc-${s.id}">
    <div class="card-header">
      <div style="display:flex;flex-direction:column;gap:4px">
        <div style="display:flex;align-items:center;gap:8px">
          <span class="card-symbol">${s.symbol || s.unique_symbol || ''}</span>
          ${s.exchange_code ? `<span style="font-size:11px;color:var(--muted)">${s.exchange_code}</span>` : ''}
          ${pdfName ? `<div class="copy-chip" title="Click to copy lock-in filename" data-copy="${encodeURIComponent(pdfName)}" onclick="copyEncoded(this.getAttribute('data-copy'))">📄 ${pdfName}</div>` : ''}
          <label class="manual-review-wrap" title="Mark manually reviewed">
            <input type="checkbox" data-manual-review-id="${s.id}" ${s.manual_reviewed ? 'checked' : ''} onchange="toggleManualReviewed(this)">
            ✓ Reviewed
          </label>
        </div>
      </div>
      <span class="badge ex-${s.exchange || 'BSE'}">${s.exchange || ''}</span>
      <span class="badge st-${effectiveStatus.replace(/[^a-zA-Z0-9]/g, '_').toUpperCase()}">${effectiveStatus}</span>
      <span style="font-size:11px">${validStr}</span>
      <span style="font-size:11px">${finalizedStr}</span>
      ${(!isFinalized && (s.exchange || '').toUpperCase() === 'NSE') ? `<button class="edit-btn" onclick="renameSymbol(${s.id}, '${(s.symbol || '').replace(/'/g, "\\'")}')" title="Rename symbol + files">✎ Rename Symbol</button>` : ''}
      <button class="edit-btn" onclick="openDetailOverlay(${s.id})" title="View detail">📋 Detail</button>
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
        <div style="color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:0.5px;padding-bottom:2px">Listing Date</div>
        <div style="color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:0.5px;text-align:right;padding-bottom:2px">Promoter</div>
        <div style="color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:0.5px;text-align:right;padding-bottom:2px">Public</div>
        <div style="color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:0.5px;text-align:right;padding-bottom:2px">Total SHP</div>
        <div style="color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:0.5px;text-align:right;padding-bottom:2px;grid-column:span 2">SHP Locked</div>

        <div style="color:var(--cyan);font-weight:700;font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${s.listing_date_actual || '-'}</div>
        <div style="text-align:right;font-weight:700;font-size:13px;white-space:nowrap;${shpSplitMatch ? '' : 'color:var(--red)'}">${fmt(s.promoter_shares)} <small style="font-weight:400;color:var(--muted)">(${psPct}%)</small></div>
        <div style="text-align:right;font-weight:700;font-size:13px;white-space:nowrap;${shpSplitMatch ? '' : 'color:var(--red)'}">${fmt(s.public_shares)} <small style="font-weight:400;color:var(--muted)">(${pubsPct}%)</small></div>
        <div style="text-align:right;font-weight:700;font-size:13px">${fmt(s.total_shares)}</div>
        <div style="text-align:right;grid-column:span 2">${fmt(s.shp_locked_total)}</div>
      </div>
      ${errorMessageStr}
    </div>
    ${linksHtml}
    ${rowsHtml}
  </div>`;
    }

    // ── Data load ─────────────────────────────────────────────────────────────────
    function loadData() {
      try {
        allScrips = <?php echo $data_json; ?>;
        if (allScrips.length && allScrips[0].error) throw new Error(allScrips[0].error);
        allScrips.forEach(enrichScrip);
        const bse = allScrips.filter(s => (s.exchange || '').toUpperCase() === 'BSE').length;
        const nse = allScrips.filter(s => (s.exchange || '').toUpperCase() === 'NSE').length;
        document.getElementById('stat-total').innerHTML = `<strong>${allScrips.length}</strong> records`;
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
      const finalizedFilter = document.getElementById('filter-finalized').value;
      const manualReviewedFilter = document.getElementById('filter-manual-reviewed').value;
      const bucket = document.getElementById('filter-bucket').value;
      const sortBy = document.getElementById('sort-by').value;
      const hideBlankLockin = document.getElementById('hide-blank-lockin').checked;
      const hideBlankShp = document.getElementById('hide-blank-shp').checked;

      let scrips = allScrips.filter(s => {
        if (q) {
          const sym = (s.symbol || s.unique_symbol || '').toLowerCase();
          const comp = (s.company_name || '').toLowerCase();
          if (!sym.includes(q) && !comp.includes(q)) return false;
        }
        if (exch && (s.exchange || '').toUpperCase() !== exch) return false;
        if (finalizedFilter !== '' && String(s.finalized ? 1 : 0) !== finalizedFilter) return false;
        if (manualReviewedFilter !== '' && String(s.manual_reviewed ? 1 : 0) !== manualReviewedFilter) return false;
        if (bucket && !(s.rows || []).some(r => (r.lock_bucket || '').toLowerCase() === bucket)) return false;
        
        // [BLANK-TXT 2026-03-09] Hide blank TXT files
        if (hideBlankLockin && s.error_message && s.error_message.includes('Blank lock-in')) return false;
        if (hideBlankShp && s.error_message && s.error_message.includes('Blank SHP')) return false;
        
        return true;
      });

      scrips.sort((a, b) => {
        const av = a[sortBy] ?? '';
        const bv = b[sortBy] ?? '';
        if (typeof av === 'number' && typeof bv === 'number') return bv - av;
        if (sortBy === 'allotment_date' || sortBy === 'listing_date_actual') return String(bv).localeCompare(String(av));
        return String(av).localeCompare(String(bv));
      });

      document.getElementById('count-label').textContent = `${scrips.length} / ${allScrips.length}`;
      const body = document.getElementById('report-body');
      if (!scrips.length) {
        body.innerHTML = '<div style="padding:40px;text-align:center;color:var(--muted)">No results</div>';
        return;
      }
      body.innerHTML = scrips.map(s => renderScripCard(s)).join('');
    }

    function renderEditableBucketSpan(bucketRaw, processingId, rowId, isFinalized) {
      const b = (bucketRaw || 'free').toLowerCase();
      const safeBucket = b.replace(/[^a-z0-9_]/g, '-');
      const label = fmtBucket(b);
      if (isFinalized || !rowId) {
        return `<span class="bucket-pill bk-${safeBucket}">${label}</span>`;
      }
      return `<span class="bucket-pill bk-${safeBucket}" data-bucket="${b}" data-row-id="${rowId}" title="Double-click to change bucket" ondblclick="beginBucketEdit(this, ${processingId}, ${rowId})">${label}</span>`;
    }

    function beginBucketEdit(el, processingId, rowId) {
      if (!el || !processingId || !rowId) return;
      const current = (el.getAttribute('data-bucket') || 'free').toLowerCase();
      const options = [
        'anchor_30',
        'anchor_90',
        '1_year_minus',
        '1_year_plus',
        '2_year_plus',
        '3_year_plus',
        'free'
      ];
      const select = document.createElement('select');
      select.style.fontSize = '11px';
      select.style.padding = '1px 4px';
      select.style.background = 'var(--card)';
      select.style.color = 'var(--text)';
      select.style.border = '1px solid var(--border2)';
      select.style.borderRadius = '4px';

      options.forEach(v => {
        const o = document.createElement('option');
        o.value = v;
        o.textContent = fmtBucket(v);
        if (v === current) o.selected = true;
        select.appendChild(o);
      });

      const parent = el.parentNode;
      if (!parent) return;
      parent.replaceChild(select, el);
      select.focus();

      let committed = false;
      const restore = (bucketToShow) => {
        if (!select.parentNode) return;
        const span = document.createElement('span');
        span.className = `bucket-pill bk-${(bucketToShow || current).replace(/[^a-z0-9_]/g, '-')}`;
        span.setAttribute('data-bucket', bucketToShow || current);
        span.setAttribute('data-row-id', String(rowId));
        span.title = 'Double-click to change bucket';
        span.textContent = fmtBucket(bucketToShow || current);
        span.ondblclick = () => beginBucketEdit(span, processingId, rowId);
        select.parentNode.replaceChild(span, select);
      };

      select.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
          committed = true;
          restore(current);
        }
      });

      select.addEventListener('blur', () => {
        if (!committed) restore(current);
      });

      select.addEventListener('change', async () => {
        committed = true;
        const nextBucket = select.value;
        if (nextBucket === current) {
          restore(current);
          return;
        }
        const ok = confirm(`Do you really wish to change the bucket from "${fmtBucket(current)}" to "${fmtBucket(nextBucket)}"?`);
        if (!ok) {
          restore(current);
          return;
        }
        try {
          const res = await fetch('finalized_report.php?action=update_bucket', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              processing_id: processingId,
              row_id: rowId,
              bucket: nextBucket
            })
          });
          const data = await res.json();
          if (!res.ok || !data.ok) {
            throw new Error((data && data.error) || `HTTP ${res.status}`);
          }
          restore(nextBucket);
          setTimeout(() => location.reload(), 120);
        } catch (err) {
          alert(`Bucket update failed: ${err.message}`);
          restore(current);
        }
      });
    }

    async function revalidateCurrentScrip() {
      if (!_editScripId) return;
      const s = allScrips.find(x => x.id == _editScripId);
      if (!s) return;
      if (s.finalized) {
        alert('Finalized scrip cannot be revalidated from overlay.');
        return;
      }
      const c1 = confirm('ReValidate this scrip using current edited DB rows (no re-parse)?');
      if (!c1) return;
      const c2 = confirm('Please confirm again: This will overwrite current validation results for this scrip.');
      if (!c2) return;

      const btn = document.getElementById('btn-revalidate-overlay');
      if (btn) btn.disabled = true;
      try {
        const res = await fetch('finalized_report.php?action=revalidate_snapshot', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ id: Number(_editScripId) })
        });
        const data = await res.json();
        if (!res.ok || !data.ok) {
          throw new Error((data && data.error) || `HTTP ${res.status}`);
        }
        alert(`ReValidate complete: ${data.passed_rules}/${data.total_rules} rules passed.`);
        location.reload();
      } catch (err) {
        alert(`ReValidate failed: ${err.message}`);
      } finally {
        if (btn) btn.disabled = false;
      }
    }

    async function toggleManualReviewed(el) {
      const id = Number(el.getAttribute('data-manual-review-id') || 0);
      if (!id) return;
      const manualReviewed = !!el.checked;
      el.disabled = true;
      try {
        const res = await fetch('finalized_report.php?action=toggle_manual_review', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ id, manual_reviewed: manualReviewed })
        });
        const data = await res.json();
        if (!res.ok || !data.ok) {
          throw new Error((data && data.error) || `HTTP ${res.status}`);
        }
        const s = allScrips.find(x => Number(x.id) === id);
        if (s) s.manual_reviewed = !!data.manual_reviewed;
      } catch (err) {
        el.checked = !manualReviewed;
        alert(`Failed to save manual review status: ${err.message}`);
      } finally {
        el.disabled = false;
        render();
      }
    }

    async function renameSymbol(id, currentSymbol) {
      const next = prompt(`Enter new NSE symbol for this scrip`, (currentSymbol || '').toUpperCase());
      if (!next) return;
      const newSymbol = String(next).trim().toUpperCase().replace(/[^A-Z0-9\-]/g, '');
      if (!newSymbol) {
        alert('Invalid symbol.');
        return;
      }
      if (newSymbol === String(currentSymbol || '').toUpperCase()) {
        return;
      }
      if (!confirm(`This will rename symbol/files from ${currentSymbol} to ${newSymbol} for this record. Continue?`)) {
        return;
      }
      try {
        const res = await fetch('finalized_report.php?action=rename_symbol', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ id, new_symbol: newSymbol })
        });
        const data = await res.json();
        if (!res.ok || !data.ok) {
          throw new Error((data && data.error) || `HTTP ${res.status}`);
        }
        alert(`Renamed to ${data.new_symbol}. File: ${data.file_name}`);
        location.reload();
      } catch (err) {
        alert(`Rename failed: ${err.message}`);
      }
    }

    // ── Detail overlay (read-only) ────────────────────────────────────────────────
    let _editScripId = null;
    let _pngFiles = [], _pngIdx = 0;

    function openDetailOverlay(scripId) {
      _editScripId = scripId;
      const s = allScrips.find(x => x.id == scripId);
      if (!s) return;

      const ov = document.getElementById('edit-overlay');
      ov.style.display = 'flex';

      document.getElementById('edit-symbol-label').textContent = s.unique_symbol || s.symbol || `#${scripId}`;
      const revalBtn = document.getElementById('btn-revalidate-overlay');
      if (revalBtn) revalBtn.disabled = !!s.finalized;

      // Populate read-only fields
      document.getElementById('ef-computed').value = fmt(s.computed_total);
      document.getElementById('ef-locked').value = fmt(s.locked_total || s.locked_shares);
      document.getElementById('ef-free').value = fmt(s.free_total || s.free_shares);
      document.getElementById('ef-declared').value = fmt(s.declared_total);
      document.getElementById('ef-shp-total').value = fmt(s.total_shares);
      document.getElementById('ef-shp-locked').value = fmt(s.shp_locked_total);
      document.getElementById('ef-promoter').value = fmt(s.promoter_shares);
      document.getElementById('ef-public').value = fmt(s.public_shares);
      document.getElementById('ef-allotment').value = s.allotment_date || '-';
      document.getElementById('ef-processed').value = s.processed_at || '-';
      
      // [STRATEGY-TRACKING 2026-03-09] Populate strategy fields from validation_results
      const strategies = s.validation_results?._strategies || {};
      document.getElementById('ef-lockin-strategy').value = strategies.lockin_strategy || '(requires re-processing)';
      document.getElementById('ef-shp-strategy').value = strategies.shp_strategy || '(requires re-processing)';

      // Rows table
      const tbody = document.getElementById('edit-rows-tbody');
      tbody.innerHTML = '';
      (s.overlay_rows || s.rows || []).forEach(r => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td class="rc-${r.row_class || 'free'}">${r.row_class || '-'}</td>
          <td>${fmt(r.shares)}${(+r._count || 0) > 1 ? ` <small style="color:var(--muted)">(${r._count})</small>` : ''}</td>
          <td>${r.lock_from || '-'}</td>
          <td>${r.lock_upto || '-'}</td>
          <td>${renderEditableBucketSpan(r.lock_bucket || 'free', s.id, r.row_id || 0, !!s.finalized)}</td>
          <td style="color:var(--muted);max-width:150px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${(r.type_raw || '').replace(/"/g, '&quot;')}">${r.type_raw || '-'}</td>
        `;
        tbody.appendChild(tr);
      });
      if (!s.rows || !s.rows.length) {
        tbody.innerHTML = '<tr><td colspan="6" style="color:var(--muted);text-align:center">No rows</td></tr>';
      }

      // PNG
      _pngFiles = Array.isArray(s.png_files)
        ? s.png_files.map(p => {
          let np = normalizeWebPath(p || '');
          if (s.finalized && np) {
            np = np.replace(/\/pdf\/lockin\/png\//, '/pdf/lockin/png/finalized/');
          }
          return np;
        }).filter(Boolean)
        : [];
      _pngIdx = 0;
      updatePng();
    }

    function closeEditOverlay() {
      document.getElementById('edit-overlay').style.display = 'none';
      _editScripId = null;
    }

    function updatePng() {
      const img = document.getElementById('edit-png');
      const nav = document.getElementById('edit-png-nav');
      const lbl = document.getElementById('edit-png-label');
      const msg = document.getElementById('edit-loading-msg');
      if (!_pngFiles.length) {
        msg.textContent = '(no PNG available)';
        img.style.display = 'none';
        nav.style.display = 'none';
        return;
      }
      msg.style.display = 'none';
      img.src = _pngFiles[_pngIdx];
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

    // PNG zoom
    let _pngZoom = 1;
    const ZOOM_STEP = 0.25, ZOOM_MAX = 3, ZOOM_MIN = 1;
    function updatePngZoom() {
      const img = document.getElementById('edit-png');
      img.style.transform = `scale(${_pngZoom})`;
      img.style.transformOrigin = 'top left';
      img.style.cursor = _pngZoom > 1 ? 'zoom-out' : 'zoom-in';
    }
    document.getElementById('edit-png').addEventListener('click', () => {
      _pngZoom = _pngZoom < ZOOM_MAX ? _pngZoom + ZOOM_STEP : 1;
      updatePngZoom();
    });
    document.getElementById('edit-png').addEventListener('contextmenu', e => {
      e.preventDefault();
      if (_pngZoom > ZOOM_MIN) { _pngZoom -= ZOOM_STEP; updatePngZoom(); }
    });

    // PNG dark mode
    let _pngDark = false;
    function applyPngDark() {
      const leftPanel = document.getElementById('edit-left');
      const btn = document.getElementById('png-dark-toggle');
      if (_pngDark) { leftPanel.classList.add('png-dark'); btn.textContent = '☀ Light'; }
      else { leftPanel.classList.remove('png-dark'); btn.textContent = '🌙 Dark'; }
    }
    function togglePngDark() { _pngDark = !_pngDark; applyPngDark(); }

    // Close on backdrop click
    document.getElementById('edit-overlay').addEventListener('click', e => {
      if (e.target === document.getElementById('edit-overlay')) closeEditOverlay();
    });

    ['search', 'filter-exchange', 'filter-finalized', 'filter-manual-reviewed', 'filter-bucket', 'sort-by'].forEach(id => {
      const el = document.getElementById(id);
      if (el) {
        el.addEventListener('input', render);
        el.addEventListener('change', render);
      }
    });
    
    // [BLANK-TXT 2026-03-09] Add event listeners for blank TXT checkboxes
    ['hide-blank-lockin', 'hide-blank-shp'].forEach(id => {
      const el = document.getElementById(id);
      if (el) {
        el.addEventListener('change', render);
      }
    });

    loadData();
  </script>
</body>

</html>
