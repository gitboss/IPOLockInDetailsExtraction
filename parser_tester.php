<?php
// Lock-in Parser Tester - Debug Tool
// Test parser on individual files with interactive editing

// Scan for all _java.txt files in the project directory
$base_dir = __DIR__;
$all_files = [];
$files_by_exchange = ['BSE' => [], 'NSE' => []];

// Recursive scan for _java.txt files
$iterator = new RecursiveIteratorIterator(
    new RecursiveDirectoryIterator($base_dir, RecursiveDirectoryIterator::SKIP_DOTS)
);

foreach ($iterator as $file) {
    if ($file->isFile() && strpos($file->getFilename(), '_java.txt') !== false) {
        $path = $file->getPathname();
        $relative_path = str_replace($base_dir . '/', '', $path);
        
        // Determine exchange from path
        $exchange = 'NSE'; // Default
        if (strpos($path, 'bse') !== false || strpos($path, 'BSE') !== false) {
            $exchange = 'BSE';
        }
        
        $file_info = [
            'path' => $path,
            'relative' => $relative_path,
            'name' => $file->getFilename(),
            'exchange' => $exchange
        ];
        
        $all_files[] = $file_info;
        $files_by_exchange[$exchange][] = $file_info;
    }
}

// Sort files by name
usort($all_files, fn($a, $b) => strcmp($a['name'], $b['name']));
foreach ($files_by_exchange as $ex => &$files) {
    usort($files, fn($a, $b) => strcmp($a['name'], $b['name']));
}

// Handle AJAX request
if (isset($_GET['action'])) {
    header('Content-Type: application/json');
    
    if ($_GET['action'] === 'load_file' && isset($_GET['path'])) {
        $path = realpath($_GET['path']);
        if ($path && file_exists($path)) {
            echo json_encode([
                'success' => true,
                'content' => file_get_contents($path),
                'path' => $path
            ]);
        } else {
            echo json_encode(['success' => false, 'error' => 'File not found']);
        }
        exit;
    }
    
    if ($_GET['action'] === 'parse' && isset($_POST['content'])) {
        $content = $_POST['content'];
        $allotment_date = $_POST['allotment_date'] ?? null;
        
        // Create temp file
        $temp_file = tempnam(sys_get_temp_dir(), 'lockin_test_') . '.txt';
        file_put_contents($temp_file, $content);
        
        // Call wrapper parser (not the original - keeps original untouched)
        $python_cmd = strtoupper(substr(PHP_OS, 0, 3)) === 'WIN' ? 'python' : 'python3';
        $cmd = $python_cmd . ' ' . escapeshellarg(__DIR__ . '/parser_lockin_test_wrapper.py') . 
               ' ' . escapeshellarg($temp_file);
        
        if ($allotment_date) {
            $cmd .= ' ' . escapeshellarg($allotment_date);
        }
        
        $output = [];
        $exit_code = 0;
        exec($cmd . ' 2>&1', $output, $exit_code);
        
        unlink($temp_file);
        
        echo json_encode([
            'success' => $exit_code === 0,
            'output' => implode("\n", $output),
            'exit_code' => $exit_code
        ]);
        exit;
    }
}
?>
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🧪 Lock-in Parser Tester</title>
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&family=Syne:wght@600;800&display=swap" rel="stylesheet">
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
            --mono: 'JetBrains Mono', monospace;
            --sans: 'Syne', sans-serif;
        }

        * { box-sizing: border-box; margin: 0; padding: 0; }

        body {
            background: var(--bg);
            color: var(--text);
            font-family: var(--mono);
            font-size: 12px;
            line-height: 1.5;
            padding: 20px;
        }

        .container {
            max-width: 1600px;
            margin: 0 auto;
        }

        h1 {
            font-family: var(--sans);
            font-size: 20px;
            font-weight: 800;
            margin-bottom: 20px;
            color: var(--accent);
        }

        .controls {
            display: flex;
            gap: 12px;
            margin-bottom: 16px;
            flex-wrap: wrap;
            align-items: center;
        }

        select, input, button {
            background: var(--card);
            border: 1px solid var(--border2);
            color: var(--text);
            font-family: var(--mono);
            font-size: 12px;
            padding: 8px 12px;
            border-radius: 6px;
            outline: none;
        }

        select:focus, input:focus {
            border-color: var(--blue);
        }

        button {
            background: var(--blue);
            border: none;
            cursor: pointer;
            font-weight: 700;
            transition: all 0.15s;
        }

        button:hover {
            filter: brightness(1.1);
        }

        button:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }

        .btn-parse {
            background: var(--green);
        }

        .btn-clear {
            background: var(--red);
        }

        textarea {
            width: 100%;
            height: 400px;
            background: var(--card);
            border: 1px solid var(--border2);
            color: var(--text);
            font-family: var(--mono);
            font-size: 11px;
            padding: 12px;
            border-radius: 6px;
            resize: vertical;
            outline: none;
            white-space: pre;
            overflow-x: auto;
        }

        textarea:focus {
            border-color: var(--blue);
        }

        .output-section {
            margin-top: 20px;
        }

        .output-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 12px;
        }

        .output-title {
            font-family: var(--sans);
            font-size: 16px;
            font-weight: 700;
        }

        .output-stats {
            display: flex;
            gap: 16px;
        }

        .stat {
            background: var(--card);
            border: 1px solid var(--border2);
            border-radius: 6px;
            padding: 8px 12px;
            text-align: center;
        }

        .stat-label {
            color: var(--muted);
            font-size: 10px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .stat-value {
            font-size: 18px;
            font-weight: 700;
            margin-top: 2px;
        }

        .stat-value.ok { color: var(--green); }
        .stat-value.fail { color: var(--red); }
        .stat-value.warn { color: var(--yellow); }

        .raw-output {
            background: var(--card);
            border: 1px solid var(--border2);
            border-radius: 6px;
            padding: 12px;
            margin-top: 12px;
            max-height: 300px;
            overflow: auto;
            font-size: 10px;
            white-space: pre-wrap;
            color: var(--muted);
        }

        .results-table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 12px;
            font-size: 11px;
        }

        .results-table th,
        .results-table td {
            padding: 8px 10px;
            text-align: left;
            border-bottom: 1px solid var(--border);
        }

        .results-table th {
            background: var(--card);
            color: var(--muted);
            font-size: 10px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            font-weight: 600;
        }

        .results-table tr:hover td {
            background: var(--surface);
        }

        .results-table td.num {
            text-align: right;
            font-variant-numeric: tabular-nums;
        }

        .badge {
            display: inline-block;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 10px;
            font-weight: 700;
            letter-spacing: 0.5px;
        }

        .badge-locked {
            background: #1a2e1a;
            color: var(--green);
        }

        .badge-free {
            background: #1e1e1e;
            color: var(--muted);
        }

        .badge-anchor {
            background: #2a1f3d;
            color: var(--purple);
        }

        .badge-year {
            background: #1a2e1a;
            color: var(--green);
        }

        .loading {
            display: none;
            align-items: center;
            gap: 8px;
            color: var(--muted);
        }

        .loading.active {
            display: flex;
        }

        .spinner {
            width: 16px;
            height: 16px;
            border: 2px solid var(--border2);
            border-top-color: var(--accent);
            border-radius: 50%;
            animation: spin 0.7s linear infinite;
        }

        @keyframes spin {
            to { transform: rotate(360deg); }
        }

        .error-box {
            background: #2a1515;
            border: 1px solid var(--red);
            border-radius: 6px;
            padding: 12px;
            margin-top: 12px;
            color: var(--red);
        }

        .success-box {
            background: #152a1a;
            border: 1px solid var(--green);
            border-radius: 6px;
            padding: 12px;
            margin-top: 12px;
            color: var(--green);
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🧪 Lock-in Parser Tester</h1>

        <div class="controls">
            <select id="exchange-filter" onchange="updateFileList()">
                <option value="">All Exchanges</option>
                <option value="BSE">BSE</option>
                <option value="NSE">NSE</option>
            </select>

            <select id="file-select" onchange="loadFile()" style="min-width: 400px;">
                <option value="">-- Select a file --</option>
                <?php foreach ($all_files as $f): ?>
                    <option value="<?= htmlspecialchars($f['path']) ?>"
                            data-exchange="<?= $f['exchange'] ?>">
                        <?= $f['exchange'] ?>: <?= htmlspecialchars($f['name']) ?>
                    </option>
                <?php endforeach; ?>
            </select>

            <input type="text" id="allotment-date" placeholder="Allotment Date (YYYY-MM-DD)" 
                   style="width: 180px;">

            <button class="btn-parse" onclick="parseContent()">▶ Parse</button>
            <button class="btn-clear" onclick="clearAll()">✕ Clear</button>

            <div class="loading" id="loading">
                <div class="spinner"></div>
                <span>Parsing...</span>
            </div>
        </div>

        <textarea id="content-area" placeholder="Select a file or paste lock-in text content here..."></textarea>

        <div class="output-section" id="output-section" style="display: none;">
            <div class="output-header">
                <div class="output-title">📊 Parser Results</div>
                <div class="output-stats" id="output-stats">
                    <!-- Stats will be inserted here -->
                </div>
            </div>

            <table class="results-table" id="results-table">
                <thead>
                    <tr>
                        <th>#</th>
                        <th>Status</th>
                        <th class="num">Shares</th>
                        <th>From</th>
                        <th>To</th>
                        <th>Lock Date</th>
                        <th>Bucket</th>
                        <th>Raw Text</th>
                    </tr>
                </thead>
                <tbody id="results-body">
                    <!-- Results will be inserted here -->
                </tbody>
            </table>

            <div class="raw-output" id="raw-output"></div>
        </div>
    </div>

    <script>
        let currentContent = '';

        function updateFileList() {
            const filter = document.getElementById('exchange-filter').value;
            const select = document.getElementById('file-select');
            
            Array.from(select.options).forEach(opt => {
                if (opt.value === '') return;
                const exchange = opt.getAttribute('data-exchange');
                opt.style.display = (!filter || exchange === filter) ? 'block' : 'none';
            });
        }

        async function loadFile() {
            const path = document.getElementById('file-select').value;
            if (!path) {
                document.getElementById('content-area').value = '';
                return;
            }

            try {
                const resp = await fetch('?action=load_file&path=' + encodeURIComponent(path));
                const data = await resp.json();
                
                if (data.success) {
                    document.getElementById('content-area').value = data.content;
                    currentContent = data.content;
                    hideOutput();
                } else {
                    alert('Error loading file: ' + data.error);
                }
            } catch (e) {
                alert('Error: ' + e.message);
            }
        }

        async function parseContent() {
            const content = document.getElementById('content-area').value;
            if (!content.trim()) {
                alert('Please enter or select content to parse');
                return;
            }

            const loading = document.getElementById('loading');
            loading.classList.add('active');

            const formData = new FormData();
            formData.append('content', content);
            const allotmentDate = document.getElementById('allotment-date').value;
            if (allotmentDate) {
                formData.append('allotment_date', allotmentDate);
            }

            try {
                const resp = await fetch('?action=parse', {
                    method: 'POST',
                    body: formData
                });
                const data = await resp.json();

                if (data.success) {
                    displayResults(data.output);
                } else {
                    showError(data.output);
                }
            } catch (e) {
                showError('Error: ' + e.message);
            } finally {
                loading.classList.remove('active');
            }
        }

        function displayResults(output) {
            const section = document.getElementById('output-section');
            const stats = document.getElementById('output-stats');
            const tbody = document.getElementById('results-body');
            const rawOutput = document.getElementById('raw-output');

            section.style.display = 'block';
            rawOutput.textContent = output;

            // Parse output to extract stats
            const lines = output.split('\n');
            const statsData = {};

            lines.forEach(line => {
                if (line.includes('Rows Found:')) {
                    statsData.rows = line.split(':')[1].trim();
                } else if (line.includes('Locked Rows:')) {
                    statsData.locked = line.split(':')[1].trim();
                } else if (line.includes('Free Rows:')) {
                    statsData.free = line.split(':')[1].trim();
                } else if (line.includes('Computed Total:')) {
                    statsData.computed = line.split(':')[1].trim();
                } else if (line.includes('Locked Total:')) {
                    statsData.lockedTotal = line.split(':')[1].trim();
                } else if (line.includes('Free Total:')) {
                    statsData.freeTotal = line.split(':')[1].trim();
                }
            });

            // Display stats
            stats.innerHTML = `
                <div class="stat">
                    <div class="stat-label">Total Rows</div>
                    <div class="stat-value">${statsData.rows || '-'}</div>
                </div>
                <div class="stat">
                    <div class="stat-label">Locked</div>
                    <div class="stat-value">${statsData.locked || '-'}</div>
                </div>
                <div class="stat">
                    <div class="stat-label">Free</div>
                    <div class="stat-value">${statsData.free || '-'}</div>
                </div>
                <div class="stat">
                    <div class="stat-label">Computed Total</div>
                    <div class="stat-value ok">${statsData.computed || '-'}</div>
                </div>
                <div class="stat">
                    <div class="stat-label">Locked Total</div>
                    <div class="stat-value">${statsData.lockedTotal || '-'}</div>
                </div>
                <div class="stat">
                    <div class="stat-label">Free Total</div>
                    <div class="stat-value">${statsData.freeTotal || '-'}</div>
                </div>
            `;

            // Parse ALL rows from output (not just "First 5 rows")
            tbody.innerHTML = '';
            // Match both "First 5 rows" format and full row list format
            const rowRegex = /^\s*(\d+)\.\s+(LOCKED|FREE)\s+([\d,]+)\s+shares\s*\|\s*(.+)$/;
            let inFirst5Section = false;
            let rowCount = 0;
            
            for (let i = 0; i < lines.length; i++) {
                const line = lines[i];
                
                // Check if we're entering the "First 5 rows" section
                if (line.includes('First 5 rows:')) {
                    inFirst5Section = true;
                    continue;
                }
                
                // Check if we're entering "First X rows" section (skip header, parse content)
                if (inFirst5Section) {
                    const match = line.match(rowRegex);
                    if (match) {
                        const [, num, status, shares, rest] = match;
                        const parts = rest.split('|').map(s => s.trim());
                        const bucket = parts[0] || '-';
                        const datesStr = parts[1] || '-';
                        
                        // Parse dates from "YYYY-MM-DD -> YYYY-MM-DD" format
                        let fromDate = '-';
                        let toDate = '-';
                        if (datesStr.includes('->')) {
                            const dateParts = datesStr.split('->').map(s => s.trim());
                            fromDate = dateParts[0] || '-';
                            toDate = dateParts[1] || '-';
                        } else if (datesStr !== '-') {
                            toDate = datesStr;
                        }

                        rowCount++;
                        const tr = document.createElement('tr');
                        tr.innerHTML = `
                            <td>${rowCount}</td>
                            <td><span class="badge badge-${status.toLowerCase()}">${status}</span></td>
                            <td class="num">${parseInt(shares.replace(/,/g, '')).toLocaleString('en-IN')}</td>
                            <td>${fromDate}</td>
                            <td>${toDate}</td>
                            <td>${bucket !== '-' && bucket !== 'unknown' && bucket !== 'free' ? `<span class="badge badge-anchor">${bucket}</span>` : '-'}</td>
                            <td style="color: var(--muted); max-width: 300px; overflow: hidden; text-overflow: ellipsis;">${line}</td>
                        `;
                        tbody.appendChild(tr);
                    }
                }
            }

            // If no rows found in "First 5" section, try parsing entire output
            if (rowCount === 0) {
                lines.forEach(line => {
                    const match = line.match(rowRegex);
                    if (match) {
                        const [, num, status, shares, rest] = match;
                        const parts = rest.split('|').map(s => s.trim());
                        const bucket = parts[0] || '-';
                        const datesStr = parts[1] || '-';
                        
                        // Parse dates from "YYYY-MM-DD -> YYYY-MM-DD" format
                        let fromDate = '-';
                        let toDate = '-';
                        if (datesStr.includes('->')) {
                            const dateParts = datesStr.split('->').map(s => s.trim());
                            fromDate = dateParts[0] || '-';
                            toDate = dateParts[1] || '-';
                        } else if (datesStr !== '-') {
                            toDate = datesStr;
                        }

                        rowCount++;
                        const tr = document.createElement('tr');
                        tr.innerHTML = `
                            <td>${rowCount}</td>
                            <td><span class="badge badge-${status.toLowerCase()}">${status}</span></td>
                            <td class="num">${parseInt(shares.replace(/,/g, '')).toLocaleString('en-IN')}</td>
                            <td>${fromDate}</td>
                            <td>${toDate}</td>
                            <td>${bucket !== '-' && bucket !== 'unknown' && bucket !== 'free' ? `<span class="badge badge-anchor">${bucket}</span>` : '-'}</td>
                            <td style="color: var(--muted); max-width: 300px; overflow: hidden; text-overflow: ellipsis;">${line}</td>
                        `;
                        tbody.appendChild(tr);
                    }
                });
            }
        }

        function showError(output) {
            const section = document.getElementById('output-section');
            section.style.display = 'block';
            section.innerHTML = `
                <div class="error-box">
                    <strong>❌ Parse Error</strong><br><br>
                    <pre style="white-space: pre-wrap; margin: 0;">${output}</pre>
                </div>
            `;
        }

        function hideOutput() {
            document.getElementById('output-section').style.display = 'none';
        }

        function clearAll() {
            document.getElementById('file-select').value = '';
            document.getElementById('content-area').value = '';
            document.getElementById('allotment-date').value = '';
            hideOutput();
        }
    </script>
</body>
</html>
