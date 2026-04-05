# -*- coding: utf-8 -*-
"""Auth routes Blueprint"""

import uuid, json
from datetime import datetime
from flask import Blueprint, render_template, request, jsonify, session, redirect
from werkzeug.security import generate_password_hash, check_password_hash
from config import get_db
from auth import login_required, get_current_user_id, log_audit

auth_bp = Blueprint("auth", __name__)

@auth_bp.route('/login')
def login_page():
    if session.get('user_id'):
        return redirect('/')
    return render_template('login.html')


@auth_bp.route('/api/auth/register', methods=['POST'])
def api_register():
    data = request.get_json()
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''
    display_name = (data.get('display_name') or '').strip() or username
    if len(username) < 2 or len(username) > 30:
        return jsonify({"status": "error", "msg": "用户名长度应为 2-30 个字符"})
    if len(password) < 6:
        return jsonify({"status": "error", "msg": "密码长度不少于 6 位"})
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id FROM users WHERE username=?", (username,))
    if c.fetchone():
        conn.close()
        return jsonify({"status": "error", "msg": "用户名已存在"})
    user_id = str(uuid.uuid4())
    c.execute("INSERT INTO users (id, username, password_hash, display_name, role, create_time) VALUES (?,?,?,?,?,?)",
              (user_id, username, generate_password_hash(password), display_name, 'user', datetime.now().isoformat()))
    conn.commit()
    conn.close()
    session['user_id'] = user_id
    session['username'] = username
    session['display_name'] = display_name
    session['role'] = 'user'
    log_audit('register', 'user', user_id)
    return jsonify({"status": "success", "user": {"id": user_id, "username": username, "display_name": display_name, "role": "user"}})


@auth_bp.route('/api/auth/login', methods=['POST'])
def api_login():
    data = request.get_json()
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, username, password_hash, display_name, role, is_active FROM users WHERE username=?", (username,))
    row = c.fetchone()
    conn.close()
    if not row or not check_password_hash(row['password_hash'], password):
        log_audit('login_failed', 'user', detail={"username": username})
        return jsonify({"status": "error", "msg": "用户名或密码错误"}), 401
    if row['is_active'] is not None and int(row['is_active']) == 0:
        return jsonify({"status": "error", "msg": "账号已被禁用，请联系管理员"}), 403
    role = row['role'] or 'user'
    session['user_id'] = row['id']
    session['username'] = row['username']
    session['display_name'] = row['display_name'] or row['username']
    session['role'] = role
    log_audit('login', 'user', row['id'])
    return jsonify({"status": "success", "user": {"id": row['id'], "username": row['username'], "display_name": row['display_name'] or row['username'], "role": role}})


@auth_bp.route('/api/auth/logout', methods=['POST'])
def api_logout():
    log_audit('logout')
    session.clear()
    return jsonify({"status": "success"})


@auth_bp.route('/api/auth/me')
def api_auth_me():
    uid = session.get('user_id')
    if not uid:
        return jsonify({"status": "error", "msg": "未登录"}), 401
    return jsonify({"status": "success", "user": {
        "id": uid,
        "username": session.get('username', ''),
        "display_name": session.get('display_name', ''),
        "role": session.get('role', 'user')
    }})
