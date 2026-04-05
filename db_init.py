# -*- coding: utf-8 -*-
"""Database initialization, migration, demo data"""

import os, json, uuid
from datetime import datetime
from werkzeug.security import generate_password_hash
from config import get_db, DB_PATH, DEPARTMENT_CONFIGS
from prompts import *

def init_db():
    conn = get_db()
    c = conn.cursor()

    # 模板表
    c.execute('''CREATE TABLE IF NOT EXISTS extraction_templates (
        template_id TEXT PRIMARY KEY,
        role_id TEXT,
        template_name TEXT,
        template_type TEXT,
        ai_prompt TEXT,
        output_schema TEXT,
        display_layout TEXT,
        is_active INTEGER DEFAULT 1,
        create_time TEXT
    )''')

    # 记录表（新版）
    c.execute('''CREATE TABLE IF NOT EXISTS medical_records (
        id TEXT PRIMARY KEY,
        case_number TEXT UNIQUE,
        original_filename TEXT,
        role_id TEXT,
        template_id TEXT,
        extracted_data TEXT,
        confidence_data TEXT,
        demographics TEXT,
        lab_tests TEXT,
        treatment TEXT,
        confidence TEXT,
        raw_text TEXT,
        create_time TEXT
    )''')

    # 检查是否需要加新列（兼容旧数据库）
    existing_cols = {row[1] for row in c.execute("PRAGMA table_info(medical_records)").fetchall()}
    for col in ['role_id', 'template_id', 'extracted_data', 'confidence_data',
                'source_type', 'audio_transcript', 'qualitative_data',
                'module_type', 'text_source', 'analysis_type', 'batch_id', 'user_id']:
        if col not in existing_cols:
            c.execute(f"ALTER TABLE medical_records ADD COLUMN {col} TEXT")

    # 迁移旧记录的module_type
    c.execute("UPDATE medical_records SET module_type='image_ocr' WHERE module_type IS NULL AND (source_type='image' OR source_type IS NULL)")
    c.execute("UPDATE medical_records SET module_type='voice_input' WHERE module_type IS NULL AND source_type='audio'")

    # 研究成果表
    c.execute('''CREATE TABLE IF NOT EXISTS research_results (
        result_id TEXT PRIMARY KEY,
        data_type TEXT,
        dept_id TEXT,
        source_record_id TEXT,
        title TEXT,
        summary TEXT,
        core_metrics TEXT,
        conclusion TEXT,
        notes TEXT,
        status TEXT DEFAULT '待复核',
        create_time TEXT,
        update_time TEXT
    )''')

    # 兼容旧表：如果 status 列不存在则添加
    try:
        c.execute("ALTER TABLE research_results ADD COLUMN status TEXT DEFAULT '待复核'")
    except Exception:
        pass

    # ====== 用户认证表 ======
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        display_name TEXT,
        create_time TEXT
    )''')

    # users 表加 role / is_active 列
    user_cols = {row[1] for row in c.execute("PRAGMA table_info(users)").fetchall()}
    if "role" not in user_cols:
        c.execute("ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'user'")
    if "is_active" not in user_cols:
        c.execute("ALTER TABLE users ADD COLUMN is_active INTEGER DEFAULT 1")

    # 审计日志表
    c.execute("CREATE TABLE IF NOT EXISTS audit_log ("
             "id TEXT PRIMARY KEY, user_id TEXT, username TEXT, "
             "action TEXT NOT NULL, target_type TEXT, target_id TEXT, "
             "detail TEXT, ip_address TEXT, create_time TEXT)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_audit_user_time ON audit_log(user_id, create_time)")

    # research_results 加 user_id 列
    rr_cols = {row[1] for row in c.execute("PRAGMA table_info(research_results)").fetchall()}
    if 'user_id' not in rr_cols:
        c.execute("ALTER TABLE research_results ADD COLUMN user_id TEXT")

    # extraction_templates 加 user_id 列
    et_cols = {row[1] for row in c.execute("PRAGMA table_info(extraction_templates)").fetchall()}
    if 'user_id' not in et_cols:
        c.execute("ALTER TABLE extraction_templates ADD COLUMN user_id TEXT")
    if 'source_type' not in et_cols:
        c.execute("ALTER TABLE extraction_templates ADD COLUMN source_type TEXT DEFAULT 'manual'")

    # 数据迁移：创建默认 admin 用户，将无主数据归属 admin
    c.execute("SELECT id FROM users WHERE username='admin'")
    _admin_row = c.fetchone()
    if not _admin_row:
        _admin_id = str(uuid.uuid4())
        c.execute("INSERT INTO users (id, username, password_hash, display_name, role, create_time) VALUES (?,?,?,?,?,?)",
                  (_admin_id, 'admin', generate_password_hash('admin123'), '管理员', 'admin', datetime.now().isoformat()))
    else:
        _admin_id = _admin_row[0]
    c.execute("UPDATE users SET role='admin' WHERE username='admin' AND (role IS NULL OR role!='admin')")
    c.execute("UPDATE medical_records SET user_id=? WHERE user_id IS NULL", (_admin_id,))
    c.execute("UPDATE research_results SET user_id=? WHERE user_id IS NULL", (_admin_id,))
    c.execute("UPDATE extraction_templates SET user_id=? WHERE user_id IS NULL AND template_type='custom'", (_admin_id,))

    conn.commit()
    conn.close()

    # 初始化内置模板
    _init_builtin_templates()
    # 插入演示数据
    _init_demo_data()


def _init_builtin_templates():
    """插入系统内置模板（如果尚未存在），使用INSERT OR IGNORE逐条插入"""
    conn = get_db()
    c = conn.cursor()

    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # ===== 数据迁移（幂等）：旧 role_id → 'general' =====
    for old_id in ('diagnosis', 'nursing', 'other', 'doctor', 'nurse', 'researcher'):
        c.execute("UPDATE extraction_templates SET role_id='general' WHERE role_id=?", (old_id,))
        c.execute("UPDATE medical_records SET role_id='general' WHERE role_id=?", (old_id,))

    # ===== 旧 12 个通用模板（role_id 统一改为 general）=====
    legacy_templates = [
        # 诊疗模板
        ('tpl_doctor_medical', 'general', '门诊/住院病历', 'fixed',
         PROMPT_DOCTOR_MEDICAL_RECORD, 'table', now),
        ('tpl_doctor_lab', 'general', '检查检验结果', 'fixed',
         PROMPT_DOCTOR_LAB_RESULTS, 'table', now),
        # 护理模板
        ('tpl_nurse_admission', 'general', '入院护理评估表', 'fixed',
         PROMPT_NURSE_ADMISSION, 'card', now),
        ('tpl_nurse_barthel', 'general', 'Barthel自理能力量表', 'fixed',
         PROMPT_NURSE_BARTHEL, 'scale', now),
        ('tpl_nurse_morse', 'general', 'Morse跌倒风险量表', 'fixed',
         PROMPT_NURSE_MORSE, 'scale', now),
        ('tpl_nurse_braden', 'general', 'Braden压疮风险量表', 'fixed',
         PROMPT_NURSE_BRADEN, 'scale', now),
        ('tpl_nurse_pain', 'general', 'NRS/VAS疼痛评估', 'fixed',
         PROMPT_NURSE_PAIN, 'card', now),
        ('tpl_nurse_record', 'general', '护理记录单', 'fixed',
         PROMPT_NURSE_RECORD, 'table', now),
        # 其他模板
        ('tpl_researcher_default', 'general', '综合科研数据提取', 'fixed',
         PROMPT_RESEARCHER, 'table', now),
        # 音频模板
        ('tpl_audio_doctor', 'general', '医患对话录音', 'fixed',
         PROMPT_AUDIO_DOCTOR, 'table', now),
        ('tpl_audio_nurse', 'general', '护理交班录音', 'fixed',
         PROMPT_AUDIO_NURSE, 'card', now),
        ('tpl_audio_researcher', 'general', '研究访谈录音', 'fixed',
         PROMPT_AUDIO_RESEARCHER, 'table', now),
        # ICCAS问卷专用模板
        ('tpl_iccas_questionnaire', 'general', 'ICCAS问卷识别', 'fixed',
         PROMPT_ICCAS_QUESTIONNAIRE, 'table', now),
    ]

    # ===== 新增 24 个科室专属模板 (6科室 × 4子模板) =====
    dept_templates = []
    for dept_id, sub_prompts in DEPARTMENT_PROMPTS.items():
        dept_name = DEPARTMENT_CONFIGS[dept_id]['name']
        for sub_type, prompt_text in sub_prompts.items():
            tpl_id = f"tpl_{dept_id}_{sub_type}"
            tpl_name = f"{dept_name} - {DEPT_SUB_NAMES[sub_type]}"
            layout = DEPT_SUB_LAYOUTS[sub_type]
            dept_templates.append(
                (tpl_id, dept_id, tpl_name, 'fixed', prompt_text, layout, now)
            )

    for t in legacy_templates + dept_templates:
        c.execute('''INSERT OR IGNORE INTO extraction_templates
            (template_id, role_id, template_name, template_type, ai_prompt, display_layout, create_time)
            VALUES (?, ?, ?, ?, ?, ?, ?)''', t)

    # 迁移旧数据：无 role_id 的记录归入 general
    c.execute('''UPDATE medical_records
        SET role_id='general', template_id='tpl_researcher_default'
        WHERE role_id IS NULL''')

    conn.commit()
    conn.close()


def _init_demo_data():
    """插入演示/测试数据（幂等：仅在 medical_records 为空时插入）"""
    conn = get_db()
    c = conn.cursor()

    count = c.execute("SELECT COUNT(*) FROM medical_records").fetchone()[0]
    if count > 0:
        conn.close()
        return

    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    demo_records = [
        {
            "id": "demo-rec-001",
            "case_number": "DEMO_20260316_A001",
            "original_filename": "心内科高血压病历.txt",
            "role_id": "cardiology",
            "template_id": "cardiology_diagnosis",
            "extracted_data": json.dumps({
                "患者姓名": "张**",
                "性别": "男",
                "年龄": "62岁",
                "主诉": "反复头晕、头痛3年，加重1周",
                "诊断": "原发性高血压3级（极高危）",
                "收缩压": "168mmHg",
                "舒张压": "102mmHg",
                "心率": "78bpm",
                "EF值": "58%",
                "BNP": "285pg/mL",
                "用药方案": "氨氯地平5mg qd + 缬沙坦80mg qd",
                "随访计划": "2周后复诊，监测血压日记"
            }, ensure_ascii=False),
            "raw_text": "患者张某某，男，62岁。因反复头晕、头痛3年，加重1周入院。既往高血压病史3年，最高血压180/110mmHg。入院查体：BP 168/102mmHg，HR 78bpm。心脏超声：EF 58%。BNP 285pg/mL。诊断：原发性高血压3级（极高危）。治疗方案：氨氯地平5mg qd + 缬沙坦80mg qd。",
            "source_type": "text",
            "module_type": "text_extract"
        },
        {
            "id": "demo-rec-002",
            "case_number": "DEMO_20260316_A002",
            "original_filename": "神经内科帕金森评估.txt",
            "role_id": "neurology",
            "template_id": "neurology_diagnosis",
            "extracted_data": json.dumps({
                "患者姓名": "李**",
                "性别": "男",
                "年龄": "71岁",
                "主诉": "右手静止性震颤2年，行走不稳6个月",
                "诊断": "帕金森病(H-Y 2.5期)",
                "UPDRS评分": "38分",
                "MMSE评分": "26分",
                "头颅MRI": "双侧基底节区少许缺血灶",
                "用药方案": "美多芭250mg tid + 普拉克索0.5mg tid",
                "alpha-synuclein": "阳性",
                "NfL": "32.5pg/mL"
            }, ensure_ascii=False),
            "raw_text": "患者李某某，男，71岁。右手静止性震颤2年，行走不稳6个月。查体：右侧肢体齿轮样肌强直，慌张步态。UPDRS评分38分，MMSE 26分。头颅MRI：双侧基底节区少许缺血灶。血清alpha-synuclein阳性，NfL 32.5pg/mL。诊断：帕金森病(H-Y 2.5期)。",
            "source_type": "text",
            "module_type": "text_extract"
        },
        {
            "id": "demo-rec-003",
            "case_number": "DEMO_20260316_A003",
            "original_filename": "儿科哮喘病历.txt",
            "role_id": "pediatrics",
            "template_id": "pediatrics_diagnosis",
            "extracted_data": json.dumps({
                "患者姓名": "王**",
                "性别": "女",
                "年龄": "6岁",
                "主诉": "反复喘息、咳嗽1年，加重3天",
                "诊断": "支气管哮喘（中度持续）",
                "肺功能FEV1": "72%预计值",
                "PEF变异率": "25%",
                "嗜酸性粒细胞": "6.2%",
                "IgE": "385IU/mL",
                "治疗方案": "布地奈德雾化吸入 1mg bid",
                "过敏原": "尘螨++，猫毛+"
            }, ensure_ascii=False),
            "raw_text": "患儿王某某，女，6岁。反复喘息、咳嗽1年，加重3天。肺功能：FEV1 72%预计值，PEF变异率25%。血常规：嗜酸性粒细胞6.2%。总IgE 385IU/mL。过敏原检测：尘螨++，猫毛+。诊断：支气管哮喘（中度持续）。治疗：布地奈德雾化吸入1mg bid。",
            "source_type": "text",
            "module_type": "text_extract"
        },
        {
            "id": "demo-rec-004",
            "case_number": "DEMO_20260316_A004",
            "original_filename": "急诊科胸痛分诊记录.txt",
            "role_id": "emergency",
            "template_id": "emergency_diagnosis",
            "extracted_data": json.dumps({
                "患者姓名": "赵**",
                "性别": "男",
                "年龄": "55岁",
                "主诉": "突发胸痛2小时",
                "分诊级别": "II级（紧急）",
                "MEWS评分": "4分",
                "心电图": "V1-V4 ST段抬高0.3-0.5mV",
                "肌钙蛋白I": "2.8ng/mL",
                "发病至就诊时间": "2小时",
                "诊断": "急性前壁ST段抬高型心肌梗死",
                "急救措施": "阿司匹林300mg+氯吡格雷300mg负荷，启动急诊PCI绿色通道",
                "转归": "急诊PCI成功，转入CCU"
            }, ensure_ascii=False),
            "raw_text": "患者赵某某，男，55岁。突发胸痛2小时，大汗淋漓。分诊II级。MEWS 4分。心电图：V1-V4 ST段抬高0.3-0.5mV。肌钙蛋白I 2.8ng/mL。诊断：急性前壁STEMI。负荷抗血小板，启动PCI绿色通道。Door-to-balloon 68min，PCI成功，转CCU。",
            "source_type": "text",
            "module_type": "text_extract"
        },
        {
            "id": "demo-rec-005",
            "case_number": "DEMO_20260316_A005",
            "original_filename": "外科术后感染评估.txt",
            "role_id": "surgery",
            "template_id": "surgery_diagnosis",
            "extracted_data": json.dumps({
                "患者姓名": "陈**",
                "性别": "女",
                "年龄": "48岁",
                "主诉": "右膝关节疼痛活动受限3年",
                "手术名称": "右侧全膝关节置换术",
                "ASA分级": "II级",
                "麻醉方式": "腰硬联合麻醉",
                "术中出血量": "280mL",
                "手术时间": "135分钟",
                "引流管": "负压引流管1根",
                "术后抗菌方案": "头孢唑林1g q8h x48h",
                "术后第3天体温": "37.2℃",
                "切口评估": "甲级愈合，无红肿渗出"
            }, ensure_ascii=False),
            "raw_text": "患者陈某某，女，48岁。右膝骨关节炎，行右侧TKA。ASA II级，腰硬联合麻醉。手术时间135min，出血280mL。术后头孢唑林1g q8h预防感染。术后第3天体温37.2℃，切口甲级愈合。",
            "source_type": "text",
            "module_type": "text_extract"
        }
    ]

    for rec in demo_records:
        c.execute('''INSERT OR IGNORE INTO medical_records
            (id, case_number, original_filename, role_id, template_id,
             extracted_data, raw_text, create_time, source_type, module_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (rec["id"], rec["case_number"], rec["original_filename"],
             rec["role_id"], rec["template_id"], rec["extracted_data"],
             rec["raw_text"], now, rec["source_type"], rec["module_type"]))

    # ===== 插入研究成果演示数据 =====
    res_count = c.execute("SELECT COUNT(*) FROM research_results").fetchone()[0]
    if res_count == 0:
        demo_results = [
            {
                "result_id": "demo-res-001",
                "data_type": "描述性统计",
                "dept_id": "cardiology",
                "source_record_id": "demo-rec-001",
                "title": "心内科高血压患者血压控制现状分析",
                "summary": "基于2024-2025年度心内科收治的原发性高血压患者数据，对血压控制率、用药依从性及并发症发生率进行描述性统计分析。纳入328例患者，分析联合用药方案（CCB+ARB）的血压达标情况及安全性。",
                "core_metrics": json.dumps({
                    "样本量": "328例",
                    "血压达标率": "68.3%",
                    "联合用药比例": "72.6%",
                    "平均收缩压下降": "22.4±8.7mmHg",
                    "平均舒张压下降": "12.1±5.3mmHg",
                    "不良反应发生率": "8.2%",
                    "随访完成率": "91.5%"
                }, ensure_ascii=False),
                "conclusion": "CCB+ARB联合用药方案血压达标率达68.3%，显著优于单药治疗组(P<0.01)。年龄>65岁患者达标率较低(58.1%)，建议加强老年高血压患者个体化管理。",
                "notes": json.dumps([
                    {"type": "审核意见", "content": "数据完整性良好，统计方法合理，建议增加亚组分析。", "time": now},
                    {"type": "修改记录", "content": "补充了2025年Q1的随访数据。", "time": now}
                ], ensure_ascii=False),
                "status": "已归档"
            },
            {
                "result_id": "demo-res-002",
                "data_type": "回归分析",
                "dept_id": "neurology",
                "source_record_id": "demo-rec-002",
                "title": "帕金森病生物标志物与疾病进展的相关性研究",
                "summary": "回顾性分析神经内科帕金森病患者血清alpha-synuclein和NfL水平与UPDRS评分、H-Y分期的关系，探索其作为疾病进展监测指标的临床价值。共纳入156例患者，随访周期12-36个月。",
                "core_metrics": json.dumps({
                    "样本量": "156例",
                    "alpha-synuclein阳性率": "73.1%",
                    "NfL中位值": "28.6pg/mL",
                    "NfL与UPDRS相关系数r": "0.72(P<0.001)",
                    "alpha-synuclein与H-Y分期r": "0.58(P<0.01)",
                    "多因素回归R²": "0.67",
                    "AUC(疾病进展预测)": "0.84"
                }, ensure_ascii=False),
                "conclusion": "血清NfL水平与UPDRS评分呈显著正相关(r=0.72)，联合alpha-synuclein检测对帕金森病进展预测AUC达0.84，具有较好的临床应用价值。建议将其纳入帕金森病常规随访监测指标体系。",
                "notes": json.dumps([
                    {"type": "审核意见", "content": "研究设计严谨，统计方法恰当。建议增加与影像学指标的对比分析。", "time": now}
                ], ensure_ascii=False),
                "status": "待复核"
            },
            {
                "result_id": "demo-res-003",
                "data_type": "对比分析",
                "dept_id": "pediatrics",
                "source_record_id": "demo-rec-003",
                "title": "儿科哮喘患儿吸入激素治疗方案疗效对比",
                "summary": "前瞻性对比研究，比较布地奈德雾化吸入与丙酸氟替卡松吸入气雾剂治疗中度持续性儿童哮喘的临床疗效和安全性。将213例6-12岁患儿随机分为两组，观察12周。",
                "core_metrics": json.dumps({
                    "样本量": "213例(布地奈德组108例/氟替卡松组105例)",
                    "FEV1改善率(布地奈德组)": "18.3±6.2%",
                    "FEV1改善率(氟替卡松组)": "16.8±7.1%",
                    "急性发作次数减少": "62.5% vs 58.3%",
                    "日间症状评分下降": "1.8±0.6 vs 1.6±0.7",
                    "组间差异P值": "0.23(无显著差异)",
                    "不良反应率": "5.6% vs 7.6%"
                }, ensure_ascii=False),
                "conclusion": "布地奈德雾化吸入与丙酸氟替卡松在改善中度持续性儿童哮喘肺功能和症状控制方面疗效相当(P=0.23)，但布地奈德组不良反应率略低。对于低龄或配合度差的患儿，推荐优先使用雾化吸入给药方式。",
                "notes": json.dumps([
                    {"type": "审核意见", "content": "样本量充足，分组合理。已通过伦理委员会审批。", "time": now},
                    {"type": "备注", "content": "后续计划纳入3-6岁低龄组进行扩展研究。", "time": now}
                ], ensure_ascii=False),
                "status": "已归档"
            },
            {
                "result_id": "demo-res-004",
                "data_type": "描述性统计",
                "dept_id": "emergency",
                "source_record_id": "demo-rec-004",
                "title": "急诊胸痛患者快速分诊流程优化效果评估",
                "summary": "评估急诊科实施改良HEART评分结合MEWS评分的快速分诊流程后，STEMI患者Door-to-Balloon时间、误诊率及预后改善情况。统计实施前后各6个月数据，涵盖急性胸痛患者共1,247例。",
                "core_metrics": json.dumps({
                    "总病例数": "1,247例",
                    "STEMI识别例数": "89例",
                    "平均D2B时间(优化前)": "95±28min",
                    "平均D2B时间(优化后)": "72±19min",
                    "D2B<90min达标率提升": "67.4% → 88.6%",
                    "胸痛误诊率下降": "4.2% → 1.8%",
                    "院内死亡率": "3.4% → 2.1%"
                }, ensure_ascii=False),
                "conclusion": "实施改良快速分诊流程后，STEMI患者平均D2B时间缩短23分钟(P<0.001)，D2B达标率提升21.2个百分点。胸痛误诊率下降至1.8%，院内死亡率降至2.1%。该流程可作为急诊胸痛管理的标准化方案推广。",
                "notes": json.dumps([
                    {"type": "审核意见", "content": "数据对比清晰，流程改进效果显著。建议形成SOP并推广至基层急诊。", "time": now}
                ], ensure_ascii=False),
                "status": "待复核"
            },
            {
                "result_id": "demo-res-005",
                "data_type": "对比分析",
                "dept_id": "surgery",
                "source_record_id": "demo-rec-005",
                "title": "全膝关节置换术后感染预防策略比较研究",
                "summary": "比较三种围手术期抗菌方案（头孢唑林单药、头孢唑林+万古霉素联合、头孢唑林+术中局部灌洗）对全膝关节置换术后手术部位感染(SSI)的预防效果。回顾性分析456例TKA患者数据，随访至术后90天。",
                "core_metrics": json.dumps({
                    "总病例数": "456例",
                    "A组(单药)SSI率": "3.9%(6/154)",
                    "B组(联合静脉)SSI率": "2.0%(3/151)",
                    "C组(静脉+局部)SSI率": "1.3%(2/151)",
                    "深部感染率": "A:1.3% B:0.7% C:0.0%",
                    "抗菌药物不良反应": "A:2.6% B:5.3% C:3.3%",
                    "组间差异P值": "0.04"
                }, ensure_ascii=False),
                "conclusion": "三组方案SSI率存在统计学差异(P=0.04)。头孢唑林联合术中局部灌洗组SSI率最低(1.3%)且深部感染为0，但联合万古霉素组不良反应率较高(5.3%)。推荐对常规TKA患者采用头孢唑林+术中局部灌洗方案，高感染风险患者可考虑联合万古霉素。",
                "notes": json.dumps([
                    {"type": "审核意见", "content": "研究结论有实际临床指导意义，分组设计合理。", "time": now},
                    {"type": "修改记录", "content": "根据审核意见补充了亚组分析（BMI>30组）。", "time": now},
                    {"type": "备注", "content": "该成果已提交院内学术委员会评审。", "time": now}
                ], ensure_ascii=False),
                "status": "已归档"
            }
        ]

        for res in demo_results:
            c.execute('''INSERT OR IGNORE INTO research_results
                (result_id, data_type, dept_id, source_record_id, title, summary,
                 core_metrics, conclusion, notes, status, create_time, update_time)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (res["result_id"], res["data_type"], res["dept_id"],
                 res["source_record_id"], res["title"], res["summary"],
                 res["core_metrics"], res["conclusion"], res["notes"],
                 res["status"], now, now))

    conn.commit()
    conn.close()



