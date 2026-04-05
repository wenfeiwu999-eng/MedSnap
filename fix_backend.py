# -*- coding: utf-8 -*-
import sys, os

FILE = r'd:\HuaweiMoveData\Users\初\Desktop\我的黑客松\MedSnap\app.py'

with open(FILE, 'r', encoding='utf-8') as f:
    c = f.read()

orig_len = len(c)
changes = 0

# === Step 1: Add batch_id generation to /upload ===
anchor1 = "module_type = request.form.get('module_type', '')  # \u7531\u524d\u7aef\u6307\u5b9a\n\n    # \u67e5\u8be2\u6a21\u677fPrompt"
batch_line = '    batch_id = f"BATCH_{datetime.now().strftime(\'%Y%m%d_%H%M%S\')}_{uuid.uuid4().hex[:6].upper()}"\n\n'
if anchor1 in c:
    new1 = anchor1.replace(
        "\n\n    # \u67e5\u8be2\u6a21\u677fPrompt",
        "\n\n    # \u751f\u6210\u6279\u6b21ID\uff0c\u7528\u4e8e\u7edf\u4e00\u5bfc\u51fa\n" + batch_line + "    # \u67e5\u8be2\u6a21\u677fPrompt"
    )
    c = c.replace(anchor1, new1, 1)
    changes += 1
    print("[OK] 1. Added batch_id to /upload")
else:
    print("[SKIP] 1")

# === Step 2: Add batch_id to audio call in /upload ===
old_audio = "ai_prompt, template_name, display_layout)\n                if result_data.get('error'):"
# Make sure we target the one in upload_and_recognize
upload_start = c.find('def upload_and_recognize():')
batch_proc_start = c.find('def batch_process():')
if upload_start >= 0:
    idx = c.find(old_audio, upload_start)
    if idx >= 0 and (batch_proc_start < 0 or idx < batch_proc_start):
        new_audio = "ai_prompt, template_name, display_layout, batch_id=batch_id)\n                if result_data.get('error'):"
        c = c[:idx] + new_audio + c[idx + len(old_audio):]
        changes += 1
        print("[OK] 2. Added batch_id to audio call")
    else:
        print("[SKIP] 2. audio call not found in /upload")
else:
    print("[SKIP] 2. upload_and_recognize not found")

# === Step 3: Replace image/PDF inline code ===
img_marker = "# ========== \u56fe\u7247/PDF\u5904\u7406\u6d41\u7a0b\uff08\u672c\u5730OCR + \u8fdc\u7a0bAI\u589e\u5f3a\uff09 =========="
img_start = c.find(img_marker)
if img_start >= 0:
    else_start = c.rfind("\n            else:\n", 0, img_start)
    if else_start >= 0:
        else_start += 1  # skip leading newline
    except_marker = "\n        except Exception as e:\n            errors.append(f\"{file.filename}: \u8bc6\u522b\u5931\u8d25"
    except_idx = c.find(except_marker, img_start)
    if else_start >= 0 and except_idx >= 0:
        new_block = (
            "            else:\n"
            "                # ========== \u56fe\u7247/PDF\u5904\u7406\uff08\u8c03\u7528\u8f85\u52a9\u51fd\u6570\uff0c\u652f\u6301batch_id\uff09 ==========\n"
            "                img_results, img_errors = _process_image_file(\n"
            "                    file_path, file.filename, role_id, template_id,\n"
            "                    ai_prompt, template_name, display_layout,\n"
            "                    module_type=module_type or 'image_ocr', batch_id=batch_id)\n"
            "                results.extend(img_results)\n"
            "                errors.extend(img_errors)\n"
        )
        c = c[:else_start] + new_block + c[except_idx:]
        changes += 1
        print("[OK] 3. Replaced image/PDF inline code")
    else:
        print(f"[ERROR] 3. else_start={else_start}, except_idx={except_idx}")
else:
    print("[SKIP] 3. Image block not found")

# === Step 4: Add batch_id to /upload response JSON ===
ret_marker = '"msg": f"\u6210\u529f\u8bc6\u522b {len(results)} \u4efd"'
ret_idx = c.find(ret_marker)
if ret_idx >= 0:
    nearby = c[max(0, ret_idx-300):ret_idx]
    if '"batch_id": batch_id' not in nearby:
        res_line = '"results": results,\n'
        res_idx = c.rfind(res_line, 0, ret_idx)
        if res_idx >= 0:
            insert = '"batch_id": batch_id,\n        '
            c = c[:res_idx] + insert + c[res_idx:]
            changes += 1
            print("[OK] 4. Added batch_id to /upload response")
        else:
            print("[ERROR] 4. results line not found")
    else:
        print("[SKIP] 4. batch_id already in response")
else:
    print("[SKIP] 4. /upload return not found")

# === Step 5: Add batch_id generation to /upload_text ===
text_anchor = "text_content = request.form.get('text_content', '').strip()\n\n    # \u67e5\u8be2\u6a21\u677f"
if text_anchor in c:
    new5 = text_anchor.replace(
        "\n\n    # \u67e5\u8be2\u6a21\u677f",
        "\n\n    # \u751f\u6210\u6279\u6b21ID\uff0c\u7528\u4e8e\u7edf\u4e00\u5bfc\u51fa\n" + batch_line + "    # \u67e5\u8be2\u6a21\u677f"
    )
    c = c.replace(text_anchor, new5, 1)
    changes += 1
    print("[OK] 5. Added batch_id to /upload_text")
else:
    print("[SKIP] 5. /upload_text anchor not found")

# === Step 6: Replace paste text inline code ===
paste_start_marker = "# \u6a21\u5f0f1\uff1a\u76f4\u63a5\u7c98\u8d34\u6587\u672c\n    if text_content:\n        try:\n            processed_text = _preprocess_text(text_content)"
paste_end_marker = "errors.append(f\"\u6587\u672c\u5904\u7406\u5931\u8d25: {str(e)}\")\n\n    # \u6a21\u5f0f2\uff1a\u6587\u4ef6\u4e0a\u4f20"
ps_idx = c.find(paste_start_marker)
pe_idx = c.find(paste_end_marker)
if ps_idx >= 0 and pe_idx >= 0:
    pe_idx += len(paste_end_marker)
    new_paste = (
        "# \u6a21\u5f0f1\uff1a\u76f4\u63a5\u7c98\u8d34\u6587\u672c\n"
        "    if text_content:\n"
        "        result, error = _process_text_content(\n"
        "            text_content, role_id, template_id,\n"
        "            ai_prompt, template_name, display_layout,\n"
        "            filename='\u7c98\u8d34\u6587\u672c', batch_id=batch_id)\n"
        "        if error:\n"
        "            errors.append(error)\n"
        "        if result:\n"
        "            results.append(result)\n"
        "\n"
        "    # \u6a21\u5f0f2\uff1a\u6587\u4ef6\u4e0a\u4f20"
    )
    c = c[:ps_idx] + new_paste + c[pe_idx:]
    changes += 1
    print("[OK] 6. Replaced paste text inline code")
else:
    print(f"[SKIP] 6. paste_start={ps_idx}, paste_end={pe_idx}")

# === Step 7: Replace file upload loop inline code ===
file_body_start = "raw_file_text = _parse_text_file(file_path)\n            processed_text = _preprocess_text(raw_file_text)"
file_body_end_marker = "errors.append(f\"{file.filename}: {str(e)}\")\n        finally:"
fb_idx = c.find(file_body_start)
fbe_idx = c.find(file_body_end_marker, fb_idx if fb_idx >= 0 else 0)
if fb_idx >= 0 and fbe_idx >= 0:
    fbe_idx += len(file_body_end_marker)
    new_fb = (
        "raw_file_text = _parse_text_file(file_path)\n"
        "            result, error = _process_text_content(\n"
        "                raw_file_text, role_id, template_id,\n"
        "                ai_prompt, template_name, display_layout,\n"
        "                filename=file.filename, batch_id=batch_id)\n"
        "            if error:\n"
        "                errors.append(error)\n"
        "            if result:\n"
        "                results.append(result)\n"
        "        except Exception as e:\n"
        "            errors.append(f\"{file.filename}: {str(e)}\")\n"
        "        finally:"
    )
    c = c[:fb_idx] + new_fb + c[fbe_idx:]
    changes += 1
    print("[OK] 7. Replaced file loop inline code")
else:
    print(f"[SKIP] 7. file_body_start={fb_idx}, file_body_end={fbe_idx}")

# === Step 8: Add batch_id to /upload_text response ===
ret2_marker = '"msg": f"\u6210\u529f\u5904\u7406 {len(results)} \u4efd"'
ret2_idx = c.find(ret2_marker)
if ret2_idx >= 0:
    nearby2 = c[max(0, ret2_idx-300):ret2_idx]
    if '"batch_id": batch_id' not in nearby2:
        res_line2 = '"results": results,\n'
        res_idx2 = c.rfind(res_line2, 0, ret2_idx)
        if res_idx2 >= 0:
            insert2 = '"batch_id": batch_id,\n        '
            c = c[:res_idx2] + insert2 + c[res_idx2:]
            changes += 1
            print("[OK] 8. Added batch_id to /upload_text response")
        else:
            print("[ERROR] 8. results line not found")
    else:
        print("[SKIP] 8. already present")
else:
    print("[SKIP] 8. /upload_text return not found")

# === Write ===
if changes > 0:
    with open(FILE, 'w', encoding='utf-8') as f:
        f.write(c)
    print(f"\n[DONE] {changes} changes. Size: {orig_len} -> {len(c)}")
else:
    print("\n[WARN] No changes made")
