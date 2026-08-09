# -*- coding: utf-8 -*-
"""Patch data_extraction.html to add Batch Queue Upload tab + panel + JS"""
import os

html_path = r'd:\HuaweiMoveData\Users\初\Desktop\我的黑客松\MedSnap\templates\data_extraction.html'
log_path = r'd:\HuaweiMoveData\Users\初\Desktop\我的黑客松\MedSnap\patch_batch_log.txt'

with open(html_path, 'r', encoding='utf-8') as f:
    content = f.read()

log = []
changes = 0

# ============================
# PATCH 1: Add 4th tab after text tab
# ============================
text_tab_marker = """switchSource('quantitative', 'text')">&#128221; 文本输入</div>"""
batch_tab_html = """switchSource('quantitative', 'text')">&#128221; 文本输入</div>
                <div class="source-tab" onclick="switchSource('quantitative', 'batch')">&#128293; 批量队列上传</div>"""

if "switchSource('quantitative', 'batch')" not in content:
    if text_tab_marker in content:
        content = content.replace(text_tab_marker, batch_tab_html, 1)
        changes += 1
        log.append('PATCH 1 OK: Added batch tab')
    else:
        log.append('PATCH 1 ERROR: Cannot find text tab marker')
else:
    log.append('PATCH 1 SKIP: Batch tab already exists')


# ============================
# PATCH 2: Add batch panel before inline-progress
# ============================
progress_marker = '            <!-- Inline Progress for Structured Extraction -->'

batch_panel = '''            <div class="source-panel" id="quant-batch">
                <input type="file" id="quantBatchInput" class="file-input" multiple accept=".jpg,.jpeg,.png,.bmp,.tiff,.pdf,.wav,.mp3,.m4a,.aac,.flac,.amr,.opus,.txt,.docx,.doc,.csv">
                <div class="dropzone" id="quantBatchZone" onclick="document.getElementById('quantBatchInput').click()">
                    <div class="drop-icon">&#128230;</div>
                    <h4>批量上传文件（最多 100 个）</h4>
                    <p>支持图片 / PDF / 音频格式，文件将进入队列异步处理</p>
                </div>
                <div class="file-list" id="quantBatchList"></div>
                <button class="btn btn-primary" style="width:100%;padding:14px;border-radius:12px;font-size:15px;" onclick="processBatch()" id="quantBatchBtn" disabled>&#128203; 提交到处理队列</button>
                <div style="margin-top:20px;padding:14px 18px;background:#f0f9ff;border:1px solid #bae6fd;border-radius:12px;display:flex;align-items:center;justify-content:space-between;">
                    <span style="font-size:14px;font-weight:600;color:#0369a1;">&#128203; 批次进度查询</span>
                    <button class="btn-outline" onclick="refreshBatchProgress()" style="padding:6px 16px;border-radius:8px;font-size:13px;">刷新列表</button>
                </div>
                <div id="batchProgressList" style="margin-top:12px;font-size:13px;color:var(--text-secondary);text-align:center;">暂无批次记录，点击「刷新列表」查看</div>
            </div>

''' + progress_marker

if 'id="quant-batch"' not in content:
    if progress_marker in content:
        content = content.replace(progress_marker, batch_panel, 1)
        changes += 1
        log.append('PATCH 2 OK: Added batch panel')
    else:
        log.append('PATCH 2 ERROR: Cannot find inline-progress marker')
else:
    log.append('PATCH 2 SKIP: Batch panel already exists')


# ============================
# PATCH 3: Add quantBatch to files object
# ============================
old_files = "var files = { qualVoice: [], qualImage: [], quantImage: [], quantVoice: [] };"
new_files = "var files = { qualVoice: [], qualImage: [], quantImage: [], quantVoice: [], quantBatch: [] };"

if old_files in content:
    content = content.replace(old_files, new_files, 1)
    changes += 1
    log.append('PATCH 3 OK: Added quantBatch to files object')
elif 'quantBatch' in content:
    log.append('PATCH 3 SKIP: quantBatch already in files')
else:
    log.append('PATCH 3 ERROR: Cannot find files object')


# ============================
# PATCH 4: Add setupFileInput for batch
# ============================
setup_marker = "setupFileInput('quantVoiceInput', 'quantVoiceList', 'quantVoiceBtn', 'quantVoice');"
new_setup = setup_marker + "\n    setupFileInput('quantBatchInput', 'quantBatchList', 'quantBatchBtn', 'quantBatch');"

if "setupFileInput('quantBatchInput'" not in content:
    if setup_marker in content:
        content = content.replace(setup_marker, new_setup, 1)
        changes += 1
        log.append('PATCH 4 OK: Added batch setupFileInput')
    else:
        log.append('PATCH 4 ERROR: Cannot find quantVoice setupFileInput marker')
else:
    log.append('PATCH 4 SKIP: Batch setupFileInput already exists')


# ============================
# PATCH 5: Add processBatch() and refreshBatchProgress() JS functions
# ============================
batch_js_insert_marker = '/* ===== Batch Integration Module ===== */'

batch_js_code = '''/* ===== Batch Queue Upload ===== */
function processBatch() {
    var templateId = document.getElementById('quantTemplate').value;
    if (!templateId) { showToast('请选择识别模板', 'error'); return; }
    var fileArr = files.quantBatch;
    if (!fileArr.length) { showToast('请先上传文件', 'error'); return; }
    if (fileArr.length > 100) { showToast('最多上传 100 个文件', 'error'); return; }
    var fd = new FormData();
    fd.append('role_id', currentDepartment);
    fd.append('template_id', templateId);
    fileArr.forEach(function(f) { fd.append('files', f); });
    showProgress('批量处理中，请稍候...');
    updateProgress(20, '提交队列...');
    fetch('/batch_process', { method: 'POST', body: fd })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        updateProgress(100, '完成');
        setTimeout(function() {
            hideProgress();
            if (data.results && data.results.length) {
                currentResults = data.results;
                showResults(data.results);
                showToast('批量处理完成，共 ' + data.results.length + ' 份', 'success');
            }
            if (data.errors) data.errors.forEach(function(e) { showToast(e, 'error'); });
            if (data.batch_id) {
                lastBatchId = data.batch_id;
                var bar = document.getElementById('quantExportBar');
                bar.style.display = 'flex';
                document.getElementById('quantBatchIdDisplay').textContent = data.batch_id;
                document.getElementById('quantResultCount').textContent = data.results ? data.results.length : 0;
            }
            files.quantBatch = [];
            renderFileList('quantBatchList', 'quantBatch', 'quantBatchBtn');
            refreshHistory();
            refreshStats();
        }, 500);
    })
    .catch(function(err) { hideProgress(); showToast('批量处理失败: ' + err.message, 'error'); });
}

function refreshBatchProgress() {
    var container = document.getElementById('batchProgressList');
    container.innerHTML = '<div style="color:var(--primary);">正在刷新...</div>';
    fetch('/api/records?page_size=10&module_type=image_ocr')
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.status !== 'success' || !data.records || !data.records.length) {
            container.innerHTML = '暂无批次记录';
            return;
        }
        var html = '<div style="text-align:left;">';
        var batches = {};
        data.records.forEach(function(r) {
            var bid = r.batch_id || '无批次';
            if (!batches[bid]) batches[bid] = [];
            batches[bid].push(r);
        });
        for (var bid in batches) {
            html += '<div style="padding:8px 12px;margin-bottom:6px;background:white;border:1px solid var(--border);border-radius:8px;">';
            html += '<strong>' + bid + '</strong> - ' + batches[bid].length + ' 条记录';
            html += '</div>';
        }
        html += '</div>';
        container.innerHTML = html;
    })
    .catch(function() { container.innerHTML = '刷新失败'; });
}

''' + batch_js_insert_marker

if 'function processBatch(' not in content:
    if batch_js_insert_marker in content:
        content = content.replace(batch_js_insert_marker, batch_js_code, 1)
        changes += 1
        log.append('PATCH 5 OK: Added processBatch + refreshBatchProgress functions')
    else:
        log.append('PATCH 5 ERROR: Cannot find batch integration marker')
else:
    log.append('PATCH 5 SKIP: processBatch already exists')


# ============================
# Write back
# ============================
if changes > 0:
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(content)
    log.append(f'DONE: {changes} patches applied, file saved ({len(content)} bytes)')
else:
    log.append('NO CHANGES: All patches already applied or failed')

with open(log_path, 'w', encoding='utf-8') as f:
    f.write('\n'.join(log))
print('\n'.join(log))
