# -*- coding: utf-8 -*-
"""Template API routes Blueprint"""

import os, json, uuid, re
from datetime import datetime
from flask import Blueprint, request, jsonify
from config import get_db, DEPARTMENT_CONFIGS, LEGACY_ROLE_MAP, client, MODEL_NAME
from auth import login_required, get_current_user_id, log_audit
from services.ai_service import extract_medical_data, parse_ai_response
from prompts import *

template_bp = Blueprint("template", __name__)

@template_bp.route('/api/roles', methods=['GET'])
def api_get_roles():
    """获取科室列表（兼容旧接口名 /api/roles）"""
    conn = get_db()
    c = conn.cursor()
    roles = []
    for dept_id, cfg in DEPARTMENT_CONFIGS.items():
        c.execute("SELECT COUNT(*) as cnt FROM extraction_templates WHERE role_id=? AND is_active=1",
                  (dept_id,))
        count = c.fetchone()['cnt']
        roles.append({
            'role_id': dept_id,
            'name': cfg['name'],
            'color': cfg['color'],
            'template_count': count
        })
    conn.close()
    return jsonify({"status": "success", "roles": roles})


@template_bp.route('/api/departments', methods=['GET'])
def api_get_departments():
    """获取科室列表（新接口）"""
    conn = get_db()
    c = conn.cursor()
    departments = []
    for dept_id, cfg in DEPARTMENT_CONFIGS.items():
        c.execute("SELECT COUNT(*) as cnt FROM extraction_templates WHERE role_id=? AND is_active=1",
                  (dept_id,))
        count = c.fetchone()['cnt']
        departments.append({
            'dept_id': dept_id,
            'name': cfg['name'],
            'color': cfg['color'],
            'template_count': count
        })
    conn.close()
    return jsonify({"status": "success", "departments": departments})


@template_bp.route('/api/templates/<role_id>', methods=['GET'])
@login_required
def api_get_templates(role_id):
    """获取某科室下的模板列表"""
    conn = get_db()
    c = conn.cursor()
    c.execute('''SELECT template_id, template_name, template_type, display_layout, ai_prompt, create_time
        FROM extraction_templates WHERE role_id=? AND is_active=1 AND (template_type='fixed' OR user_id=?) ORDER BY template_type, create_time''',
              (role_id, get_current_user_id()))
    rows = c.fetchall()
    conn.close()
    templates = []
    for row in rows:
        fields = _extract_fields_from_prompt(row['ai_prompt']) if row['ai_prompt'] else []
        templates.append({
            'template_id': row['template_id'],
            'template_name': row['template_name'],
            'template_type': row['template_type'],
            'display_layout': row['display_layout'],
            'field_count': len(fields),
        })
    return jsonify({"status": "success", "templates": templates})


@template_bp.route('/api/detect_department', methods=['POST'])
@login_required
def api_detect_department():
    """AI自动检测医疗文本所属科室"""
    data = request.get_json()
    text = (data or {}).get('text', '').strip()
    if not text:
        return jsonify({"status": "error", "msg": "请提供待检测的医疗文本"})

    # 截取前2000字符送检以节省token
    sample = text[:2000]
    try:
        combined_prompt = PROMPT_DETECT_DEPARTMENT + "\n\n" + sample
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[{'role': 'user', 'content': combined_prompt}],
            temperature=0.1,
            max_tokens=512
        )
        raw = response.choices[0].message.content
        parsed = parse_ai_response(raw)
        if isinstance(parsed, dict) and 'error' not in parsed:
            dept = parsed.get('department', 'general')
            # 校验科室ID有效性
            if dept not in DEPARTMENT_CONFIGS:
                dept = 'general'
            return jsonify({
                "status": "success",
                "department": dept,
                "confidence": parsed.get('confidence', 0),
                "reasoning": parsed.get('reasoning', ''),
                "sub_type": parsed.get('sub_type', 'clinical')
            })
        else:
            return jsonify({"status": "success", "department": "general",
                            "confidence": 0, "reasoning": "无法识别", "sub_type": "clinical"})
    except Exception as e:
        return jsonify({"status": "error", "msg": f"科室检测失败: {str(e)}",
                        "department": "general", "confidence": 0})


def _generate_template_prompt(role_id, fields, include_score=False, sub_type=None):
    """根据科室/角色和字段列表生成AI提取Prompt和display_layout。
    role_id 可以是新科室ID (cardiology等) 或旧角色ID (diagnosis/nursing/other)。
    sub_type 可选：'clinical'/'nursing'/'other'，用于科室模板。
    """
    field_schema_parts = []
    for f in fields:
        f = f.strip()
        if f:
            field_schema_parts.append(f'    "{f}": null')
    field_schema = ',\n'.join(field_schema_parts)
    field_names = '、'.join([f.strip() for f in fields if f.strip()])

    score_rule = ""
    if include_score:
        score_rule = "3. 如果字段是评分项，提取纯数字评分。如有总分，一并计算。\n"

    # 将旧角色ID映射为等效逻辑
    effective_role = LEGACY_ROLE_MAP.get(role_id, role_id)

    # 对于6大临床科室，根据 sub_type 选择模板风格
    if effective_role in DEPARTMENT_PROMPTS:
        dept_name = DEPARTMENT_CONFIGS.get(effective_role, {}).get('name', '临床')
        if sub_type == 'nursing':
            ai_prompt = NURSE_CUSTOM_PROMPT_TEMPLATE.format(
                field_schema=field_schema, field_names=field_names, score_rule=score_rule)
            display_layout = 'scale' if include_score else 'card'
        elif sub_type == 'other':
            ai_prompt = RESEARCHER_CUSTOM_PROMPT_TEMPLATE.format(
                field_schema=field_schema, field_names=field_names)
            display_layout = 'table'
        else:
            # clinical 或默认
            ai_prompt = DOCTOR_CUSTOM_PROMPT_TEMPLATE.format(
                field_schema=field_schema, field_names=field_names)
            display_layout = 'table'
    elif effective_role == 'general' or role_id == 'diagnosis':
        # 通用科室 / 旧诊疗角色 → 医生模板风格
        if sub_type == 'nursing' or role_id == 'nursing':
            ai_prompt = NURSE_CUSTOM_PROMPT_TEMPLATE.format(
                field_schema=field_schema, field_names=field_names, score_rule=score_rule)
            display_layout = 'scale' if include_score else 'card'
        elif sub_type == 'other' or role_id == 'other':
            ai_prompt = RESEARCHER_CUSTOM_PROMPT_TEMPLATE.format(
                field_schema=field_schema, field_names=field_names)
            display_layout = 'table'
        else:
            ai_prompt = DOCTOR_CUSTOM_PROMPT_TEMPLATE.format(
                field_schema=field_schema, field_names=field_names)
            display_layout = 'table'
    else:
        # 未知 role_id 兜底：护理风格
        ai_prompt = NURSE_CUSTOM_PROMPT_TEMPLATE.format(
            field_schema=field_schema, field_names=field_names, score_rule=score_rule)
        display_layout = 'scale' if include_score else 'card'

    return ai_prompt, display_layout


def _extract_fields_from_prompt(ai_prompt):
    """从ai_prompt中反向提取自定义字段列表"""
    fields = []
    matches = re.findall(r'"custom_fields"\s*:\s*\{([^}]+)\}', ai_prompt, re.DOTALL)
    if matches:
        field_matches = re.findall(r'"([^"]+)"\s*:\s*null', matches[0])
        fields = [f.strip() for f in field_matches if f.strip()]
    return fields


# 系统模板的中文字段名映射
TEMPLATE_FIELDS = {
    # ===== 通用（旧12模板）=====
    'tpl_doctor_medical': ['主诉', '现病史', '既往史', '个人史', '家族史', '过敏史', '体格检查', '专科检查', '辅助检查', '诊断', '诊疗计划', '处理意见'],
    'tpl_doctor_lab': ['项目名称', '结果', '参考值', '单位', '异常提示', '标本类型', '采集时间', '报告时间'],
    'tpl_nurse_admission': ['一般资料', '过敏史', '既往史', '用药史', '生命体征', '意识状态', '皮肤黏膜', '营养状况', '排泄', '活动能力', '跌倒风险', '压疮风险', '疼痛评分', '吞咽功能', '心理状态', '睡眠', '饮食', '专科情况', '护理问题', '护理措施'],
    'tpl_nurse_barthel': ['进食', '洗澡', '修饰', '穿衣', '控制大便', '控制小便', '如厕', '床椅转移', '平地行走', '上下楼梯'],
    'tpl_nurse_morse': ['跌倒史', '继发诊断', '步行辅助', '静脉输液/肝素锁', '步态', '认知状态'],
    'tpl_nurse_braden': ['感知能力', '潮湿程度', '活动能力', '移动能力', '营养摄取', '摩擦力和剪切力'],
    'tpl_nurse_pain': ['疼痛部位', '疼痛性质', '疼痛强度', '诱发因素', '缓解因素', '伴随症状', '疼痛持续时间'],
    'tpl_nurse_record': ['生命体征', '意识状态', '皮肤完整性', '跌倒风险', '压疮风险', '护理措施'],
    'tpl_researcher_default': ['人口学特征', '实验室检查', '主要终点事件', '随访日期', '血压', '血脂', '用药情况', '治疗结局'],
    'tpl_audio_doctor': ['主诉', '现病史', '诊断', '治疗方案'],
    'tpl_audio_nurse': ['生命体征', '护理观察', '风险提醒'],
    'tpl_audio_researcher': ['人口学特征', '病史', '干预措施', '结局指标'],
    # ===== 心内科 =====
    'tpl_cardiology_clinical': ['主诉', '现病史', '既往史', 'EF值', 'BNP_NT_proBNP', '冠脉造影结果', '心律失常类型', '心功能分级_NYHA', '血压_收缩压_舒张压', '心率', '血脂_LDL_HDL_TG_TC', '肌钙蛋白', '用药方案', 'PCI_CABG记录', '诊断', '治疗计划'],
    'tpl_cardiology_nursing': ['心电监护', '生命体征_体温_脉搏_呼吸_血压', '胸痛评估', '出入量记录', '活动耐量评估', '抗凝药物管理', '跌倒风险评估', '心理状态', '饮食护理', '心脏康复指导', '护理问题', '护理措施'],
    'tpl_cardiology_other': ['人口学特征', 'LVEF', 'BNP', 'LDL_C', '支架类型', '再狭窄', 'MACE事件', '随访日期', '用药情况', '治疗结局'],
    'tpl_cardiology_audio': ['主诉', '症状描述', '心电图提及', 'EF值', 'BNP', '用药方案', '诊断', '医嘱'],
    # ===== 神经内科 =====
    'tpl_neurology_clinical': ['主诉', '现病史', '既往史', 'GCS评分', 'NIHSS评分', '肌力分级', '感觉障碍', '反射检查', '头颅CT_MRI', '脑电图', '腰穿结果', '病灶定位', '发病时间', '溶栓_取栓记录', '诊断', '治疗方案'],
    'tpl_neurology_nursing': ['意识状态_GCS', '瞳孔变化', '肌力评估', '吞咽功能筛查', '跌倒风险', '深静脉血栓预防', '语言功能评估', '康复训练', '颅内压监测', '护理问题', '护理措施'],
    'tpl_neurology_other': ['人口学特征', '卒中类型', 'NIHSS评分', '发病至治疗时间', 'mRS评分', '影像学结果', '再灌注治疗', '并发症', '随访日期', '治疗结局'],
    'tpl_neurology_audio': ['主诉', '症状描述', '意识状态', '肢体活动', '影像学提及', '诊断', '医嘱'],
    # ===== 外科 =====
    'tpl_surgery_clinical': ['主诉', '现病史', '既往史', '手术名称', 'ASA分级', '麻醉方式', '术中出血量', '手术时长', '引流管', '术后并发症', '病理结果', '切口情况', '诊断', '手术记录'],
    'tpl_surgery_nursing': ['术前准备', '手术核查', '术后生命体征', '引流管护理', '切口换药', '疼痛评估', 'DVT预防', '早期活动', '营养支持', '术后并发症观察', '护理问题', '护理措施'],
    'tpl_surgery_other': ['人口学特征', '手术方式', '手术时长', '术中出血量', '并发症', '住院天数', '切口愈合等级', '病理分期', '随访日期', '治疗结局'],
    'tpl_surgery_audio': ['主诉', '症状描述', '手术方案', '麻醉方式', '术后情况', '诊断', '医嘱'],
    # ===== 儿科 =====
    'tpl_pediatrics_clinical': ['主诉', '现病史', '既往史', '出生体重', '胎龄', '体重_身高百分位', '疫苗接种', '喂养方式', '发育评估', '过敏史', '家族史', '专科检查', '诊断', '治疗方案'],
    'tpl_pediatrics_nursing': ['体温管理', '喂养评估', '体重监测', '黄疸评估', '疼痛评估_FLACC', '用药核查_体重剂量', '家长健康教育', '隔离防护', '护理问题', '护理措施'],
    'tpl_pediatrics_other': ['人口学特征', '胎龄', '出生体重', '生长发育指标', '疫苗接种', '过敏', '主要诊断', '治疗方案', '随访日期', '治疗结局'],
    'tpl_pediatrics_audio': ['主诉', '症状描述', '体温', '喂养情况', '发育情况', '诊断', '医嘱'],
    # ===== 妇产科 =====
    'tpl_obstetrics_clinical': ['主诉', '现病史', '既往史', '孕周', 'GPAL', '胎心率', '宫高_腹围', '羊水指数', '胎位', '妊娠并发症', '分娩方式', 'Apgar评分', '产后出血量', '新生儿体重', '诊断', '治疗方案'],
    'tpl_obstetrics_nursing': ['产前监护', '胎心监测', '宫缩评估', '产后出血观察', '母乳喂养指导', '切口_会阴护理', '子宫复旧', '新生儿护理', '心理支持', '护理问题', '护理措施'],
    'tpl_obstetrics_other': ['人口学特征', '孕周', '分娩方式', '妊娠并发症', '新生儿结局', 'Apgar评分', '产后出血量', '住院天数', '随访日期', '治疗结局'],
    'tpl_obstetrics_audio': ['主诉', '症状描述', '孕周', '胎动情况', '产检结果', '诊断', '医嘱'],
    # ===== 急诊科 =====
    'tpl_emergency_clinical': ['主诉', '现病史', '既往史', '分诊级别', 'MEWS_NEWS评分', '发病至就诊时间', '生命体征', '意识状态_GCS', '急救措施', '检查结果', '会诊情况', '处置结果', '转归', '诊断'],
    'tpl_emergency_nursing': ['分诊评估', '生命体征', '意识状态', '疼痛评估', '急救配合', '静脉通路', '用药记录', '标本采集', '转运交接', '护理问题', '护理措施'],
    'tpl_emergency_other': ['人口学特征', '就诊时间', '分诊级别', '主要诊断', '急救措施', '检查项目', '抢救结局', '滞留时间', '随访日期', '治疗结局'],
    'tpl_emergency_audio': ['主诉', '症状描述', '发病时间', '急救措施', '意识状态', '诊断', '医嘱'],
    # ===== ICCAS =====
    'tpl_iccas_questionnaire': ['Consent','Demographics','Pre_ICCAS_01','Pre_ICCAS_20','Post_ICCAS_01','Post_ICCAS_21'],
}


@template_bp.route('/api/templates/<template_id>/detail', methods=['GET'])
@login_required
def api_get_template_detail(template_id):
    """获取模板完整信息用于编辑"""
    conn = get_db()
    c = conn.cursor()
    c.execute('''SELECT template_id, role_id, template_name, template_type,
        ai_prompt, display_layout, create_time
        FROM extraction_templates WHERE template_id=? AND (template_type='fixed' OR user_id=?)''', (template_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        return jsonify({"status": "error", "msg": "模板不存在"})

    # For system templates, try extracting from updated prompt first (user may have edited fields),
    # then fall back to TEMPLATE_FIELDS defaults
    fields = []
    if row['ai_prompt']:
        fields = _extract_fields_from_prompt(row['ai_prompt'])
    if not fields:
        fields = TEMPLATE_FIELDS.get(row['template_id'], [])
    include_score = row['display_layout'] == 'scale'

    return jsonify({
        "status": "success",
        "template": {
            "template_id": row['template_id'],
            "role_id": row['role_id'],
            "template_name": row['template_name'],
            "template_type": row['template_type'],
            "display_layout": row['display_layout'],
            "fields": fields,
            "include_score": include_score,
            "create_time": row['create_time']
        }
    })


@template_bp.route('/api/templates', methods=['POST'])
@login_required
def api_create_template():
    """创建自定义模板"""
    data = request.get_json()
    if not data:
        return jsonify({"status": "error", "msg": "无数据"})

    role_id = data.get('role_id', 'general')
    template_name = data.get('template_name', '').strip()
    fields = data.get('fields', [])
    include_score = data.get('include_score', False)
    sub_type = data.get('sub_type', None)

    if not template_name or not fields:
        return jsonify({"status": "error", "msg": "请填写模板名称和提取字段"})

    ai_prompt, display_layout = _generate_template_prompt(role_id, fields, include_score, sub_type=sub_type)

    template_id = f"tpl_custom_{uuid.uuid4().hex[:8]}"
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    conn = get_db()
    c = conn.cursor()
    c.execute('''INSERT INTO extraction_templates
        (template_id, role_id, template_name, template_type, ai_prompt, display_layout, is_active, create_time, user_id)
        VALUES (?, ?, ?, 'custom', ?, ?, 1, ?, ?)''',
              (template_id, role_id, template_name, ai_prompt, display_layout, now, get_current_user_id()))
    conn.commit()
    conn.close()

    log_audit("create", "template", template_id, template_name)
    return jsonify({"status": "success", "template_id": template_id, "msg": "模板创建成功"})


@template_bp.route('/api/templates/<template_id>', methods=['DELETE'])
@login_required
def api_delete_template(template_id):
    """删除自定义模板"""
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT template_type FROM extraction_templates WHERE template_id=? AND user_id=?", (template_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return jsonify({"status": "error", "msg": "模板不存在"})
    if row['template_type'] == 'fixed':
        conn.close()
        return jsonify({"status": "error", "msg": "系统内置模板不可删除"})

    c.execute("DELETE FROM extraction_templates WHERE template_id=?", (template_id, get_current_user_id()))
    conn.commit()
    conn.close()
    log_audit("delete", "template", template_id)
    return jsonify({"status": "success", "msg": "模板已删除"})


@template_bp.route('/api/templates/<template_id>', methods=['PUT'])
@login_required
def api_update_template(template_id):
    """编辑自定义模板"""
    data = request.get_json()
    if not data:
        return jsonify({"status": "error", "msg": "无数据"})

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT template_type, role_id FROM extraction_templates WHERE template_id=? AND user_id=?", (template_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return jsonify({"status": "error", "msg": "模板不存在"})

    role_id = row['role_id']
    template_name = data.get('template_name', '').strip()
    fields = data.get('fields', [])
    include_score = data.get('include_score', False)
    sub_type = data.get('sub_type', None)

    # For system templates, keep original name if not provided
    if not template_name and row['template_type'] == 'fixed':
        c.execute("SELECT template_name FROM extraction_templates WHERE template_id=?", (template_id,))
        name_row = c.fetchone()
        template_name = name_row['template_name'] if name_row else ''

    if not template_name or not fields:
        conn.close()
        return jsonify({"status": "error", "msg": "请填写模板名称和提取字段"})

    ai_prompt, display_layout = _generate_template_prompt(role_id, fields, include_score, sub_type=sub_type)

    c.execute('''UPDATE extraction_templates
        SET template_name=?, ai_prompt=?, display_layout=?
        WHERE template_id=?''',
              (template_name, ai_prompt, display_layout, template_id))
    conn.commit()
    conn.close()

    # Update in-memory fields cache
    TEMPLATE_FIELDS[template_id] = fields

    log_audit("update", "template", template_id, template_name)
    return jsonify({"status": "success", "msg": "模板已更新"})


# ========== 字段预览与自定义提取 ==========

# ========== 模板文件分析 ==========

@template_bp.route('/api/analyze_template_file', methods=['POST'])
@login_required
def api_analyze_template_file():
    """分析上传的模板文件（空白问卷/量表），识别字段结构"""
    from config import app, allowed_file
    from desensitizer import desensitize_text

    text_content = request.form.get("text_content", "").strip()
    description = request.form.get("description", "").strip()

    # Mode 1: File upload (image/PDF)
    if "files" in request.files:
        file = request.files["files"]
        if not file or not file.filename:
            return jsonify({"status": "error", "msg": "未选择文件"})

        filename = file.filename.lower()
        if not allowed_file(filename) and not filename.endswith('.pdf'):
            return jsonify({"status": "error", "msg": "不支持的文件格式"})

        file_ext = os.path.splitext(filename)[1]
        temp_name = str(uuid.uuid4().hex) + file_ext
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], temp_name)
        file.save(file_path)

        try:
            prompt = PROMPT_TEMPLATE_ANALYSIS
            if description:
                prompt = prompt + chr(10) + chr(10) + "补充说明: " + description

            parsed, raw_text = extract_medical_data(file_path, prompt)

            if not parsed or 'error' in parsed:
                err_msg = parsed.get('error', 'AI分析失败') if parsed else 'AI分析失败'
                return jsonify({"status": "error", "msg": err_msg})

            fields = parsed.get('available_fields', [])
            template_info = parsed.get('template_info', {})

            fields = [fld for fld in fields if fld.get('confidence', 0) >= 0.4]

            cat_order = ['基本信息', '检验结果', '诊疗记录', '护理评估', '量表评分', '问卷项目', '其他']
            fields.sort(key=lambda x: (cat_order.index(x.get('category', '其他')) if x.get('category', '其他') in cat_order else 99))

            fn = file.filename
            log_audit('analyze_template', 'template', None, '分析模板文件: ' + fn)
            return jsonify({
                "status": "success",
                "fields": fields,
                "template_info": template_info,
                "raw_data": parsed
            })
        except Exception as e:
            return jsonify({"status": "error", "msg": "分析失败: " + str(e)})
        finally:
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
            except Exception:
                pass

    # Mode 2: Text description
    elif text_content:
        if len(text_content) < 10:
            return jsonify({"status": "error", "msg": "文本内容过短"})

        try:
            masked = desensitize_text(text_content)
            prompt = PROMPT_TEMPLATE_ANALYSIS_TEXT.format(text_content=masked)

            resp = client.chat.completions.create(
                model=MODEL_NAME,
                messages=[{'role': 'user', 'content': prompt}],
                temperature=0.1,
                max_tokens=16384
            )
            raw_text = resp.choices[0].message.content
            parsed = parse_ai_response(raw_text)

            if not parsed or 'error' in parsed:
                err_msg = parsed.get('error', 'AI分析失败') if parsed else 'AI分析失败'
                return jsonify({"status": "error", "msg": err_msg})

            fields = parsed.get('available_fields', [])
            template_info = parsed.get('template_info', {})
            fields = [fld for fld in fields if fld.get('confidence', 0) >= 0.4]

            cat_order = ['基本信息', '检验结果', '诊疗记录', '护理评估', '量表评分', '问卷项目', '其他']
            fields.sort(key=lambda x: (cat_order.index(x.get('category', '其他')) if x.get('category', '其他') in cat_order else 99))

            log_audit('analyze_template', 'template', None, '分析模板文本描述')
            return jsonify({
                "status": "success",
                "fields": fields,
                "template_info": template_info,
                "raw_data": parsed
            })
        except Exception as e:
            return jsonify({"status": "error", "msg": "分析失败: " + str(e)})

    else:
        return jsonify({"status": "error", "msg": "请上传模板文件或输入文本描述"})
