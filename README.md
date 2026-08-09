# MedSnap 临床数据智能平台

AI 驱动的临床数据提取、统计分析与科研成果管理一体化平台。

上传病历图片、PDF、语音或文本，平台通过多模态大模型自动识别并提取结构化字段；提取结果可进入统计分析引擎做定量分析，或进入质性分析流程做主题编码，最终沉淀为可导出的科研成果记录。

## 核心功能

- **多模态数据提取**：支持图片 / PDF / 语音 / 文本四种输入方式，基于阿里云 DashScope 多模态大模型识别手写病历、检查单、问卷（含 ICCAS 问卷）等医疗文档
- **模板管理**：按 7 大科室分类的内置模板 + 自定义模板，可配置预设字段、字段预览与选择性提取
- **定量统计分析**：纯 Python 统计引擎（pandas + scipy），支持描述统计、组间比较、可视化，支持科室筛选
- **质性分析**：四步分析流程（编码 → 主题聚类 → 代表性引用），面向访谈文本等定性数据
- **数据脱敏**：本地正则脱敏模块，识别姓名、身份证号、电话等敏感信息，不依赖网络调用
- **记录管理与导出**：提取记录 CRUD、批量处理、Excel / Word 导出
- **用户与权限**：注册登录、管理员后台（用户管理、审计日志、系统统计）

## 技术栈

- **后端**：Flask（蓝图模块化架构）+ SQLite
- **AI**：阿里云 DashScope（多模态识别 / 文本分析）
- **统计**：pandas / numpy / scipy
- **前端**：原生 HTML + JS（templates/ + static/）
- **部署**：Docker（ModelScope 创空间，`app_port: 7860`）

## 项目结构

```
MedSnap/
├── app.py                  # 入口：注册蓝图、启动服务（默认端口 7860）
├── config.py               # Flask 应用与 DashScope 配置（API Key 从环境变量读取）
├── db_init.py              # SQLite 数据库初始化
├── auth.py                 # 认证辅助
├── prompts.py              # 各科室 / 场景的 AI 提取 Prompt 定义
├── desensitizer.py         # 敏感信息检测与本地脱敏
├── statistics_engine.py    # 统计分析引擎（纯计算，不依赖 Flask）
├── statistics_routes.py    # 统计分析路由
├── research_routes.py      # 科研成果管理路由
├── routes/                 # 蓝图路由
│   ├── auth_routes.py      # 注册 / 登录 / 登出
│   ├── template_routes.py  # 角色 / 科室 / 模板管理
│   ├── extraction_routes.py# 上传识别、字段提取、质性分析、批量处理
│   ├── record_routes.py    # 记录 CRUD、Excel 导出
│   └── admin_routes.py     # 管理员后台
├── services/               # 业务服务层
│   ├── ai_service.py       # DashScope 调用封装
│   ├── file_processor.py   # 图片 / PDF / 语音预处理
│   ├── data_analysis.py    # 数据分析
│   └── export_service.py   # 导出服务
├── templates/              # 页面模板（首页、数据提取、统计、科研成果、后台）
├── static/                 # 前端静态资源
└── 安装并启动.bat           # Windows 一键安装启动
```

## 快速开始

### 本地运行

```bash
pip install -r requirements.txt
set DASHSCOPE_API_KEY=你的Key    # Windows
# export DASHSCOPE_API_KEY=你的Key   # Linux/macOS
python app.py                  # 默认 7860 端口，可 python app.py 8080 指定
```

浏览器访问 http://localhost:7860

Windows 用户也可直接双击 `安装并启动.bat` 自动安装依赖并启动。

### Docker 部署

```bash
docker build -t medsnap .
docker run -p 7860:7860 -e DASHSCOPE_API_KEY=你的Key medsnap
```

## 环境变量

| 变量 | 说明 |
|---|---|
| `DASHSCOPE_API_KEY` | 阿里云 DashScope API Key（必需，AI 识别功能依赖） |

> 参考 `.env.example`。请勿将真实 Key 提交到仓库；`_dev_notes/` 目录已被 gitignore，其中为历史开发残留。

## 许可

Apache License 2.0
