<?php
// Self-contained unlock events API (same env/PDO style as finalized_report.php)

header('Content-Type: application/json');

$env_path = __DIR__ . '/.env';
if (!file_exists($env_path)) {
  $env_path = __DIR__ . '/.env.example';
}
$env = [];
if (file_exists($env_path)) {
  foreach (file($env_path, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES) as $line) {
    $line = trim($line);
    if ($line === '' || $line[0] === '#') {
      continue;
    }
    if (strpos($line, '=') === false) {
      continue;
    }
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

try {
  $pdo = make_pdo($env);

  $since = trim((string)($_GET['since'] ?? '1970-01-01 00:00:00'));
  if ($since === '') {
    $since = '1970-01-01 00:00:00';
  }

  $exchange = strtoupper(trim((string)($_GET['exchange'] ?? '')));
  if ($exchange !== '' && !in_array($exchange, ['NSE', 'BSE'], true)) {
    throw new InvalidArgumentException("Invalid exchange. Use NSE or BSE.");
  }

  $status = strtoupper(trim((string)($_GET['status'] ?? 'ANY')));
  if (!in_array($status, ['FINALIZED', 'ANY'], true)) {
    throw new InvalidArgumentException("Invalid status. Use FINALIZED or ANY.");
  }

  $where = [
    "r.status = 'LOCKED'",
    "r.lockin_date_to IS NOT NULL",
    "r.bucket IN ('anchor_30','anchor_90','1_year_minus','1_year_plus','2_year_plus','3_year_plus')",
    "COALESCE(p.updated_at, p.processed_at) > :since",
  ];
  $params = [':since' => $since];

  if ($exchange !== '') {
    $where[] = "p.exchange = :exchange";
    $params[':exchange'] = $exchange;
  }
  if ($status === 'FINALIZED') {
    $where[] = "p.status = 'FINALIZED'";
  }

  $sql = "
    SELECT
      p.id AS processing_id,
      p.unique_symbol,
      p.exchange,
      p.file_name,
      CASE WHEN p.status = 'FINALIZED' THEN 1 ELSE 0 END AS finalized,
      COALESCE(m.company_name, m.ipo_name) AS company_name,
      r.lockin_date_to AS unlock_date,
      r.bucket,
      SUM(r.shares) AS shares_unlocked,
      MIN(r.lockin_date_from) AS lock_from,
      MAX(COALESCE(p.updated_at, p.processed_at)) AS last_updated
    FROM ipo_processing_log p
    JOIN (
      SELECT unique_symbol, MAX(id) AS max_id
      FROM ipo_processing_log
      " . ($exchange !== '' ? "WHERE exchange = :exchange_latest" : "") . "
      GROUP BY unique_symbol
    ) latest ON latest.max_id = p.id
    JOIN ipo_lockin_rows r ON r.processing_log_id = p.id
    LEFT JOIN sme_ipo_master m
      ON (p.exchange COLLATE utf8mb4_unicode_ci = 'BSE' COLLATE utf8mb4_unicode_ci
          AND CAST(m.bse_script_code AS CHAR) COLLATE utf8mb4_unicode_ci = SUBSTRING_INDEX(p.unique_symbol, ':', -1) COLLATE utf8mb4_unicode_ci)
      OR (p.exchange COLLATE utf8mb4_unicode_ci = 'NSE' COLLATE utf8mb4_unicode_ci
          AND UPPER(CAST(m.nse_symbol AS CHAR)) COLLATE utf8mb4_unicode_ci = UPPER(SUBSTRING_INDEX(p.unique_symbol, ':', -1)) COLLATE utf8mb4_unicode_ci)
    WHERE " . implode(" AND ", $where) . "
    GROUP BY
      p.id, p.unique_symbol, p.exchange, p.file_name, finalized, company_name, r.lockin_date_to, r.bucket
    ORDER BY
      p.id ASC, r.lockin_date_to ASC, r.bucket ASC
  ";

  if ($exchange !== '') {
    $params[':exchange_latest'] = $exchange;
  }

  $stmt = $pdo->prepare($sql);
  $stmt->execute($params);
  $rows = $stmt->fetchAll();

  // Group by processing_id => one scrip object with nested unlock_events[]
  $scripMap = [];
  foreach ($rows as $r) {
    $pid = (string)($r['processing_id'] ?? '');
    if ($pid === '') {
      continue;
    }
    if (!isset($scripMap[$pid])) {
      $scripMap[$pid] = [
        'processing_id' => (int)$r['processing_id'],
        'unique_symbol' => $r['unique_symbol'],
        'exchange' => $r['exchange'],
        'file_name' => $r['file_name'],
        'finalized' => (int)$r['finalized'],
        'company_name' => $r['company_name'],
        'last_updated' => $r['last_updated'],
        'unlock_events' => [],
      ];
    }
    $scripMap[$pid]['unlock_events'][] = [
      'unlock_date' => $r['unlock_date'],
      'bucket' => $r['bucket'],
      'shares_unlocked' => (int)$r['shares_unlocked'],
      'lock_from' => $r['lock_from'],
    ];
  }
  $scrips = array_values($scripMap);

  echo json_encode([
    'ok' => true,
    'server_time' => date('Y-m-d H:i:s'),
    'since' => $since,
    'scrip_count' => count($scrips),
    'event_count' => count($rows),
    'scrips' => $scrips,
  ], JSON_UNESCAPED_UNICODE);
} catch (Exception $e) {
  http_response_code(400);
  echo json_encode([
    'ok' => false,
    'error' => $e->getMessage(),
  ], JSON_UNESCAPED_UNICODE);
}
