import os, sys
os.environ["DASHSCOPE_API_KEY"]="sk-b42f150f26a34ad096115a2f3221ca5a"
os.environ["MODELSCOPE_API_KEY"]="ms-0b1bd02a-a5fc-4a05-ad31-b33de050f670"

# 直接import而非exec，避免Werkzeug兼容问题
from app import app
from db_init import init_db

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 7860
    print("=" * 50)
    print("  MedSnap 临床数据智能平台")
    print(f"  访问地址: http://localhost:{port}")
    print("  按 Ctrl+C 停止服务")
    print("=" * 50)
    init_db()
    app.run(host="0.0.0.0", port=port, debug=False)
