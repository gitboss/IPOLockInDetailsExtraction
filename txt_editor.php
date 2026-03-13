<?php
// Simple TXT editor for non-finalized files only.

$baseDir = realpath(__DIR__);
$error = null;
$success = null;

function h($s)
{
    return htmlspecialchars((string)$s, ENT_QUOTES, 'UTF-8');
}

function last_php_error_message()
{
    $e = error_get_last();
    return $e && !empty($e['message']) ? $e['message'] : 'Unknown PHP write error.';
}

function normalize_input_path($path)
{
    $path = str_replace('\\', '/', trim((string)$path));
    if ($path === '') {
        return '';
    }
    $isAbsoluteUnix = (strpos($path, '/') === 0);
    $isAbsoluteWindows = (bool)preg_match('/^[A-Za-z]:\//', $path);
    // Convert web-style path to filesystem path under project root.
    if (strpos($path, '/nile/sme/notices/') === 0) {
        $path = substr($path, strlen('/nile/sme/notices/'));
    }
    // Preserve true absolute filesystem paths (/home/... or C:/...).
    if (!$isAbsoluteUnix && !$isAbsoluteWindows) {
        $path = ltrim($path, '/');
    }
    return $path;
}

function resolve_real_path($baseDir, $inputPath)
{
    if ($inputPath === '') {
        return false;
    }
    if (preg_match('/^[A-Za-z]:[\/\\\\]/', $inputPath) || strpos($inputPath, '/') === 0) {
        return realpath($inputPath);
    }
    return realpath($baseDir . DIRECTORY_SEPARATOR . str_replace('/', DIRECTORY_SEPARATOR, $inputPath));
}

$requested = $_REQUEST['file'] ?? '';
$inputPath = normalize_input_path($requested);
$realPath = resolve_real_path($baseDir, $inputPath);

$symbol = $_REQUEST['symbol'] ?? '';
$code = $_REQUEST['code'] ?? '';
$company = $_REQUEST['company'] ?? '';
$type = $_REQUEST['type'] ?? 'TXT';

$titleParts = [];
if (trim((string)$symbol) !== '') $titleParts[] = trim((string)$symbol);
if (trim((string)$code) !== '') $titleParts[] = trim((string)$code);
if (trim((string)$company) !== '') $titleParts[] = trim((string)$company);
$pageTitle = count($titleParts) ? implode(' - ', $titleParts) : 'TXT Editor';

if (!$realPath || !is_file($realPath)) {
    $error = "File not found.";
}

$isInsideProject = $realPath && (strpos($realPath, $baseDir) === 0);
$isTxt = $realPath && (strtolower(pathinfo($realPath, PATHINFO_EXTENSION)) === 'txt');
$isFinalizedFile = $realPath && (strpos(str_replace('\\', '/', strtolower($realPath)), '/finalized/') !== false);

if (!$error && (!$isInsideProject || !$isTxt)) {
    $error = "Invalid file path.";
}

$canEdit = !$error && !$isFinalizedFile;

if ($_SERVER['REQUEST_METHOD'] === 'POST' && !$error) {
    $action = $_POST['action'] ?? '';
    $content = $_POST['content'] ?? '';

    if (!$canEdit) {
        $error = "Finalized TXT files cannot be edited.";
    } else {
        if (!is_writable($realPath)) {
            $error = "File is not writable by web server user: " . basename($realPath);
        }
    }

    if (!$error) {
        if ($action === 'save') {
            if (@file_put_contents($realPath, $content) === false) {
                $error = "Failed to save file: " . last_php_error_message();
            } else {
                $success = "Saved successfully.";
            }
        } elseif ($action === 'save_as') {
            $newName = trim((string)($_POST['save_as_name'] ?? ''));
            if ($newName === '') {
                $error = "Save As filename required.";
            } else {
                $newName = preg_replace('/[^\w\-. ]+/', '_', $newName);
                if (!preg_match('/\.txt$/i', $newName)) {
                    $newName .= '.txt';
                }
                $targetPath = dirname($realPath) . DIRECTORY_SEPARATOR . $newName;
                if (@file_put_contents($targetPath, $content) === false) {
                    $error = "Failed to save as new file: " . last_php_error_message();
                } else {
                    $success = "Saved as " . $newName;
                }
            }
        }
    }
}

$fileContent = '';
if (!$error) {
    $fileContent = @file_get_contents($realPath);
    if ($fileContent === false) {
        $error = "Failed to read file.";
    }
}
?>
<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title><?= h($pageTitle) ?></title>
  <style>
    body { margin: 0; font-family: Consolas, monospace; background:#101418; color:#e5e7eb; }
    .top { position: sticky; top: 0; z-index: 10; background:#161b22; border-bottom:1px solid #2d333b; padding:10px 14px; }
    .meta { display:flex; gap:18px; flex-wrap:wrap; font-size:12px; margin-bottom:8px; color:#9ca3af; }
    .meta b { color:#f3f4f6; }
    .buttons { display:flex; gap:8px; flex-wrap:wrap; }
    button { background:#0ea5e9; border:0; color:#fff; padding:7px 12px; border-radius:5px; cursor:pointer; font-size:12px; }
    button.secondary { background:#334155; }
    button.warn { background:#b91c1c; }
    button:disabled { opacity:0.5; cursor:not-allowed; }
    .msg { padding:8px 14px; font-size:12px; }
    .ok { background:#052e16; color:#86efac; }
    .err { background:#450a0a; color:#fca5a5; }
    textarea { width:100%; height:calc(100vh - 125px); border:0; outline:none; resize:none; padding:14px; box-sizing:border-box; background:#0b0f14; color:#e5e7eb; font-size:13px; line-height:1.45; overflow:auto; white-space:pre; }
  </style>
</head>
<body>
  <div class="top">
    <div class="meta">
      <div>SYMBOL: <b><?= h($symbol ?: '-') ?></b></div>
      <div>CODE: <b><?= h($code ?: '-') ?></b></div>
      <div>COMPANY: <b><?= h($company ?: '-') ?></b></div>
      <div>TYPE: <b><?= h($type) ?></b></div>
      <div>FILE: <b><?= h($realPath ? basename($realPath) : '-') ?></b></div>
    </div>
    <div class="buttons">
      <button id="btn-save" <?= $canEdit ? '' : 'disabled' ?>>Save</button>
      <button id="btn-undo" class="secondary">Undo</button>
      <button id="btn-redo" class="secondary">Redo</button>
      <button id="btn-saveas" class="secondary" <?= $canEdit ? '' : 'disabled' ?>>Save As</button>
      <button id="btn-reload" class="warn">Reload</button>
    </div>
  </div>

  <?php if ($success): ?><div class="msg ok"><?= h($success) ?></div><?php endif; ?>
  <?php if ($error): ?><div class="msg err"><?= h($error) ?></div><?php endif; ?>

  <textarea id="editor" spellcheck="false" <?= $error ? 'disabled' : '' ?>><?= h($fileContent) ?></textarea>

  <form id="save-form" method="post" style="display:none">
    <input type="hidden" name="file" value="<?= h($requested) ?>">
    <input type="hidden" name="symbol" value="<?= h($symbol) ?>">
    <input type="hidden" name="code" value="<?= h($code) ?>">
    <input type="hidden" name="company" value="<?= h($company) ?>">
    <input type="hidden" name="type" value="<?= h($type) ?>">
    <input type="hidden" name="action" id="action-field" value="save">
    <input type="hidden" name="save_as_name" id="saveas-field" value="">
    <input type="hidden" name="content" id="content-field" value="">
  </form>

  <script>
    const editor = document.getElementById('editor');
    const canEdit = <?= $canEdit ? 'true' : 'false' ?>;
    const undoStack = [];
    const redoStack = [];
    let lastVal = editor.value;

    function pushUndo(prevVal) {
      undoStack.push(prevVal);
      if (undoStack.length > 200) undoStack.shift();
      redoStack.length = 0;
    }

    editor.addEventListener('input', () => {
      if (editor.value !== lastVal) {
        pushUndo(lastVal);
        lastVal = editor.value;
      }
    });

    document.getElementById('btn-undo').addEventListener('click', () => {
      if (!undoStack.length) return;
      const curr = editor.value;
      const prev = undoStack.pop();
      redoStack.push(curr);
      editor.value = prev;
      lastVal = prev;
    });

    document.getElementById('btn-redo').addEventListener('click', () => {
      if (!redoStack.length) return;
      const curr = editor.value;
      const next = redoStack.pop();
      undoStack.push(curr);
      editor.value = next;
      lastVal = next;
    });

    function submitAction(action, saveAsName = '') {
      document.getElementById('action-field').value = action;
      document.getElementById('saveas-field').value = saveAsName;
      document.getElementById('content-field').value = editor.value;
      document.getElementById('save-form').submit();
    }

    document.getElementById('btn-save').addEventListener('click', () => {
      if (!canEdit) return;
      submitAction('save');
    });

    document.getElementById('btn-saveas').addEventListener('click', () => {
      if (!canEdit) return;
      const name = prompt('Save as filename (.txt):', '');
      if (!name) return;
      submitAction('save_as', name);
    });

    document.getElementById('btn-reload').addEventListener('click', () => {
      location.reload();
    });
  </script>
</body>
</html>
