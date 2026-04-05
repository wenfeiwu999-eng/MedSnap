# -*- coding: utf-8 -*-
"""Data extraction, upload, batch routes Blueprint"""

import os, json, uuid
from datetime import datetime
from flask import Blueprint, render_template, request, jsonify, send_file
from config import (
    app, get_db, allowed_file, is_audio_file, is_text_file,
    DEPARTMENT_CONFIGS, client, MODEL_NAME,
)
from auth import login_required, get_current_user_id, log_audit
from services.ai_service import (
    extract_medical_data, extract_medical_data_multimodal,
    parse_ai_response, transcribe_audio, extract_from_transcript,
    qualitative_analysis, qualitative_analysis_enhanced,
    _parse_text_file, _preprocess_text,
)
from services.file_processor import image_to_base64, pdf_to_images, preprocess_image, local_ocr, local_ocr_pdf
from services.export_service import generate_unified_excel
from prompts import PROMPT_FIELD_PREVIEW, PROMPT_FIELD_PREVIEW_TEXT, PROMPT_EXTRACT_FIELD_NAMES
from desensitizer import desensitize_text

extraction_bp = Blueprint("extraction", __name__)

@extraction_bp.route('/api/extract_fields_from_text', methods=['POST'])
@login_required
def api_extract_fields_from_text():
    """从用户输入的描述性文本中智能提取可用作模板字段的名称"""
    try:
        data = request.get_json()
        text = (data.get('text', '') or '').strip()
        role_id = data.get('role_id', 'general')

        if len(text) < 5:
            return jsonify({"status": "error", "msg": "请输入更多文本内容（至少5个字符）"})

        if role_id not in ('diagnosis', 'nursing', 'other'):
            role_id = 'other'

        role_hints = {
            'diagnosis': '诊疗数据提取',
            'nursing': '护理评估数据提取',
            'other': '综合数据提取'
        }
        role_hint = role_hints[role_id]

        # 脱敏处理
        masked_text, _report = desensitize_text(text)

        # 构建 prompt 并调用 LLM
        prompt = PROMPT_EXTRACT_FIELD_NAMES.format(
            role_hint=role_hint,
            text_content=masked_text
        )

        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[{'role': 'user', 'content': prompt}],
            temperature=0.1,
            max_tokens=2048
        )
        raw_text = response.choices[0].message.content
        parsed = parse_ai_response(raw_text)

        # 提取字段列表
        fields = parsed.get('fields', [])
        if not isinstance(fields, list):
            fields = []

        # 过滤低置信度字段并去重
        seen = set()
        filtered = []
        category_order = {'基本信息': 0, '检验结果': 1, '诊疗记录': 2, '护理评估': 3, '科研数据': 4, '其他': 5}
        for f in fields:
            if not isinstance(f, dict):
                continue
            name = (f.get('name', '') or '').strip()
            confidence = f.get('confidence', 0)
            if not name or name in seen:
                continue
            if isinstance(confidence, (int, float)) and confidence < 0.5:
                continue
            seen.add(name)
            filtered.append({
                'name': name,
                'category': f.get('category', '其他'),
                'confidence': round(confidence, 2) if isinstance(confidence, (int, float)) else 0.8
            })

        # 按类别排序
        filtered.sort(key=lambda x: category_order.get(x['category'], 5))

        return jsonify({"status": "success", "fields": filtered})

    except Exception as e:
        return jsonify({"status": "error", "msg": f"分析失败: {str(e)}"})


@extraction_bp.route('/api/preview_fields', methods=['POST'])
@login_required
def api_preview_fields():
    """文档字段预览 - 分析文档并返回可提取的字段列表"""
    text_content = request.form.get('text_content', '').strip()
    uploaded_files = request.files.getlist('files')

    raw_data = None
    fields = []

    try:
        if text_content:
            # 文本模式
            prompt = PROMPT_FIELD_PREVIEW_TEXT.format(text_content=text_content)
            response = client.chat.completions.create(
                model=MODEL_NAME,
                messages=[{'role': 'user', 'content': prompt}],
                temperature=0.1,
                max_tokens=16384
            )
            raw_data = parse_ai_response(response.choices[0].message.content)

        elif uploaded_files and uploaded_files[0].filename:
            file = uploaded_files[0]
            file_ext = os.path.splitext(file.filename)[1].lower()
            temp_name = f"{uuid.uuid4().hex}{file_ext}"
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], temp_name)
            file.save(file_path)

            try:
                if is_audio_file(file.filename):
                    transcript_result = transcribe_audio(file_path)
                    transcript_text = transcript_result['text']
                    prompt = PROMPT_FIELD_PREVIEW_TEXT.format(text_content=transcript_text)
                    response = client.chat.completions.create(
                        model=MODEL_NAME,
                        messages=[{'role': 'user', 'content': prompt}],
                        temperature=0.1,
                        max_tokens=16384
                    )
                    raw_data = parse_ai_response(response.choices[0].message.content)
                elif is_text_file(file.filename):
                    raw_file_text = _parse_text_file(file_path)
                    processed_text = _preprocess_text(raw_file_text)
                    prompt = PROMPT_FIELD_PREVIEW_TEXT.format(text_content=processed_text)
                    response = client.chat.completions.create(
                        model=MODEL_NAME,
                        messages=[{'role': 'user', 'content': prompt}],
                        temperature=0.1,
                        max_tokens=16384
                    )
                    raw_data = parse_ai_response(response.choices[0].message.content)
                else:
                    # 图片/PDF模式
                    if file_ext == '.pdf':
                        image_paths = pdf_to_images(file_path)
                        if image_paths:
                            raw_data, _ = extract_medical_data_multimodal(image_paths[0], PROMPT_FIELD_PREVIEW)
                            for ip in image_paths:
                                try:
                                    os.remove(ip)
                                except Exception:
                                    pass
                    else:
                        raw_data, _ = extract_medical_data_multimodal(file_path, PROMPT_FIELD_PREVIEW)
            finally:
                try:
                    if os.path.exists(file_path):
                        os.remove(file_path)
                except Exception:
                    pass
        else:
            return jsonify({"status": "error", "msg": "请提供文件或文本内容"})

        if not raw_data or 'error' in raw_data:
            return jsonify({"status": "error", "msg": raw_data.get('error', '分析失败') if raw_data else '分析失败'})

        fields = raw_data.get('available_fields', [])
        # 过滤低置信度字段
        fields = [f for f in fields if f.get('confidence', 0) >= 0.5]
        # 按category排序
        category_order = {'基本信息': 0, '检验结果': 1, '诊疗记录': 2, '护理评估': 3, '其他': 4}
        fields.sort(key=lambda x: category_order.get(x.get('category', '其他'), 4))

        return jsonify({
            "status": "success",
            "fields": fields,
            "raw_data": raw_data
        })
    except Exception as e:
        return jsonify({"status": "error", "msg": f"字段预览失败: {str(e)}"})


@extraction_bp.route('/api/extract_selected', methods=['POST'])
def api_extract_selected_fields():
    """根据用户选择的字段执行提取"""
    data = request.get_json()
    if not data:
        return jsonify({"status": "error", "msg": "无数据"})

    selected_fields = data.get('selected_fields', [])
    role_id = data.get('role_id', 'general')
    sub_type = data.get('sub_type', None)
    cached_raw_data = data.get('raw_data')
    text_content = data.get('text_content', '').strip()

    if not selected_fields:
        return jsonify({"status": "error", "msg": "请至少选择一个字段"})

    results = []
    errors = []
    user_id = get_current_user_id()
    try:
        extracted_data = {}

        if cached_raw_data:
            # 从缓存中筛选字段
            all_fields = cached_raw_data.get('available_fields', [])
            for f in all_fields:
                if f.get('field_name') in selected_fields:
                    extracted_data[f['field_name']] = f.get('example_value')
        elif text_content:
            # 脱敏：在发送远程LLM之前，对文本进行敏感信息脱敏
            masked_content, _privacy_report = desensitize_text(text_content)
            # 动态生成prompt提取
            ai_prompt, _ = _generate_template_prompt(role_id, selected_fields, sub_type=sub_type)
            parsed, raw_text = extract_from_transcript(masked_content, ai_prompt)
            if 'error' not in parsed:
                extracted_data = parsed.get('custom_fields', parsed)
            else:
                return jsonify({"status": "error", "msg": parsed.get('error', '提取失败')})
        else:
            return jsonify({"status": "error", "msg": "缺少数据来源"})

        # 存储到数据库
        case_number = f"DYN_{datetime.now().strftime('%Y%m%d')}_{uuid.uuid4().hex[:6].upper()}"
        record_id = str(uuid.uuid4())
        create_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        conn = get_db()
        c = conn.cursor()
        c.execute('''INSERT INTO medical_records
            (id, case_number, original_filename, role_id, template_id,
             extracted_data, confidence_data, raw_text, create_time,
             source_type, module_type, user_id)
            VALUES (?, ?, ?, ?, 'dynamic_extract', ?, NULL, NULL, ?, 'text', 'dynamic_extract', ?)''',
            (record_id, case_number, '自定义字段提取', role_id,
             json.dumps(extracted_data, ensure_ascii=False), create_time, user_id))
        conn.commit()
        conn.close()

        results.append({
            "id": record_id,
            "case_number": case_number,
            "filename": "自定义字段提取",
            "role_id": role_id,
            "template_name": "自定义字段",
            "display_layout": "table",
            "source_type": "text",
            "module_type": "dynamic_extract",
            "data": extracted_data,
            "create_time": create_time
        })
    except Exception as e:
        errors.append(f"提取失败: {str(e)}")

    return jsonify({
        "status": "success" if results else "error",
        "results": results,
        "errors": errors,
        "msg": f"成功提取 {len(results)} 份" if results else "提取失败"
    })


# ========== 路由: 核心功能 ==========



@extraction_bp.route('/')
@extraction_bp.route('/index')
@login_required
def home():
    return render_template('home.html')

@extraction_bp.route('/data-extraction')
@login_required
def data_extraction():
    return render_template('data_extraction.html')

@extraction_bp.route('/research-results')
@login_required
def research_results_page():
    return render_template('research_results.html')




@extraction_bp.route('/upload', methods=['POST'])
@login_required
def upload_and_recognize():
    """上传文件并AI识别（支持角色/模板选择，支持图片和音频）"""
    if 'files' not in request.files:
        return jsonify({"status": "error", "msg": "未选择文件"})

    files = request.files.getlist('files')
    if not files or files[0].filename == '':
        return jsonify({"status": "error", "msg": "未选择有效文件"})

    role_id = request.form.get('role_id', 'general')
    template_id = request.form.get('template_id', 'tpl_researcher_default')
    module_type = request.form.get('module_type', '')  # 由前端指定

    # 生成批次ID，用于统一导出
    batch_id = f"BATCH_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6].upper()}"
    user_id = get_current_user_id()

    # 查询模板Prompt
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT ai_prompt, template_name, display_layout FROM extraction_templates WHERE template_id=?",
              (template_id,))
    tpl_row = c.fetchone()
    conn.close()

    if not tpl_row:
        return jsonify({"status": "error", "msg": "模板不存在"})

    ai_prompt = tpl_row['ai_prompt']
    template_name = tpl_row['template_name']
    display_layout = tpl_row['display_layout']

    results = []
    errors = []

    for file in files:
        is_audio = is_audio_file(file.filename)
        is_image = allowed_file(file.filename)

        if not is_audio and not is_image:
            errors.append(f"不支持的格式: {file.filename}")
            continue

        file_ext = os.path.splitext(file.filename)[1].lower()
        temp_name = f"{uuid.uuid4().hex}{file_ext}"
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], temp_name)
        file.save(file_path)

        try:
            if is_audio:
                # ========== 音频处理流程 ==========
                result_data = _process_audio_file(
                    file_path, file.filename, role_id, template_id,
                    ai_prompt, template_name, display_layout, batch_id=batch_id, user_id=get_current_user_id())
                if result_data.get('error'):
                    errors.append(f"{file.filename}: {result_data['error']}")
                else:
                    results.append(result_data)
            else:
                # ========== 图片/PDF处理（调用辅助函数，支持batch_id） ==========
                img_results, img_errors = _process_image_file(
                    file_path, file.filename, role_id, template_id,
                    ai_prompt, template_name, display_layout,
                    module_type=module_type or 'image_ocr', batch_id=batch_id, user_id=get_current_user_id())
                results.extend(img_results)
                errors.extend(img_errors)

        except Exception as e:
            errors.append(f"{file.filename}: 识别失败 - {str(e)}")
        finally:
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
            except Exception:
                pass

    if results:
        log_audit('upload', 'record', batch_id, f"上传{len(results)}个文件，{len(errors)}个失败")

    return jsonify({
        "status": "success" if results else "error",
        "batch_id": batch_id,
        "results": results,
        "errors": errors,
        "msg": f"成功识别 {len(results)} 份" + (f"，{len(errors)} 份失败" if errors else "")
    })


def _process_audio_file(audio_path, filename, role_id, template_id,
                        ai_prompt, template_name, display_layout, batch_id=None, user_id=None):
    """处理单个音频文件：语音转写 → 结构化提取 → 可选质性分析"""
    try:
        # 1. 语音转文字
        transcript_result = transcribe_audio(audio_path)
        transcript_text = transcript_result['text']

        # 1.5 脱敏：在发送远程LLM之前，对转录文本进行敏感信息脱敏
        transcript_text, _privacy_report = desensitize_text(transcript_text)

        # 2. 用AI从转录文本提取结构化数据
        data, raw_text = extract_from_transcript(transcript_text, ai_prompt)

        if "error" in data:
            return {"error": data.get('error', '文本提取失败')}

        # 3. 质性分析（仅科研角色）
        qual_result = None
        if role_id == 'other':
            try:
                qual_result = qualitative_analysis(transcript_text)
            except Exception as e:
                print(f"[WARN] 质性分析失败: {e}")

        # 4. 生成记录
        case_number = f"AUDIO_{datetime.now().strftime('%Y%m%d')}_{uuid.uuid4().hex[:6].upper()}"
        record_id = str(uuid.uuid4())
        create_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        confidence_data = data.pop('confidence', {})

        # 5. 存储到数据库
        conn = get_db()
        c = conn.cursor()
        c.execute('''INSERT INTO medical_records
            (id, case_number, original_filename, role_id, template_id,
             extracted_data, confidence_data, raw_text, create_time,
             source_type, audio_transcript, qualitative_data, module_type, batch_id, user_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'audio', ?, ?, 'voice_input', ?, ?)''',
            (record_id, case_number, filename, role_id, template_id,
             json.dumps(data, ensure_ascii=False),
             json.dumps(confidence_data, ensure_ascii=False),
             raw_text, create_time,
             transcript_text,
             json.dumps(qual_result, ensure_ascii=False) if qual_result else None,
             batch_id, user_id))
        conn.commit()
        conn.close()

        return {
            "id": record_id,
            "case_number": case_number,
            "filename": filename,
            "role_id": role_id,
            "template_name": template_name,
            "display_layout": display_layout,
            "source_type": "audio",
            "transcript": transcript_text,
            "qualitative_analysis": qual_result,
            "data": data,
            "confidence": confidence_data,
            "create_time": create_time
        }
    except Exception as e:
        return {"error": f"音频处理失败: {str(e)}"}


def _process_image_file(file_path, filename, role_id, template_id,
                        ai_prompt, template_name, display_layout,
                        module_type='image_ocr', batch_id=None, user_id=None):
    """处理单个图片/PDF文件：OCR识别 → 结构化提取 → 存储
    返回 (results_list, errors_list)"""
    results = []
    errors = []
    file_ext = os.path.splitext(filename)[1].lower()

    try:
        if file_ext == '.pdf':
            pdf_data = None
            pdf_raw = None

            embedded_text = _extract_pdf_text(file_path)
            if embedded_text and len(embedded_text) >= 20:
                print(f"[PDF] 提取到嵌入文本({len(embedded_text)}字符)，使用LLM结构化")
                pdf_data, pdf_raw = extract_from_ocr_text(embedded_text, ai_prompt)
                if 'error' in pdf_data:
                    print(f"[PDF] 嵌入文本结构化失败，尝试OCR")
                    pdf_data = None

            if pdf_data is None and HAS_TESSERACT:
                try:
                    ocr_text = local_ocr_pdf(file_path)
                    if ocr_text and len(ocr_text) >= 10:
                        print(f"[PDF] OCR识别成功({len(ocr_text)}字符)，使用LLM结构化")
                        pdf_data, pdf_raw = extract_from_ocr_text(ocr_text, ai_prompt)
                        if 'error' in pdf_data:
                            print(f"[PDF] OCR文本结构化失败，回退到多模态识别")
                            pdf_data = None
                except Exception as e:
                    print(f"[PDF] OCR处理失败: {e}")

            if pdf_data is None:
                print(f"[PDF] 使用多模态模型逐页识别")
                image_paths = pdf_to_images(file_path)
                for img_path in image_paths:
                    try:
                        data, raw_text = extract_medical_data_multimodal(img_path, ai_prompt)
                        if "error" in data:
                            errors.append(f"{filename}: {data['error']}")
                            continue
                        case_number = f"CASE_{datetime.now().strftime('%Y%m%d')}_{uuid.uuid4().hex[:6].upper()}"
                        record_id = str(uuid.uuid4())
                        create_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        confidence_data = data.pop('confidence', {})
                        conn = get_db()
                        c = conn.cursor()
                        c.execute('''INSERT INTO medical_records
                            (id, case_number, original_filename, role_id, template_id,
                             extracted_data, confidence_data, raw_text, create_time,
                             source_type, module_type, batch_id, user_id)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'image', ?, ?, ?)''',
                            (record_id, case_number, filename, role_id, template_id,
                             json.dumps(data, ensure_ascii=False),
                             json.dumps(confidence_data, ensure_ascii=False),
                             raw_text, create_time, module_type or 'image_ocr', batch_id, user_id))
                        conn.commit()
                        conn.close()
                        results.append({
                            "id": record_id, "case_number": case_number,
                            "filename": filename, "role_id": role_id,
                            "template_name": template_name, "display_layout": display_layout,
                            "source_type": "image", "module_type": module_type or "image_ocr",
                            "data": data, "confidence": confidence_data, "create_time": create_time
                        })
                    finally:
                        try:
                            if os.path.exists(img_path):
                                os.remove(img_path)
                        except Exception:
                            pass
                return results, errors

            data = pdf_data
            raw_text = pdf_raw
            if "error" in data:
                errors.append(f"{filename}: {data['error']}")
                return results, errors
        else:
            # 直接使用多模态识别（OCR无法识别勾选框等视觉元素）
            data, raw_text = extract_medical_data_multimodal(file_path, ai_prompt)
            if "error" in data:
                errors.append(f"{filename}: {data['error']}")
                return results, errors

        case_number = f"CASE_{datetime.now().strftime('%Y%m%d')}_{uuid.uuid4().hex[:6].upper()}"
        record_id = str(uuid.uuid4())
        create_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        confidence_data = data.pop('confidence', {})

        conn = get_db()
        c = conn.cursor()
        c.execute('''INSERT INTO medical_records
            (id, case_number, original_filename, role_id, template_id,
             extracted_data, confidence_data, raw_text, create_time,
             source_type, module_type, batch_id, user_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'image', ?, ?, ?)''',
            (record_id, case_number, filename, role_id, template_id,
             json.dumps(data, ensure_ascii=False),
             json.dumps(confidence_data, ensure_ascii=False),
             raw_text, create_time, module_type or 'image_ocr', batch_id, user_id))
        conn.commit()
        conn.close()

        results.append({
            "id": record_id, "case_number": case_number,
            "filename": filename, "role_id": role_id,
            "template_name": template_name, "display_layout": display_layout,
            "source_type": "image", "module_type": module_type or "image_ocr",
            "data": data, "confidence": confidence_data, "create_time": create_time
        })
    except Exception as e:
        errors.append(f"{filename}: 识别失败 - {str(e)}")

    return results, errors


def _process_text_content(text_content, role_id, template_id,
                          ai_prompt, template_name, display_layout,
                          filename='粘贴文本', batch_id=None, user_id=None):
    """处理文本内容：预处理 → 脱敏 → 结构化提取 → 存储
    返回 (result_dict_or_None, error_string_or_None)"""
    try:
        processed_text = _preprocess_text(text_content)
        if len(processed_text) < 5:
            return None, f"{filename}: 文本内容过短或为空"

        processed_text, _privacy_report = desensitize_text(processed_text)
        data, raw_text = extract_from_transcript(processed_text, ai_prompt)
        if "error" in data:
            return None, f"{filename}: {data.get('error', '文本提取失败')}"

        case_number = f"TEXT_{datetime.now().strftime('%Y%m%d')}_{uuid.uuid4().hex[:6].upper()}"
        record_id = str(uuid.uuid4())
        create_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        confidence_data = data.pop('confidence', {})

        conn = get_db()
        c = conn.cursor()
        c.execute('''INSERT INTO medical_records
            (id, case_number, original_filename, role_id, template_id,
             extracted_data, confidence_data, raw_text, create_time,
             source_type, module_type, text_source, batch_id, user_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'text', 'text_input', ?, ?, ?)''',
            (record_id, case_number, filename, role_id, template_id,
             json.dumps(data, ensure_ascii=False),
             json.dumps(confidence_data, ensure_ascii=False),
             raw_text, create_time, processed_text, batch_id, user_id))
        conn.commit()
        conn.close()

        return {
            "id": record_id, "case_number": case_number,
            "filename": filename, "role_id": role_id,
            "template_name": template_name, "display_layout": display_layout,
            "source_type": "text", "module_type": "text_input",
            "text_source": processed_text,
            "data": data, "confidence": confidence_data, "create_time": create_time
        }, None
    except Exception as e:
        return None, f"{filename}: {str(e)}"


@extraction_bp.route('/upload_text', methods=['POST'])
@login_required
def upload_text():
    """文本输入模块：处理粘贴文本或txt/docx文件上传"""
    role_id = request.form.get('role_id', 'general')
    template_id = request.form.get('template_id', 'tpl_researcher_default')
    text_content = request.form.get('text_content', '').strip()

    # 生成批次ID，用于统一导出
    batch_id = f"BATCH_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6].upper()}"
    user_id = get_current_user_id()

    # 查询模板
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT ai_prompt, template_name, display_layout FROM extraction_templates WHERE template_id=?",
              (template_id,))
    tpl_row = c.fetchone()
    conn.close()

    if not tpl_row:
        return jsonify({"status": "error", "msg": "模板不存在"})

    ai_prompt = tpl_row['ai_prompt']
    template_name = tpl_row['template_name']
    display_layout = tpl_row['display_layout']

    results = []
    errors = []

    # 模式1：直接粘贴文本
    if text_content:
        result, error = _process_text_content(
            text_content, role_id, template_id,
            ai_prompt, template_name, display_layout,
            filename='粘贴文本', batch_id=batch_id, user_id=get_current_user_id())
        if error:
            errors.append(error)
        if result:
            results.append(result)

    # 模式2：文件上传
    files = request.files.getlist('files')
    for file in files:
        if not file or file.filename == '':
            continue
        if not is_text_file(file.filename):
            errors.append(f"不支持的格式: {file.filename}")
            continue

        file_ext = os.path.splitext(file.filename)[1].lower()
        temp_name = f"{uuid.uuid4().hex}{file_ext}"
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], temp_name)
        file.save(file_path)

        try:
            raw_file_text = _parse_text_file(file_path)
            result, error = _process_text_content(
                raw_file_text, role_id, template_id,
                ai_prompt, template_name, display_layout,
                filename=file.filename, batch_id=batch_id, user_id=get_current_user_id())
            if error:
                errors.append(error)
            if result:
                results.append(result)
        except Exception as e:
            errors.append(f"{file.filename}: {str(e)}")
        finally:
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
            except Exception:
                pass

    if not results and not errors:
        return jsonify({"status": "error", "msg": "请输入文本或上传文件"})

    if results:
        log_audit('upload', 'record', batch_id, f"上传{len(results)}个文件，{len(errors)}个失败")

    return jsonify({
        "status": "success" if results else "error",
        "batch_id": batch_id,
        "results": results,
        "errors": errors,
        "msg": f"成功处理 {len(results)} 份" + (f"，{len(errors)} 份失败" if errors else "")
    })




@extraction_bp.route('/qualitative_analyze', methods=['POST'])
@login_required
def qualitative_analyze():
    """质性研究模块：独立的质性分析入口"""
    analysis_type = request.form.get('analysis_type', 'interview')
    user_id = get_current_user_id()
    text_content = request.form.get('text_content', '').strip()

    results = []
    errors = []
    transcript_text = ''
    source_filename = ''

    # 模式1：音频文件 → 转录 → 分析
    files = request.files.getlist('files')
    for file in files:
        if not file or file.filename == '':
            continue

        file_ext = os.path.splitext(file.filename)[1].lower()
        temp_name = f"{uuid.uuid4().hex}{file_ext}"
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], temp_name)
        file.save(file_path)

        try:
            if is_audio_file(file.filename):
                transcript_result = transcribe_audio(file_path)
                transcript_text = transcript_result['text']
                source_filename = file.filename
            elif is_text_file(file.filename):
                raw_text = _parse_text_file(file_path)
                transcript_text = _preprocess_text(raw_text)
                source_filename = file.filename
            else:
                errors.append(f"不支持的格式: {file.filename}，请上传音频或文本文件")
                continue

            if len(transcript_text) < 10:
                errors.append(f"{file.filename}: 内容过短，无法进行质性分析")
                continue

            # 脱敏：在发送远程LLM和存储之前，对转录文本进行敏感信息脱敏
            transcript_text, _privacy_report = desensitize_text(transcript_text)

            qual_result = qualitative_analysis_enhanced(transcript_text, analysis_type)

            case_number = f"QUAL_{datetime.now().strftime('%Y%m%d')}_{uuid.uuid4().hex[:6].upper()}"
            record_id = str(uuid.uuid4())
            create_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            conn = get_db()
            c = conn.cursor()
            c.execute('''INSERT INTO medical_records
                (id, case_number, original_filename, role_id, template_id,
                 extracted_data, raw_text, create_time,
                 source_type, module_type, audio_transcript, qualitative_data, analysis_type, user_id)
                VALUES (?, ?, ?, NULL, NULL, NULL, NULL, ?, ?, 'qualitative', ?, ?, ?, ?)''',
                (record_id, case_number, source_filename, create_time,
                 'audio' if is_audio_file(file.filename) else 'text',
                 transcript_text,
                 json.dumps(qual_result, ensure_ascii=False),
                 analysis_type, user_id))
            conn.commit()
            conn.close()

            results.append({
                "id": record_id,
                "case_number": case_number,
                "filename": source_filename,
                "source_type": "audio" if is_audio_file(file.filename) else "text",
                "module_type": "qualitative",
                "analysis_type": analysis_type,
                "transcript": transcript_text,
                "qualitative_analysis": qual_result,
                "create_time": create_time
            })
        except Exception as e:
            errors.append(f"{file.filename}: {str(e)}")
        finally:
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
            except Exception:
                pass

    # 模式2：直接粘贴文本
    if text_content and not results:
        try:
            processed_text = _preprocess_text(text_content)
            if len(processed_text) < 10:
                return jsonify({"status": "error", "msg": "文本内容过短，无法进行质性分析"})

            # 脱敏：在发送远程LLM和存储之前，对文本进行敏感信息脱敏
            processed_text, _privacy_report = desensitize_text(processed_text)

            qual_result = qualitative_analysis_enhanced(processed_text, analysis_type)

            case_number = f"QUAL_{datetime.now().strftime('%Y%m%d')}_{uuid.uuid4().hex[:6].upper()}"
            record_id = str(uuid.uuid4())
            create_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            conn = get_db()
            c = conn.cursor()
            c.execute('''INSERT INTO medical_records
                (id, case_number, original_filename, role_id, template_id,
                 extracted_data, raw_text, create_time,
                 source_type, module_type, audio_transcript, qualitative_data, analysis_type, user_id)
                VALUES (?, ?, ?, NULL, NULL, NULL, NULL, ?, 'text', 'qualitative', ?, ?, ?, ?)''',
                (record_id, case_number, '粘贴文本', create_time,
                 processed_text,
                 json.dumps(qual_result, ensure_ascii=False),
                 analysis_type, user_id))
            conn.commit()
            conn.close()

            results.append({
                "id": record_id,
                "case_number": case_number,
                "filename": "粘贴文本",
                "source_type": "text",
                "module_type": "qualitative",
                "analysis_type": analysis_type,
                "transcript": processed_text,
                "qualitative_analysis": qual_result,
                "create_time": create_time
            })
        except Exception as e:
            errors.append(f"质性分析失败: {str(e)}")

    if not results and not errors:
        return jsonify({"status": "error", "msg": "请上传文件或输入文本"})

    return jsonify({
        "status": "success" if results else "error",
        "results": results,
        "errors": errors,
        "msg": f"成功分析 {len(results)} 份" + (f"，{len(errors)} 份失败" if errors else "")
    })




# ========== 批量混合处理 ==========

@extraction_bp.route('/batch_process', methods=['POST'])
@login_required
def batch_process():
    """批量混合处理：同时支持图片、音频、文本文件的批量上传和统一识别"""
    batch_id = f"BATCH_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6].upper()}"
    user_id = get_current_user_id()
    role_id = request.form.get('role_id', 'general')
    template_id = request.form.get('template_id', 'tpl_researcher_default')
    text_content = request.form.get('text_content', '').strip()

    # 查询模板
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT ai_prompt, template_name, display_layout FROM extraction_templates WHERE template_id=?",
              (template_id,))
    tpl_row = c.fetchone()
    conn.close()

    if not tpl_row:
        return jsonify({"status": "error", "msg": "模板不存在"})

    ai_prompt = tpl_row['ai_prompt']
    template_name = tpl_row['template_name']
    display_layout = tpl_row['display_layout']

    results = []
    errors = []

    # 1. 处理上传的文件（图片/PDF/音频/文本文件）
    uploaded_files = request.files.getlist('files')
    for file in uploaded_files:
        if not file or file.filename == '':
            continue

        file_ext = os.path.splitext(file.filename)[1].lower()
        temp_name = f"{uuid.uuid4().hex}{file_ext}"
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], temp_name)
        file.save(file_path)

        try:
            if is_audio_file(file.filename):
                # 音频处理
                result = _process_audio_file(
                    file_path, file.filename, role_id, template_id,
                    ai_prompt, template_name, display_layout, batch_id=batch_id, user_id=get_current_user_id())
                if result.get('error'):
                    errors.append(f"{file.filename}: {result['error']}")
                else:
                    results.append(result)
            elif allowed_file(file.filename):
                # 图片/PDF处理
                img_results, img_errors = _process_image_file(
                    file_path, file.filename, role_id, template_id,
                    ai_prompt, template_name, display_layout,
                    module_type='image_ocr', batch_id=batch_id, user_id=get_current_user_id())
                results.extend(img_results)
                errors.extend(img_errors)
            elif is_text_file(file.filename):
                # 文本文件处理
                raw_file_text = _parse_text_file(file_path)
                result, error = _process_text_content(
                    raw_file_text, role_id, template_id,
                    ai_prompt, template_name, display_layout,
                    filename=file.filename, batch_id=batch_id, user_id=get_current_user_id())
                if error:
                    errors.append(error)
                if result:
                    results.append(result)
            else:
                errors.append(f"不支持的格式: {file.filename}")
        except Exception as e:
            errors.append(f"{file.filename}: 处理失败 - {str(e)}")
        finally:
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
            except Exception:
                pass

    # 2. 处理粘贴的文本内容
    if text_content:
        result, error = _process_text_content(
            text_content, role_id, template_id,
            ai_prompt, template_name, display_layout,
            filename='粘贴文本', batch_id=batch_id, user_id=get_current_user_id())
        if error:
            errors.append(error)
        if result:
            results.append(result)

    if not results and not errors:
        return jsonify({"status": "error", "msg": "请上传文件或输入文本"})

    if results:
        log_audit('upload', 'record', batch_id, f"上传{len(results)}个文件，{len(errors)}个失败")

    return jsonify({
        "status": "success" if results else "error",
        "batch_id": batch_id,
        "results": results,
        "errors": errors,
        "msg": f"批量处理完成：成功 {len(results)} 份" + (f"，失败 {len(errors)} 份" if errors else "")
    })


@extraction_bp.route('/batch_export/<batch_id>', methods=['GET'])
@login_required
def batch_export(batch_id):
    """导出指定批次的所有记录为统一Excel"""
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM medical_records WHERE batch_id=? AND user_id=? ORDER BY create_time', (batch_id, get_current_user_id()))
    rows = c.fetchall()
    conn.close()

    if not rows:
        return jsonify({"status": "error", "msg": "该批次无数据"})

    data_list = _rows_to_export_list(rows)
    excel_path = generate_unified_excel(data_list, batch_id)
    if not excel_path:
        return jsonify({"status": "error", "msg": "生成Excel失败"})

    return send_file(excel_path, as_attachment=True,
                     download_name=f"统一数据集_{batch_id}.xlsx")

