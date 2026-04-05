# -*- coding: utf-8 -*-
"""MedSnap global config"""
import os
import json
import uuid
import base64
import tempfile
import sqlite3
import shutil
import re
from datetime import datetime
from flask import Flask, render_template, request, send_file, jsonify, session, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash
from auth import login_required, get_current_user_id
from openai import OpenAI
from PIL import Image, ImageFilter, ImageEnhance, ImageOps
Image.MAX_IMAGE_PIXELS = None  # Allow large questionnaire scans
import numpy as np
import pandas as pd
from desensitizer import desensitize_text, desensitize_structured_data

HAS_PYMUPDF = False
try:
    import fitz
    HAS_PYMUPDF = True
except ImportError:
    pass

HAS_DASHSCOPE = False
try:
    import dashscope
    from dashscope.audio.asr import Recognition
    HAS_DASHSCOPE = True
except ImportError:
    pass

HAS_PYDUB = False
try:
    from pydub import AudioSegment
    HAS_PYDUB = True
except ImportError:
    pass

HAS_TESSERACT = False
try:
    import pytesseract
    HAS_TESSERACT = True
    # Windows下Tesseract默认安装路径
    import platform
    if platform.system() == 'Windows':
        _tesseract_paths = [
            r'C:\Program Files\Tesseract-OCR\tesseract.exe',
            r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe',
        ]
        for _tp in _tesseract_paths:
            if os.path.exists(_tp):
                pytesseract.pytesseract.tesseract_cmd = _tp
                break
except ImportError:
    pass

# ========== Flask 应用初始化 ==========
app = Flask(__name__)
_secret_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.secret_key')
if os.path.exists(_secret_file):
    app.secret_key = open(_secret_file, 'r').read().strip()
else:
    app.secret_key = uuid.uuid4().hex
    with open(_secret_file, 'w') as f:
        f.write(app.secret_key)
app.config['JSON_AS_ASCII'] = False
try:
    app.json.ensure_ascii = False
except (AttributeError, TypeError):
    pass

UPLOAD_DIR = os.path.join(tempfile.gettempdir(), "medical_ocr_uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_DIR
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'local_medical_data.db')


# ========== 多模态大模型配置 ==========
API_KEY = os.environ.get("DASHSCOPE_API_KEY", "") or os.environ.get("MODELSCOPE_API_KEY", "")
if not API_KEY:
    print("[WARN] 环境变量 DASHSCOPE_API_KEY 未设置，AI识别功能将不可用")
client = OpenAI(
    base_url='https://dashscope.aliyuncs.com/compatible-mode/v1',
    api_key=API_KEY
)
MODEL_NAME = "qwen-vl-max"

# ========== 语音识别配置 ==========
DASHSCOPE_API_KEY = API_KEY
if not DASHSCOPE_API_KEY:
    print("[WARN] 环境变量 DASHSCOPE_API_KEY 未设置，语音识别功能将不可用")
if HAS_DASHSCOPE and DASHSCOPE_API_KEY:
    dashscope.api_key = DASHSCOPE_API_KEY

ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'bmp', 'tiff', 'pdf'}
ALLOWED_AUDIO_EXTENSIONS = {'wav', 'mp3', 'aac', 'amr', 'opus', 'm4a', 'flac'}
ALLOWED_TEXT_EXTENSIONS = {'txt', 'doc', 'docx'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def is_audio_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_AUDIO_EXTENSIONS

def is_text_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_TEXT_EXTENSIONS


# ========== 科室与模板配置 ==========
DEPARTMENT_CONFIGS = {
    'cardiology':  {'name': '心内科',   'color': '#dc2626'},
    'neurology':   {'name': '神经内科', 'color': '#7c3aed'},
    'surgery':     {'name': '外科',     'color': '#0891b2'},
    'pediatrics':  {'name': '儿科',     'color': '#f59e0b'},
    'obstetrics':  {'name': '妇产科',   'color': '#ec4899'},
    'emergency':   {'name': '急诊科',   'color': '#ef4444'},
    'general':     {'name': '通用',     'color': '#64748b'},
}

# 向后兼容：旧角色ID映射到通用科室
LEGACY_ROLE_MAP = {
    'diagnosis': 'general', 'nursing': 'general', 'other': 'general',
    'doctor': 'general', 'nurse': 'general', 'researcher': 'general',
}

# 保留旧名供内部兼容
CATEGORY_CONFIGS = DEPARTMENT_CONFIGS

# ========== 数据库初始化 ==========
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

