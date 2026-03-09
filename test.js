
    let allScrips = [];

    function fmt(n) {
      if (n == null || n === '') return '-';
      return Number(n).toLocaleString('en-IN');
    }

    function fmtBucket(bucket) {
      if (!bucket) return '-';
      const map = {
        'anchor_30days': 'Anchor 30d',
        'anchor_90days': 'Anchor 90d',
        '1+year': '1 Year',
        '2+years': '2 Years',
        '3+years': '3 Years+',
        'free': 'Free',
        'unknown': 'Unknown'
      };
      return map[bucket.toLowerCase()] || bucket;
    }

    function getEffectiveStatus(s) {
      return s.status || '';
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
      const totalShares = Number(s.total_shares || s.computed_total) || 0;
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

      const errorMessageStr = s.error_message
        ? `<div style="grid-column:1/-1;background:#fff3cd;border:1px solid #ffc107;border-radius:4px;padding:6px 10px;margin-top:4px;font-size:11px;color:#856404">
             <strong>⚠ Finalization Issue:</strong> ${s.error_message}
           </div>`
        : '';

      const validStr = (() => {
        const st = effectiveStatus.toUpperCase();
        if (st === 'PASS' || st === 'SHP_PASS') return `<span class="match-ok">OK MATCH</span>`;
        if (st === 'FAIL' || st === 'SHP_FAIL' || st === 'FAILED') return `<span class="match-fail">FAIL</span>`;
        if (st === 'MANUAL_LOCKED') return `<span class="match-ok">MANUAL LOCK</span>`;
        if (st === 'AUTO_LOCKED') return `<span class="match-ok">AUTO LOCK</span>`;
        return `<span class="match-none">${st}</span>`;
      })();

      // Build file paths - finalized files are moved to 'finalized/' subfolder in same directory
      const pdfFile = (s.pdf_file || s.lockin_pdf_path || '').replace(/\\/g, '/');
      const pdfName = pdfFile ? pdfFile.split('/').pop() : '';
      const stem = pdfName ? pdfName.replace(/\.pdf$/i, '') : '';
      const shpName = s.exchange === 'BSE' ? pdfName.replace('I.', 'II.') : 'SHP-' + (s.symbol || '') + '.pdf';

      // Build base paths by extracting directory from stored paths
      const pdfBase = pdfFile ? pdfFile.substring(0, pdfFile.lastIndexOf('/') + 1) : '';
      const shpBase = s.shp_pdf_path ? s.shp_pdf_path.replace(/\\/g, '/').substring(0, s.shp_pdf_path.replace(/\\/g, '/').lastIndexOf('/') + 1) : pdfBase.replace('pdf/lockin', 'pdf/shp');
      const pngBase = Array.isArray(s.png_files) && s.png_files.length
        ? s.png_files[0].replace(/\\/g, '/').substring(0, s.png_files[0].replace(/\\/g, '/').lastIndexOf('/') + 1)
        : pdfBase.replace('pdf/lockin', 'pdf/lockin/png');

      // TXT file paths from database
      const lockinTxtFile = (s.lockin_txt_java || '').replace(/\\/g, '/');
      const shpTxtFile = (s.shp_txt_java || '').replace(/\\/g, '/');
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

      const linksHtml = pdfName ? `
    <div class="card-links">
      <a class="link-btn" href="${pdfPathFinalized}${pdfName}" target="_blank">📄 PDF</a>
      <a class="link-btn" href="${shpPathFinalized}${shpName}" target="_blank">📊 SHP PDF</a>
      <a class="link-btn" href="${pngPathFinalized}${stem}.png" target="_blank">🖼 PNG</a>
      <span style="color:var(--muted);margin:0 4px">|</span>
      <a class="link-btn" href="${lockinTxtPathFinalized}${lockinTxtName}" target="_blank">📝 Lock-in TXT</a>
      <a class="link-btn" href="${shpTxtPathFinalized}${shpTxtName}" target="_blank">📝 SHP TXT</a>
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
        </div>
      </div>
      <span class="badge ex-${s.exchange || 'BSE'}">${s.exchange || ''}</span>
      <span class="badge st-${effectiveStatus.replace(/[^a-zA-Z0-9]/g, '_').toUpperCase()}">${effectiveStatus}</span>
      <span style="font-size:11px">${validStr}</span>
      <span style="font-size:11px">${finalizedStr}</span>
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
        <div style="color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:0.5px;padding-bottom:2px">Processed</div>
        <div style="color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:0.5px;text-align:right;padding-bottom:2px">Promoter</div>
        <div style="color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:0.5px;text-align:right;padding-bottom:2px">Public</div>
        <div style="color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:0.5px;text-align:right;padding-bottom:2px">Total SHP</div>
        <div style="color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:0.5px;text-align:right;padding-bottom:2px;grid-column:span 2">SHP Locked</div>

        <div style="color:var(--muted);font-size:11px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${s.processed_at || '-'}</div>
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
      const bucket = document.getElementById('filter-bucket').value;
      const sortBy = document.getElementById('sort-by').value;

      let scrips = allScrips.filter(s => {
        if (q) {
          const sym = (s.symbol || s.unique_symbol || '').toLowerCase();
          const comp = (s.company_name || '').toLowerCase();
          if (!sym.includes(q) && !comp.includes(q)) return false;
        }
        if (exch && (s.exchange || '').toUpperCase() !== exch) return false;
        if (finalizedFilter !== '' && String(s.finalized ? 1 : 0) !== finalizedFilter) return false;
        if (bucket && !(s.rows || []).some(r => (r.lock_bucket || '').toLowerCase() === bucket)) return false;
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
          <td><span class="bucket-pill bk-${(r.lock_bucket || 'free').replace(/[^a-z0-9_]/g, '-')}">${fmtBucket(r.lock_bucket || '')}</span></td>
          <td style="color:var(--muted);max-width:150px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${(r.type_raw || '').replace(/"/g, '&quot;')}">${r.type_raw || '-'}</td>
        `;
        tbody.appendChild(tr);
      });
      if (!s.rows || !s.rows.length) {
        tbody.innerHTML = '<tr><td colspan="6" style="color:var(--muted);text-align:center">No rows</td></tr>';
      }

      // PNG
      _pngFiles = Array.isArray(s.png_files) ? s.png_files.map(p => p.replace(/\\/g, '/')) : [];
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

    ['search', 'filter-exchange', 'filter-finalized', 'filter-bucket', 'sort-by'].forEach(id =>
      document.getElementById(id).addEventListener('input', render)
    );

    loadData();
  