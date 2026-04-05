# -*- coding: utf-8 -*-
"""
MedSnap - Entry Point
"""
import sys, traceback
from flask import jsonify
from config import app
from db_init import init_db

# Register all Blueprints
from routes.auth_routes import auth_bp
from routes.template_routes import template_bp
from routes.extraction_routes import extraction_bp
from routes.record_routes import record_bp
from statistics_routes import stats_bp
from research_routes import research_bp
from routes.admin_routes import admin_bp

app.register_blueprint(auth_bp)
app.register_blueprint(template_bp)
app.register_blueprint(extraction_bp)
app.register_blueprint(record_bp)
app.register_blueprint(stats_bp)
app.register_blueprint(research_bp)
app.register_blueprint(admin_bp)

@app.errorhandler(500)
def handle_500(e):
    return jsonify({"status": "error", "msg": f"服务器内部错误: {str(e)}"}), 500

@app.errorhandler(Exception)
def handle_exception(e):
    traceback.print_exc()
    return jsonify({"status": "error", "msg": f"未处理异常: {str(e)}"}), 500

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 7860
    print("=" * 50)
    print("  MedSnap 临床数据智能平台")
    print(f"  访问地址: http://localhost:{port}")
    print("  按 Ctrl+C 停止服务")
    print("=" * 50)
    init_db()
    app.run(host="0.0.0.0", port=port, debug=False)
