#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""修改 /upload 和 /upload_text 路由，添加 batch_id 支持"""

import re

FILE = r'd:\HuaweiMoveData\Users\初\Desktop\我的黑客松\MedSnap\app.py'

with open(FILE, 'r', encoding='utf-8') as f:
    content = f.read()

original = content  # backup

# ============================================================
# 1. 在 /upload 路由中添加 batch_id 生成
# ============================================================
old_upload_header = """    module_type = request.form.get('module_type', '')  # 由前端指定

    # 查询模板Prompt"""

new_upload_header = """    module_type = request.form.get('module_type', '')  # 由前端指定

    # 生成批次ID，用于统一导出
    batch_id = f"BATCH_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6].upper()}"

    # 查询模板Prompt"""

if old_upload_header in content:
    content = content.replace(old_upload_header, new_upload_header, 1)
    print("[OK] 1. Added batch_id generation to /upload route")
else:
    print("[SKIP] 1. batch_id generation - pattern not found or already added")

# ============================================================
# 2. 在 /upload 路由的音频处理中添加 batch_id 参数
# ============================================================
# Find the audio call in upload_and_recognize (NOT in batch_process)
# The one in upload_and_recognize does NOT have batch_id=batch_id
old_audio = """                result_data = _process_audio_file(
                    file_path, file.filename, role_id, template_id,
                    ai_prompt, template_name, display_layout)
                if result_data.get('error'):"""

new_audio = """                result_data = _process_audio_file(
                    file_path, file.filename, role_id, template_id,
                    ai_prompt, template_name, display_layout, batch_id=batch_id)
                if result_data.get('error'):"""

if old_audio in content:
    content = content.replace(old_audio, new_audio, 1)
    print("[OK] 2. Added batch_id to audio call in /upload route")
else:
    print("[SKIP] 2. Audio batch_id - pattern not found or already added")

# ============================================================
# 3. 替换 /upload 路由中的图片/PDF内联处理为辅助函数调用
# ============================================================
# Find the exact block to replace: from "else:" (image/PDF branch) to the end of the results.append block
# This is inside the for loop, under "if is_audio: ... else:"

old_image_block = """            else:
                # ========== 图片/PDF处理流程（本地OCR + 远程AI增强） ==========
                if file_ext == '.pdf':"""

# We need to find this and replace everything until the except block
# Let's find the start index
start_idx = content.find(old_image_block)
if start_idx == -1:
    print("[SKIP] 3. Image/PDF block - pattern not found or already replaced")
else:
    # Find the except block that follows
    # The except block is at the same indentation level as the try block
    # Pattern: "\n        except Exception as e:\n"
    except_pattern = "\n        except Exception as e:\n            errors.append(f\"{file.filename}: 识别失败"
    end_idx = content.find(except_pattern, start_idx)
    
    if end_idx == -1:
        print("[ERROR] 3. Could not find the except block after image processing")
    else:
        new_image_block = """            else:
                # ========== 图片/PDF处理（调用辅助函数，支持batch_id） ==========
                img_results, img_errors = _process_image_file(
                    file_path, file.filename, role_id, template_id,
                    ai_prompt, template_name, display_layout,
                    module_type=module_type or 'image_ocr', batch_id=batch_id)
                results.extend(img_results)
                errors.extend(img_errors)
"""
        content = content[:start_idx] + new_image_block + content[end_idx:]
        print("[OK] 3. Replaced image/PDF inline code with _process_image_file() call")

# ============================================================
# 4. 在 /upload 路由的响应 JSON 中添加 batch_id
# ============================================================
# Find the return jsonify in upload_and_recognize
# It should be the first occurrence after the route definition
old_return = '''    return jsonify({
        "status": "success" if results else "error",
        "results": results,
        "errors": errors,
        "msg": f"成功识别 {len(results)} 份" + (f"，{len(errors)} 份失败" if errors else "")
    })


def _process_audio_file'''

new_return = '''    return jsonify({
        "status": "success" if results else "error",
        "batch_id": batch_id,
        "results": results,
        "errors": errors,
        "msg": f"成功识别 {len(results)} 份" + (f"，{len(errors)} 份失败" if errors else "")
    })


def _process_audio_file'''

if old_return in content:
    content = content.replace(old_return, new_return, 1)
    print("[OK] 4. Added batch_id to /upload response JSON")
else:
    print("[SKIP] 4. /upload response JSON - pattern not found or already added")

# ============================================================
# 5. 在 /upload_text 路由中添加 batch_id 生成
# ============================================================
old_text_header = """    text_content = request.form.get('text_content', '').strip()

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
        try:
            processed_text = _preprocess_text(text_content)"""

new_text_header = """    text_content = request.form.get('text_content', '').strip()

    # 生成批次ID，用于统一导出
    batch_id = f"BATCH_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6].upper()}"

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
            filename='粘贴文本', batch_id=batch_id)
        if error:
            errors.append(error)
        if result:
            results.append(result)
        elif not error:
            pass  # 无结果也无错误，继续处理文件"""

if old_text_header in content:
    content = content.replace(old_text_header, new_text_header, 1)
    print("[OK] 5. Added batch_id to /upload_text + replaced paste text inline code")
else:
    print("[SKIP] 5. /upload_text header - pattern not found")

# ============================================================
# 6. 删除 /upload_text 的旧粘贴文本处理代码 (从 if len... 到 except)
# ============================================================
# After step 5, the old inline paste processing code should have been removed
# by the replacement. But there's still remaining code from the old try block.
# Let's find and remove it.

# The old code after "if text_content: try: processed_text = ..." continues until the file upload section
# After our replacement, this old code should be gone since we replaced the whole block starting from 
# "# 模式1：直接粘贴文本\n    if text_content:\n        try:\n            processed_text"

# Check if old inline code still exists
old_paste_inline = """            if len(processed_text) < 5:
                return jsonify({"status": "error", "msg": "文本内容过短，请输入更多内容"})

            # 脱敏：在发送远程LLM之前，对文本进行敏感信息脱敏
            processed_text, _privacy_report = desensitize_text(processed_text)

            data, raw_text = extract_from_transcript(processed_text, ai_prompt)
            if "error" in data:
                return jsonify({"status": "error", "msg": data.get('error', '文本提取失败')})

            case_number = f"TEXT_{datetime.now().strftime('%Y%m%d')}_{uuid.uuid4().hex[:6].upper()}"
            record_id = str(uuid.uuid4())
            create_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            confidence_data = data.pop('confidence', {})

            conn = get_db()
            c = conn.cursor()
            c.execute(\'\'\'INSERT INTO medical_records
                (id, case_number, original_filename, role_id, template_id,
                 extracted_data, confidence_data, raw_text, create_time,
                 source_type, module_type, text_source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'text', 'text_input', ?)\'\'\',
                (record_id, case_number, '粘贴文本', role_id, template_id,
                 json.dumps(data, ensure_ascii=False),
                 json.dumps(confidence_data, ensure_ascii=False),
                 raw_text, create_time, processed_text))
            conn.commit()
            conn.close()

            results.append({
                "id": record_id,
                "case_number": case_number,
                "filename": "粘贴文本",
                "role_id": role_id,
                "template_name": template_name,
                "display_layout": display_layout,
                "source_type": "text",
                "module_type": "text_input",
                "text_source": processed_text,
                "data": data,
                "confidence": confidence_data,
                "create_time": create_time
            })
        except Exception as e:
            errors.append(f"文本处理失败: {str(e)}")

    # 模式2：文件上传"""

if old_paste_inline in content:
    content = content.replace(old_paste_inline, """
    # 模式2：文件上传""", 1)
    print("[OK] 6. Removed old paste text inline code")
else:
    print("[SKIP] 6. Old paste inline code already removed or not found")

# ============================================================
# 7. 替换 /upload_text 文件上传循环的内联处理
# ============================================================
old_file_loop_body = """        try:
            raw_file_text = _parse_text_file(file_path)
            processed_text = _preprocess_text(raw_file_text)
            if len(processed_text) < 5:
                errors.append(f"{file.filename}: 文件内容过短或为空")
                continue

            # 脱敏：在发送远程LLM之前，对文本进行敏感信息脱敏
            processed_text, _privacy_report = desensitize_text(processed_text)

            data, raw_text = extract_from_transcript(processed_text, ai_prompt)
            if "error" in data:
                errors.append(f"{file.filename}: {data.get('error', '提取失败')}")
                continue

            case_number = f"TEXT_{datetime.now().strftime('%Y%m%d')}_{uuid.uuid4().hex[:6].upper()}"
            record_id = str(uuid.uuid4())
            create_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            confidence_data = data.pop('confidence', {})

            conn = get_db()
            c = conn.cursor()
            c.execute(\'\'\'INSERT INTO medical_records
                (id, case_number, original_filename, role_id, template_id,
                 extracted_data, confidence_data, raw_text, create_time,
                 source_type, module_type, text_source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'text', 'text_input', ?)\'\'\',
                (record_id, case_number, file.filename, role_id, template_id,
                 json.dumps(data, ensure_ascii=False),
                 json.dumps(confidence_data, ensure_ascii=False),
                 raw_text, create_time, processed_text))
            conn.commit()
            conn.close()

            results.append({
                "id": record_id,
                "case_number": case_number,
                "filename": file.filename,
                "role_id": role_id,
                "template_name": template_name,
                "display_layout": display_layout,
                "source_type": "text",
                "module_type": "text_input",
                "text_source": processed_text,
                "data": data,
                "confidence": confidence_data,
                "create_time": create_time
            })
        except Exception as e:
            errors.append(f"{file.filename}: {str(e)}")
        finally:"""

new_file_loop_body = """        try:
            raw_file_text = _parse_text_file(file_path)
            result, error = _process_text_content(
                raw_file_text, role_id, template_id,
                ai_prompt, template_name, display_layout,
                filename=file.filename, batch_id=batch_id)
            if error:
                errors.append(error)
            if result:
                results.append(result)
        except Exception as e:
            errors.append(f"{file.filename}: {str(e)}")
        finally:"""

if old_file_loop_body in content:
    content = content.replace(old_file_loop_body, new_file_loop_body, 1)
    print("[OK] 7. Replaced /upload_text file loop with _process_text_content() call")
else:
    print("[SKIP] 7. /upload_text file loop - pattern not found")

# ============================================================
# 8. 在 /upload_text 路由的响应 JSON 中添加 batch_id
# ============================================================
old_text_return = '''    return jsonify({
        "status": "success" if results else "error",
        "results": results,
        "errors": errors,
        "msg": f"成功处理 {len(results)} 份" + (f"，{len(errors)} 份失败" if errors else "")
    })


@app.route('/qualitative_analyze'''

new_text_return = '''    return jsonify({
        "status": "success" if results else "error",
        "batch_id": batch_id,
        "results": results,
        "errors": errors,
        "msg": f"成功处理 {len(results)} 份" + (f"，{len(errors)} 份失败" if errors else "")
    })


@app.route('/qualitative_analyze'''

if old_text_return in content:
    content = content.replace(old_text_return, new_text_return, 1)
    print("[OK] 8. Added batch_id to /upload_text response JSON")
else:
    print("[SKIP] 8. /upload_text response JSON - pattern not found")

# ============================================================
# Write the modified file
# ============================================================
if content != original:
    with open(FILE, 'w', encoding='utf-8') as f:
        f.write(content)
    print("\n[DONE] File written successfully")
    print(f"Original size: {len(original)}, New size: {len(content)}")
else:
    print("\n[WARN] No changes made to file")
