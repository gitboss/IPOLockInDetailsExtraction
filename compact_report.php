<?php
// Compact tabular report with sortable columns + AJAX row expansion

$env_path = __DIR__ . '/.env';
if (!file_exists($env_path)) {
  $env_path = __DIR__ . '/.env.example';
}
$env = [];
if (file_exists($env_path)) {
  foreach (file($env_path, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES) as $line) {
    $line = trim($line);
    if ($line === '' || $line[0] === '#' || strpos($line, '=') === false) {
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

function fmt_num($n): string
{
  if ($n === null || $n === '') {
    return '-';
  }
  return number_format((float) $n, 0, '.', ',');
}

function esc($v): string
{
  return htmlspecialchars((string) $v, ENT_QUOTES, 'UTF-8');
}

if (($_GET['action'] ?? '') === 'rows') {
  header('Content-Type: application/json');
  try {
    $id = (int) ($_GET['id'] ?? 0);
    if ($id <= 0) {
      throw new RuntimeException("Invalid id");
    }
    $pdo = make_pdo($env);
    $stmt = $pdo->prepare("
      SELECT
        row_order,
        shares,
        distinctive_from,
        distinctive_to,
        security_type,
        lockin_date_from,
        lockin_date_to,
        status,
        bucket,
        share_form
      FROM ipo_lockin_rows
      WHERE processing_log_id = :id
      ORDER BY row_order ASC, id ASC
    ");
    $stmt->execute([':id' => $id]);
    $rows = $stmt->fetchAll();
    echo json_encode(['ok' => true, 'rows' => $rows]);
  } catch (Exception $e) {
    http_response_code(400);
    echo json_encode(['ok' => false, 'error' => $e->getMessage()]);
  }
  exit;
}

$records = [];
$err = null;
try {
  $pdo = make_pdo($env);
  $records = $pdo->query("
    SELECT
      p.id, p.unique_symbol, p.exchange, p.file_name, p.status,
      p.computed_total, p.locked_total, p.free_total,
      p.shp_total_shares, p.shp_locked_shares, p.shp_promoter_shares, p.shp_public_shares, p.shp_others_shares,
      p.allotment_date, p.declared_total, p.processed_at, p.finalized_at,
      p.failed_rules, p.error_message,
      m.company_name, m.ipo_name, m.listing_date_actual, m.nse_symbol, m.bse_script_code
    FROM ipo_processing_log p
    LEFT JOIN sme_ipo_master m
      ON (p.exchange COLLATE utf8mb4_unicode_ci = 'BSE' COLLATE utf8mb4_unicode_ci
          AND CAST(m.bse_script_code AS CHAR) COLLATE utf8mb4_unicode_ci = SUBSTRING_INDEX(p.unique_symbol, ':', -1) COLLATE utf8mb4_unicode_ci)
      OR (p.exchange COLLATE utf8mb4_unicode_ci = 'NSE' COLLATE utf8mb4_unicode_ci
          AND UPPER(CAST(m.nse_symbol AS CHAR)) COLLATE utf8mb4_unicode_ci = UPPER(SUBSTRING_INDEX(p.unique_symbol, ':', -1)) COLLATE utf8mb4_unicode_ci)
    ORDER BY p.processed_at DESC
  ")->fetchAll();

  foreach ($records as &$r) {
    if (preg_match('/^([0-9]+)-([A-Z\\-]+)-Annexure-I\\.pdf$/', (string) $r['file_name'], $m)) {
      $r['exchange_code'] = $m[1];
      $r['symbol'] = $m[2];
    } else {
      $parts = explode(':', (string) $r['unique_symbol']);
      $r['exchange_code'] = count($parts) > 1 ? $parts[1] : '';
      $r['symbol'] = $r['nse_symbol'] ?? $r['exchange_code'];
    }
    $r['company_name'] = $r['company_name'] ?? $r['ipo_name'] ?? '';
    $r['is_finalized'] = !empty($r['finalized_at']);
  }
  unset($r);
} catch (Exception $e) {
  $err = $e->getMessage();
}
?>
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Compact IPO Report</title>
  <style>
    :root {
      --bg: #000;
      --bg2: #070707;
      --text: #d8d8d8;
      --muted: #8e8e8e;
      --head: #111;
      --line: #232323;
      --lockin: #2f1d00;
      --shp: #001f2b;
      --finalized-row: #062c12;
      --pending-row: #2b0808;
      --accent: #66d9ef;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: Consolas, Menlo, Monaco, monospace;
      font-size: 12px;
    }
    .wrap { padding: 10px; }
    .title {
      padding: 8px 10px;
      border: 1px solid var(--line);
      background: var(--bg2);
      margin-bottom: 8px;
      font-weight: 700;
      color: #fff;
    }
    .meta { color: var(--muted); font-weight: 400; }
    .grid-wrap {
      border: 1px solid var(--line);
      overflow: auto;
      max-height: calc(100vh - 80px);
      background: #030303;
    }
    table {
      border-collapse: collapse;
      width: max-content;
      min-width: 100%;
    }
    th, td {
      border: 1px solid var(--line);
      padding: 4px 6px;
      white-space: nowrap;
      text-align: right;
      vertical-align: middle;
    }
    th {
      background: var(--head);
      color: #fff;
      position: sticky;
      top: 0;
      z-index: 2;
      cursor: pointer;
      user-select: none;
    }
    .group th {
      top: 0;
      z-index: 3;
      text-align: center;
      font-weight: 700;
    }
    .group .g-lockin { background: var(--lockin); }
    .group .g-shp { background: var(--shp); }
    .group .g-core { background: #161616; }
    .h2 th { top: 28px; z-index: 2; }
    .left, .left th, td.left { text-align: left; }
    .num { text-align: right; }
    .finalized { background: var(--finalized-row); }
    .not-finalized { background: var(--pending-row); }
    .status-pill {
      font-size: 10px;
      font-weight: 700;
      padding: 1px 6px;
      border: 1px solid #444;
      border-radius: 3px;
      display: inline-block;
    }
    .exp-btn {
      background: #121212;
      color: #eee;
      border: 1px solid #3a3a3a;
      border-radius: 2px;
      width: 22px;
      height: 20px;
      line-height: 18px;
      cursor: pointer;
      font-weight: 700;
      padding: 0;
    }
    .exp-btn:hover { border-color: var(--accent); color: var(--accent); }
    .partition-r { border-right: 2px solid #4a4a4a !important; }
    .partition-l { border-left: 2px solid #4a4a4a !important; }
    .sort-ind { color: var(--accent); margin-left: 4px; font-size: 10px; }
    .detail-row td {
      background: #020202;
      padding: 8px;
      text-align: left;
    }
    .inner {
      border: 1px solid #2c2c2c;
      overflow: auto;
      max-height: 300px;
    }
    .inner table { width: 100%; min-width: 900px; }
    .inner th, .inner td { position: static; font-size: 11px; }
    .err {
      margin: 12px;
      border: 1px solid #511;
      background: #1a0505;
      color: #ff8080;
      padding: 10px;
    }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="title">
      Compact SME IPO Report
      <span class="meta"> | rows: <?php echo count($records); ?> | dark compact | click any column to sort | ▼ for AJAX lock-in rows</span>
    </div>

    <?php if ($err): ?>
      <div class="err"><?php echo esc($err); ?></div>
    <?php endif; ?>

    <div class="grid-wrap">
      <table id="reportTable">
        <thead>
          <tr class="group">
            <th colspan="6" class="g-lockin partition-r">Lock-in</th>
            <th colspan="5" class="g-shp partition-r">SHP</th>
            <th colspan="9" class="g-core">Core</th>
          </tr>
          <tr class="h2">
            <th data-type="num" class="num">#</th>
            <th data-type="str" class="left">Rows</th>
            <th data-type="num">Declared</th>
            <th data-type="num">Computed</th>
            <th data-type="num">Locked</th>
            <th data-type="num" class="partition-r">Free</th>

            <th data-type="num">SHP Total</th>
            <th data-type="num">SHP Locked</th>
            <th data-type="num">Promoter</th>
            <th data-type="num">Public</th>
            <th data-type="num" class="partition-r">Others</th>

            <th data-type="str" class="left">Symbol</th>
            <th data-type="num" class="num">Code</th>
            <th data-type="str" class="left">Company</th>
            <th data-type="str">Exch</th>
            <th data-type="str">Finalized</th>
            <th data-type="date">Allotment</th>
            <th data-type="date">Listing</th>
            <th data-type="date">Processed</th>
            <th data-type="str">Status</th>
          </tr>
        </thead>
        <tbody>
          <?php $row_no = 0; foreach ($records as $r): $row_no++; ?>
            <tr class="<?php echo $r['is_finalized'] ? 'finalized' : 'not-finalized'; ?>" data-id="<?php echo (int) $r['id']; ?>">
              <td class="num row-no"><?php echo $row_no; ?></td>
              <td class="left">
                <button class="exp-btn" data-open="0" onclick="toggleRows(this, <?php echo (int) $r['id']; ?>)">▼</button>
              </td>
              <td><?php echo esc(fmt_num($r['declared_total'])); ?></td>
              <td><?php echo esc(fmt_num($r['computed_total'])); ?></td>
              <td><?php echo esc(fmt_num($r['locked_total'])); ?></td>
              <td class="partition-r"><?php echo esc(fmt_num($r['free_total'])); ?></td>

              <td><?php echo esc(fmt_num($r['shp_total_shares'])); ?></td>
              <td><?php echo esc(fmt_num($r['shp_locked_shares'])); ?></td>
              <td><?php echo esc(fmt_num($r['shp_promoter_shares'])); ?></td>
              <td><?php echo esc(fmt_num($r['shp_public_shares'])); ?></td>
              <td class="partition-r"><?php echo esc(fmt_num($r['shp_others_shares'])); ?></td>

              <td class="left"><?php echo esc($r['symbol']); ?></td>
              <td class="num"><?php echo esc($r['exchange_code']); ?></td>
              <td class="left"><?php echo esc($r['company_name']); ?></td>
              <td><?php echo esc($r['exchange']); ?></td>
              <td>
                <span class="status-pill"><?php echo $r['is_finalized'] ? 'FINALIZED' : 'NOT FINALIZED'; ?></span>
              </td>
              <td data-sort="<?php echo esc((string) $r['allotment_date']); ?>"><?php echo esc((string) $r['allotment_date'] ?: '-'); ?></td>
              <td data-sort="<?php echo esc((string) $r['listing_date_actual']); ?>"><?php echo esc((string) $r['listing_date_actual'] ?: '-'); ?></td>
              <td data-sort="<?php echo esc((string) $r['processed_at']); ?>"><?php echo esc((string) $r['processed_at'] ?: '-'); ?></td>
              <td><?php echo esc($r['status'] ?: '-'); ?></td>
            </tr>
          <?php endforeach; ?>
        </tbody>
      </table>
    </div>
  </div>

  <script>
    const table = document.getElementById('reportTable');
    const tbody = table.tBodies[0];
    let sortState = { index: -1, asc: true };

    function parseValue(cell, type) {
      const raw = (cell.getAttribute('data-sort') || cell.textContent || '').trim();
      if (!raw || raw === '-') return type === 'str' ? '' : Number.NEGATIVE_INFINITY;
      if (type === 'num') {
        const n = Number(raw.replace(/,/g, '').replace(/[^\d.-]/g, ''));
        return Number.isFinite(n) ? n : Number.NEGATIVE_INFINITY;
      }
      if (type === 'date') {
        const t = Date.parse(raw);
        return Number.isFinite(t) ? t : Number.NEGATIVE_INFINITY;
      }
      return raw.toLowerCase();
    }

    function clearSortIndicators() {
      table.querySelectorAll('thead .sort-ind').forEach(x => x.remove());
    }

    function sortByColumn(index, type) {
      const rows = Array.from(tbody.querySelectorAll('tr')).filter(r => !r.classList.contains('detail-row'));
      const asc = sortState.index === index ? !sortState.asc : false;
      sortState = { index, asc };

      const detailMap = new Map();
      tbody.querySelectorAll('tr.detail-row').forEach(dr => {
        const parentId = dr.getAttribute('data-parent-id');
        if (parentId) detailMap.set(parentId, dr);
      });

      rows.sort((a, b) => {
        const av = parseValue(a.cells[index], type);
        const bv = parseValue(b.cells[index], type);
        if (av < bv) return asc ? -1 : 1;
        if (av > bv) return asc ? 1 : -1;
        return 0;
      });

      rows.forEach(r => {
        tbody.appendChild(r);
        const id = r.getAttribute('data-id');
        const dr = detailMap.get(id);
        if (dr) tbody.appendChild(dr);
      });
      renumberRows();

      clearSortIndicators();
      const target = table.tHead.rows[1].cells[index];
      const mark = document.createElement('span');
      mark.className = 'sort-ind';
      mark.textContent = asc ? '↑' : '↓';
      target.appendChild(mark);
    }

    Array.from(table.tHead.rows[1].cells).forEach((th, i) => {
      const type = th.getAttribute('data-type') || 'str';
      th.addEventListener('click', () => sortByColumn(i, type));
    });

    function renumberRows() {
      const rows = Array.from(tbody.querySelectorAll('tr')).filter(r => !r.classList.contains('detail-row'));
      rows.forEach((r, i) => {
        const cell = r.querySelector('td.row-no');
        if (cell) cell.textContent = String(i + 1);
      });
    }

    function buildInnerTable(rows) {
      const tr = rows.map(r => `
        <tr>
          <td>${r.row_order ?? '-'}</td>
          <td>${r.status ?? '-'}</td>
          <td style="text-align:right">${formatNum(r.shares)}</td>
          <td style="text-align:right">${formatNum(r.distinctive_from)}</td>
          <td style="text-align:right">${formatNum(r.distinctive_to)}</td>
          <td>${escHtml(r.lockin_date_from || '-')}</td>
          <td>${escHtml(r.lockin_date_to || '-')}</td>
          <td>${escHtml(r.bucket || '-')}</td>
          <td>${escHtml(r.security_type || '-')}</td>
          <td>${escHtml(r.share_form || '-')}</td>
        </tr>
      `).join('');

      return `
        <div class="inner">
          <table>
            <thead>
              <tr>
                <th>#</th><th>Status</th><th>Shares</th><th>From</th><th>To</th>
                <th>Lock From</th><th>Lock Upto</th><th>Bucket</th><th>Type</th><th>Form</th>
              </tr>
            </thead>
            <tbody>${tr || '<tr><td colspan="10">No rows</td></tr>'}</tbody>
          </table>
        </div>
      `;
    }

    function escHtml(s) {
      return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
    }

    function formatNum(v) {
      if (v === null || v === undefined || v === '') return '-';
      const n = Number(v);
      if (!Number.isFinite(n)) return '-';
      return new Intl.NumberFormat('en-IN').format(n);
    }

    async function toggleRows(btn, id) {
      const row = btn.closest('tr');
      const open = btn.getAttribute('data-open') === '1';
      const existing = tbody.querySelector(`tr.detail-row[data-parent-id="${id}"]`);

      if (open) {
        if (existing) existing.remove();
        btn.setAttribute('data-open', '0');
        btn.textContent = '▼';
        return;
      }

      btn.disabled = true;
      try {
        const res = await fetch(`compact_report.php?action=rows&id=${encodeURIComponent(id)}`, { cache: 'no-store' });
        const data = await res.json();
        if (!res.ok || !data.ok) {
          throw new Error((data && data.error) || `HTTP ${res.status}`);
        }
        if (existing) existing.remove();
        const dr = document.createElement('tr');
        dr.className = 'detail-row';
        dr.setAttribute('data-parent-id', String(id));
        const td = document.createElement('td');
        td.colSpan = row.cells.length;
        td.innerHTML = buildInnerTable(data.rows || []);
        dr.appendChild(td);
        row.insertAdjacentElement('afterend', dr);
        btn.setAttribute('data-open', '1');
        btn.textContent = '▲';
      } catch (e) {
        alert(`Failed to load rows: ${e.message}`);
      } finally {
        btn.disabled = false;
      }
    }
  </script>
</body>
</html>
