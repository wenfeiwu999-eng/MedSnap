# -*- coding: utf-8 -*-
import functools, uuid, json
from datetime import datetime
from flask import session, request, jsonify, redirect


def login_required(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get('user_id'):
            if request.is_json or request.path.startswith('/api/'):
                return jsonify({"status": "error", "msg": "未登录"}), 401
            return redirect('/login')
        return f(*args, **kwargs)
    return wrapper


def admin_required(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get('user_id'):
            if request.is_json or request.path.startswith('/api/'):
                return jsonify({"status": "error", "msg": "未登录"}), 401
            return redirect('/login')
        if session.get('role') != 'admin':
            if request.is_json or request.path.startswith('/api/'):
                return jsonify({"status": "error", "msg": "权限不足"}), 403
            return redirect('/')
        return f(*args, **kwargs)
    return wrapper


def get_current_user_id():
    return session.get('user_id')


def get_current_user_role():
    return session.get('role', 'user')


def log_audit(action, target_type=None, target_id=None, detail=None):
    """Insert an audit log record. Silently fails to avoid breaking main flow."""
    try:
        from config import get_db
        conn = get_db()
        c = conn.cursor()
        c.execute(
            "INSERT INTO audit_log (id, user_id, username, action, target_type, target_id, detail, ip_address, create_time) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                str(uuid.uuid4()),
                session.get('user_id'),
                session.get('username', ''),
                action,
                target_type,
                str(target_id) if target_id else None,
                json.dumps(detail, ensure_ascii=False) if isinstance(detail, (dict, list)) else detail,
                request.remote_addr if request else None,
                datetime.now().isoformat(),
            )
        )
        conn.commit()
        conn.close()
    except Exception:
        pass
