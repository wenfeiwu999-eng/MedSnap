# -*- coding: utf-8 -*-
"""
MedSnap 打包脚本
将项目打包为可分发的 ZIP 部署包，排除缓存文件
"""
import os
import zipfile
import sys
from datetime import datetime

# 配置
SOURCE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_NAME = "MedSnap"
OUTPUT_DIR = os.path.dirname(SOURCE_DIR)  # 输出到上级目录

# 排除规则
EXCLUDE_DIRS = {
    '__pycache__',
    '.git',
    'venv',
    '.venv',
    'node_modules',
    '.idea',
    '.vscode',
    'env',
}

EXCLUDE_FILES = {
    '.pyc',
    '.pyo',
    '.pyd',
    '.DS_Store',
    'Thumbs.db',
    '.secret_key',
}

# 排除特定文件名
EXCLUDE_NAMES = {
    'nul',
    '打包部署.py',  # 不打包自身
}


def should_exclude(path, name):
    """判断是否应排除"""
    # 排除目录
    if os.path.isdir(os.path.join(path, name)):
        return name in EXCLUDE_DIRS
    # 排除特定扩展名
    _, ext = os.path.splitext(name)
    if ext.lower() in EXCLUDE_FILES:
        return True
    # 排除特定文件名
    if name in EXCLUDE_NAMES:
        return True
    return False


def create_package():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_filename = f"{PROJECT_NAME}_部署包_{timestamp}.zip"
    zip_path = os.path.join(OUTPUT_DIR, zip_filename)

    file_count = 0
    total_size = 0

    print(f"{'='*50}")
    print(f"  MedSnap 打包工具")
    print(f"{'='*50}")
    print(f"  源目录: {SOURCE_DIR}")
    print(f"  输出文件: {zip_path}")
    print(f"{'='*50}")
    print()

    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(SOURCE_DIR):
            # 原地修改 dirs 列表来跳过排除的目录
            dirs[:] = [d for d in dirs if not should_exclude(root, d)]

            for file in files:
                if should_exclude(root, file):
                    continue

                file_path = os.path.join(root, file)
                # 计算在 ZIP 中的相对路径
                arcname = os.path.join(
                    PROJECT_NAME,
                    os.path.relpath(file_path, SOURCE_DIR)
                )

                try:
                    zf.write(file_path, arcname)
                    file_size = os.path.getsize(file_path)
                    file_count += 1
                    total_size += file_size
                except Exception as e:
                    print(f"  [跳过] {file}: {e}")

    # 输出结果
    zip_size = os.path.getsize(zip_path)
    print(f"  打包完成！")
    print(f"  - 文件数量: {file_count} 个")
    print(f"  - 原始大小: {total_size / 1024 / 1024:.1f} MB")
    print(f"  - 压缩后大小: {zip_size / 1024 / 1024:.1f} MB")
    print(f"  - 输出位置: {zip_path}")
    print()
    print(f"  将此 ZIP 文件拷贝给对方，解压后双击「安装并启动.bat」即可运行")
    print(f"{'='*50}")

    return zip_path


if __name__ == '__main__':
    create_package()
