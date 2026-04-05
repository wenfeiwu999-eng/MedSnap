# -*- coding: utf-8 -*-
"""Admin management routes Blueprint"""

import uuid, json
from datetime import datetime
from flask import Blueprint, render_template, request, jsonify
from werkzeug.security import generate_password_hash
from config import get_db
from auth import admin_required, get_current_user_id, log_audit

admin_bp = Blueprint("admin", __name__)


@admin_bp.route('/admin')
@admin_required
def admin_page():
    return render_template('admin.html')


@admin_bp.route('/api/admin/users')
@admin_required
def admin_list_users():
    try:
        page = max(1, int(request.args.get('page', 1)))
        page_size = min(100, max(1, int(request.args.get('page_size', 20))))
        keyword = request.args.get('keyword', '').strip()
        conn = get_db()
        c = conn.cursor()
        conditions, params = [], []
        if keyword:
            conditions.append("(username LIKE ? OR display_name LIKE ?)")
            kw = f'%{keyword}%'
            params.extend([kw, kw])
        where = (' WHERE ' + ' AND '.join(conditions)) if conditions else ''
        total = c.execute(f"SELECT COUNT(*) FROM users{where}", params).fetchone()[0]
        offset = (page - 1) * page_size
        rows = c.execute(f"SELECT id, username, display_name, role, is_active, create_time FROM users{where} ORDER BY create_time DESC LIMIT ? OFFSET ?", params + [page_size, offset]).fetchall()
        conn.close()
        users = [{"id": r["id"], "username": r["username"], "display_name": r["display_name"], "role": r["role"] or "user", "is_active": 1 if r["is_active"] is None else int(r["is_active"]), "create_time": r["create_time"]} for r in rows]
        return jsonify({"status": "success", "users": users, "total": total, "page": page, "page_size": page_size})
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)})

@admin_bp.route('/api/admin/users/<user_id>', methods=['PUT'])
@admin_required
def admin_update_user(user_id):
    try:
        data = request.get_json()
        conn = get_db()
        c = conn.cursor()
        row = c.execute("SELECT id, username, role FROM users WHERE id=?", (user_id,)).fetchone()
        if not row:
            conn.close()
            return jsonify({"status": "error", "msg": "用户不存在"})
        if user_id == get_current_user_id() and 'role' in data:
            conn.close()
            return jsonify({"status": "error", "msg": "不能修改自己的角色"})
        updates, vals = [], []
        if 'role' in data and data['role'] in ('admin', 'user'):
            updates.append("role=?")
            vals.append(data['role'])
        if 'display_name' in data:
            updates.append("display_name=?")
            vals.append(data['display_name'])
        if not updates:
            conn.close()
            return jsonify({"status": "error", "msg": "无有效更新字段"})
        vals.append(user_id)
        c.execute(f"UPDATE users SET {', '.join(updates)} WHERE id=?", vals)
        conn.commit()
        conn.close()
        log_audit('admin_update_user', 'user', user_id, {'changes': data})
        return jsonify({"status": "success", "msg": "更新成功"})
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)})


@admin_bp.route('/api/admin/users/<user_id>/toggle', methods=['POST'])
@admin_required
def admin_toggle_user(user_id):
    try:
        if user_id == get_current_user_id():
            return jsonify({"status": "error", "msg": "不能禁用自己的账号"})
        conn = get_db()
        c = conn.cursor()
        row = c.execute("SELECT is_active FROM users WHERE id=?", (user_id,)).fetchone()
        if not row:
            conn.close()
            return jsonify({"status": "error", "msg": "用户不存在"})
        new_status = 0 if (row['is_active'] is None or int(row['is_active']) == 1) else 1
        c.execute("UPDATE users SET is_active=? WHERE id=?", (new_status, user_id))
        conn.commit()
        conn.close()
        action = 'admin_enable_user' if new_status == 1 else 'admin_disable_user'
        log_audit(action, 'user', user_id)
        return jsonify({"status": "success", "is_active": new_status, "msg": "已启用" if new_status else "已禁用"})
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)})


@admin_bp.route('/api/admin/users/<user_id>/reset_password', methods=['POST'])
@admin_required
def admin_reset_password(user_id):
    try:
        data = request.get_json()
        new_password = data.get('new_password', '')
        if len(new_password) < 6:
            return jsonify({"status": "error", "msg": "密码长度不少于 6 位"})
        conn = get_db()
        c = conn.cursor()
        row = c.execute("SELECT id FROM users WHERE id=?", (user_id,)).fetchone()
        if not row:
            conn.close()
            return jsonify({"status": "error", "msg": "用户不存在"})
        c.execute("UPDATE users SET password_hash=? WHERE id=?", (generate_password_hash(new_password), user_id))
        conn.commit()
        conn.close()
        log_audit('admin_reset_password', 'user', user_id)
        return jsonify({"status": "success", "msg": "密码已重置"})
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)})

@admin_bp.route('/api/admin/audit_logs')
@admin_required
def admin_audit_logs():
    try:
        page = max(1, int(request.args.get('page', 1)))
        page_size = min(100, max(1, int(request.args.get('page_size', 20))))
        user_id_filter = request.args.get('user_id', '').strip()
        action_filter = request.args.get('action', '').strip()
        conn = get_db()
        c = conn.cursor()
        conditions, params = [], []
        if user_id_filter:
            conditions.append("user_id=?")
            params.append(user_id_filter)
        if action_filter:
            conditions.append("action=?")
            params.append(action_filter)
        where = (' WHERE ' + ' AND '.join(conditions)) if conditions else ''
        total = c.execute(f"SELECT COUNT(*) FROM audit_log{where}", params).fetchone()[0]
        offset = (page - 1) * page_size
        rows = c.execute(f"SELECT * FROM audit_log{where} ORDER BY create_time DESC LIMIT ? OFFSET ?", params + [page_size, offset]).fetchall()
        conn.close()
        logs = [dict(r) for r in rows]
        return jsonify({"status": "success", "logs": logs, "total": total, "page": page, "page_size": page_size})
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)})


@admin_bp.route('/api/admin/system_stats')
@admin_required
def admin_system_stats():
    try:
        conn = get_db()
        c = conn.cursor()
        today = datetime.now().strftime('%Y-%m-%d')
        total_users = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        active_users = c.execute("SELECT COUNT(*) FROM users WHERE is_active=1 OR is_active IS NULL").fetchone()[0]
        total_records = c.execute("SELECT COUNT(*) FROM medical_records").fetchone()[0]
        total_templates = c.execute("SELECT COUNT(*) FROM extraction_templates").fetchone()[0]
        total_results = c.execute("SELECT COUNT(*) FROM research_results").fetchone()[0]
        logins_today = c.execute("SELECT COUNT(*) FROM audit_log WHERE action='login' AND create_time LIKE ?", (today + '%',)).fetchone()[0]
        records_today = c.execute("SELECT COUNT(*) FROM medical_records WHERE create_time LIKE ?", (today + '%',)).fetchone()[0]
        conn.close()
        return jsonify({"status": "success", "stats": {
            "total_users": total_users, "active_users": active_users,
            "total_records": total_records, "total_templates": total_templates,
            "total_results": total_results, "logins_today": logins_today,
            "records_today": records_today
        }})
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)})

