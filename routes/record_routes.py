# -*- coding: utf-8 -*-
"""Record management routes Blueprint"""

import os, json, shutil
from datetime import datetime
from flask import Blueprint, request, jsonify, send_file
from config import app, get_db
from auth import login_required, get_current_user_id, log_audit
from services.export_service import generate_excel, generate_unified_excel
from services.data_analysis import (
    _extract_nested_field, _collect_field_paths, _is_numeric,
    analyze_structured_data,
)

record_bp = Blueprint("record", __name__)

@record_bp.route('/records', methods=['GET'])
@login_required
def get_records():
    role_id = request.args.get('role_id', None)
    module_type = request.args.get('module_type', None)
    conn = get_db()
    c = conn.cursor()

    conditions = []
    params = []
    conditions.append("user_id=?")
    params.append(get_current_user_id())
    if role_id:
        conditions.append("role_id=?")
        params.append(role_id)
    if module_type:
        conditions.append("module_type=?")
        params.append(module_type)

    where_clause = (" WHERE " + " AND ".join(conditions)) if conditions else ""
    c.execute(f'''SELECT id, case_number, original_filename, role_id, template_id,
        create_time, source_type, module_type
        FROM medical_records{where_clause} ORDER BY create_time DESC''', params)
    rows = c.fetchall()
    conn.close()

    records = []
    for row in rows:
        records.append({
            "id": row['id'],
            "case_number": row['case_number'],
            "filename": row['original_filename'],
            "role_id": row['role_id'] or 'general',
            "template_id": row['template_id'] or '',
            "create_time": row['create_time'],
            "source_type": row['source_type'] or 'image',
            "module_type": row['module_type'] or 'image_ocr'
        })
    return jsonify({"status": "success", "records": records})


@record_bp.route('/record/<record_id>', methods=['GET'])
@login_required
def get_record_detail(record_id):
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT * FROM medical_records WHERE id=? AND user_id=?', (record_id, get_current_user_id()))
        row = c.fetchone()

        # 查模板信息
        template_name = ''
        display_layout = 'table'
        if row and row['template_id']:
            c.execute("SELECT template_name, display_layout FROM extraction_templates WHERE template_id=?",
                      (row['template_id'],))
            tpl = c.fetchone()
            if tpl:
                template_name = tpl['template_name']
                display_layout = tpl['display_layout']
        conn.close()

        if not row:
            return jsonify({"status": "error", "msg": "记录不存在"})

        role_id = row['role_id'] or 'other'

        # 兼容旧数据
        if row['extracted_data']:
            extracted_data = json.loads(row['extracted_data'])
            confidence_data = json.loads(row['confidence_data']) if row['confidence_data'] else {}
        else:
            # 旧格式兼容
            extracted_data = {
                'demographics': json.loads(row['demographics']) if row['demographics'] else {},
                'lab_tests': json.loads(row['lab_tests']) if row['lab_tests'] else [],
                'treatment': json.loads(row['treatment']) if row['treatment'] else {},
            }
            confidence_data = json.loads(row['confidence']) if row['confidence'] else {}
            display_layout = 'table'
            template_name = '综合科研数据提取'

        return jsonify({
            "status": "success",
            "data": {
                "id": row['id'],
                "case_number": row['case_number'],
                "filename": row['original_filename'],
                "role_id": role_id,
                "template_name": template_name,
                "display_layout": display_layout,
                "extracted_data": extracted_data,
                "confidence": confidence_data,
                "create_time": row['create_time'],
                "source_type": row['source_type'] or 'image',
                "module_type": row['module_type'] or 'image_ocr',
                "audio_transcript": row['audio_transcript'] if (row['source_type'] == 'audio') else None,
                "qualitative_data": json.loads(row['qualitative_data']) if row['qualitative_data'] else None,
                "text_source": row['text_source'] if (row['source_type'] == 'text') else None,
                "analysis_type": row['analysis_type'] if row['module_type'] == 'qualitative' else None
            }
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "msg": f"查看记录失败: {str(e)}"}), 500


@record_bp.route('/record/<record_id>', methods=['PUT'])
@login_required
def update_record(record_id):
    update_data = request.get_json()
    if not update_data:
        return jsonify({"status": "error", "msg": "无更新数据"})

    conn = get_db()
    c = conn.cursor()
    if 'extracted_data' in update_data:
        c.execute("UPDATE medical_records SET extracted_data=? WHERE id=? AND user_id=?",
                  (json.dumps(update_data['extracted_data'], ensure_ascii=False), record_id, get_current_user_id()))
    if 'confidence' in update_data:
        c.execute("UPDATE medical_records SET confidence_data=? WHERE id=? AND user_id=?",
                  (json.dumps(update_data['confidence'], ensure_ascii=False), record_id, get_current_user_id()))
    conn.commit()
    conn.close()
    return jsonify({"status": "success", "msg": "数据已更新"})


@record_bp.route('/record/<record_id>', methods=['DELETE'])
@login_required
def delete_record(record_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('DELETE FROM medical_records WHERE id=? AND user_id=?', (record_id, get_current_user_id()))
    conn.commit()
    conn.close()
    log_audit('delete', 'record', record_id)
    return jsonify({"status": "success", "msg": "记录已删除"})


@record_bp.route('/export', methods=['POST'])
@login_required
def export_excel():
    req_data = request.get_json() or {}
    record_ids = req_data.get('record_ids', [])
    role_filter = req_data.get('role_id', None)

    conn = get_db()
    c = conn.cursor()

    if record_ids:
        placeholders = ','.join(['?'] * len(record_ids))
        c.execute(f'SELECT * FROM medical_records WHERE id IN ({placeholders}) AND user_id=?', record_ids + [get_current_user_id()])
    elif role_filter:
        c.execute('SELECT * FROM medical_records WHERE role_id=? AND user_id=? ORDER BY create_time', (role_filter, get_current_user_id()))
    else:
        c.execute('SELECT * FROM medical_records WHERE user_id=? ORDER BY create_time', (get_current_user_id(),))

    rows = c.fetchall()
    conn.close()

    if not rows:
        return jsonify({"status": "error", "msg": "暂无可导出的数据"})

    data_list = _rows_to_export_list(rows)
    excel_path = generate_excel(data_list)
    return send_file(excel_path, as_attachment=True,
                     download_name=f"临床数据_{datetime.now().strftime('%Y%m%d')}.xlsx")


@record_bp.route('/export_all', methods=['GET'])
@login_required
def export_all_excel():
    role_filter = request.args.get('role_id', None)
    conn = get_db()
    c = conn.cursor()
    if role_filter:
        c.execute('SELECT * FROM medical_records WHERE role_id=? AND user_id=? ORDER BY create_time', (role_filter, get_current_user_id()))
    else:
        c.execute('SELECT * FROM medical_records WHERE user_id=? ORDER BY create_time', (get_current_user_id(),))
    rows = c.fetchall()
    conn.close()

    if not rows:
        return jsonify({"status": "error", "msg": "暂无可导出的数据"})

    data_list = _rows_to_export_list(rows)
    excel_path = generate_excel(data_list)
    return send_file(excel_path, as_attachment=True,
                     download_name=f"临床数据_{datetime.now().strftime('%Y%m%d')}.xlsx")


def _rows_to_export_list(rows):
    """将数据库行转为导出数据列表"""
    conn = get_db()
    c = conn.cursor()
    data_list = []
    for row in rows:
        role_id = row['role_id'] or 'other'
        template_name = ''
        if row['template_id']:
            c.execute("SELECT template_name FROM extraction_templates WHERE template_id=?",
                      (row['template_id'],))
            tpl = c.fetchone()
            if tpl:
                template_name = tpl['template_name']

        if row['extracted_data']:
            extracted = json.loads(row['extracted_data'])
            conf = json.loads(row['confidence_data']) if row['confidence_data'] else {}
        else:
            extracted = {
                'demographics': json.loads(row['demographics']) if row['demographics'] else {},
                'lab_tests': json.loads(row['lab_tests']) if row['lab_tests'] else [],
                'treatment': json.loads(row['treatment']) if row['treatment'] else {},
            }
            conf = json.loads(row['confidence']) if row['confidence'] else {}

        data_list.append({
            'case_number': row['case_number'],
            'create_time': row['create_time'],
            'role_id': role_id,
            'template_name': template_name,
            'original_filename': row['original_filename'] or '',
            'extracted_data': extracted,
            'confidence_data': conf,
            'source_type': row['source_type'] or 'image',
            'audio_transcript': row['audio_transcript'] if row['source_type'] == 'audio' else None,
            'qualitative_data': json.loads(row['qualitative_data']) if row['qualitative_data'] else None,
        })
    conn.close()
    return data_list






@record_bp.route('/clean', methods=['POST'])
@login_required
def clean_all():
    try:
        shutil.rmtree(app.config['UPLOAD_FOLDER'])
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    except Exception:
        pass
    conn = get_db()
    c = conn.cursor()
    c.execute('DELETE FROM medical_records WHERE user_id=?', (get_current_user_id(),))
    conn.commit()
    conn.close()
    log_audit('clean_all', 'record', None, '清除所有记录')
    return jsonify({"status": "success", "msg": "所有数据已清理"})


@record_bp.route('/stats', methods=['GET'])
@login_required
def get_stats():
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT COUNT(*) as cnt FROM medical_records WHERE user_id=?', (get_current_user_id(),))
    total = c.fetchone()['cnt']
    # 按角色统计
    c.execute("SELECT role_id, COUNT(*) as cnt FROM medical_records WHERE user_id=? GROUP BY role_id", (get_current_user_id(),))
    by_role = {}
    for row in c.fetchall():
        by_role[row['role_id'] or 'other'] = row['cnt']
    conn.close()
    return jsonify({"status": "success", "total_records": total, "by_role": by_role})


@record_bp.route('/data_analysis/fields', methods=['GET'])
@login_required
def data_analysis_fields():
    """获取选中记录的所有可用数值字段"""
    record_ids = request.args.getlist('ids')
    if not record_ids:
        return jsonify({"status": "error", "msg": "请选择记录"})

    conn = get_db()
    c = conn.cursor()
    placeholders = ','.join(['?'] * len(record_ids))
    c.execute(f'SELECT extracted_data FROM medical_records WHERE id IN ({placeholders})', record_ids)
    rows = c.fetchall()
    conn.close()

    all_paths = set()
    for row in rows:
        if row['extracted_data']:
            data = json.loads(row['extracted_data'])
            paths = _collect_field_paths(data)
            all_paths.update(paths)

    # 过滤出含数值的字段
    numeric_fields = []
    text_fields = []
    for path in sorted(all_paths):
        has_numeric = False
        for row in rows:
            if row['extracted_data']:
                data = json.loads(row['extracted_data'])
                val = _extract_nested_field(data, path)
                if _is_numeric(val):
                    has_numeric = True
                    break
        if has_numeric:
            numeric_fields.append(path)
        else:
            text_fields.append(path)

    return jsonify({
        "status": "success",
        "numeric_fields": numeric_fields,
        "text_fields": text_fields
    })


@record_bp.route('/data_analysis/analyze', methods=['POST'])
@login_required
def data_analysis_analyze():
    """数据分析模块：对选中记录进行统计分析"""
    req_data = request.get_json()
    if not req_data:
        return jsonify({"status": "error", "msg": "无请求数据"})

    record_ids = req_data.get('record_ids', [])
    fields = req_data.get('fields', [])
    analysis_type = req_data.get('analysis_type', 'descriptive')

    if not record_ids:
        return jsonify({"status": "error", "msg": "请选择至少1条记录"})
    if not fields:
        return jsonify({"status": "error", "msg": "请选择至少1个分析字段"})

    try:
        result = analyze_structured_data(record_ids, fields, analysis_type)
        return jsonify({"status": "success", **result})
    except Exception as e:
        return jsonify({"status": "error", "msg": f"分析失败: {str(e)}"})

