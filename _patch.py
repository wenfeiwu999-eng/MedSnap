# -*- coding: utf-8 -*-
import glob, os

base = glob.glob('d:/HuaweiMoveData/Users/*/Desktop/*/MedSnap/')[0]

# ===== Patch db_init.py =====
fpath = os.path.join(base, 'db_init.py')
with open(fpath, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find insertion point
insert_idx = None
for i, l in enumerate(lines):
    if 'research_results' in l and 'user_id' in l and l.strip().startswith('#'):
        insert_idx = i
        break

new_block = [
    '    # users 表加 role / is_active 列\n',
    '    user_cols = {row[1] for row in c.execute("PRAGMA table_info(users)").fetchall()}\n',
    '    if "role" not in user_cols:\n',
    "        c.execute(\"ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'user'\")\n",
    '    if "is_active" not in user_cols:\n',
    '        c.execute("ALTER TABLE users ADD COLUMN is_active INTEGER DEFAULT 1")\n',
    '\n',
    '    # 审计日志表\n',
    '    c.execute("CREATE TABLE IF NOT EXISTS audit_log ("\n',
    '             "id TEXT PRIMARY KEY, user_id TEXT, username TEXT, "\n',
    '             "action TEXT NOT NULL, target_type TEXT, target_id TEXT, "\n',
    '             "detail TEXT, ip_address TEXT, create_time TEXT)")\n',
    '    c.execute("CREATE INDEX IF NOT EXISTS idx_audit_user_time ON audit_log(user_id, create_time)")\n',
    '\n',
]

lines = lines[:insert_idx] + new_block + lines[insert_idx:]
content = ''.join(lines)

# Fix admin INSERT
content = content.replace(
    'INSERT INTO users (id, username, password_hash, display_name, create_time) VALUES (?,?,?,?,?)',
    'INSERT INTO users (id, username, password_hash, display_name, role, create_time) VALUES (?,?,?,?,?,?)'
)
content = content.replace(
    "(_admin_id, 'admin', generate_password_hash('admin123'), '\u7ba1\u7406\u5458', datetime.now().isoformat())",
    "(_admin_id, 'admin', generate_password_hash('admin123'), '\u7ba1\u7406\u5458', 'admin', datetime.now().isoformat())"
)

# Add role enforcement
target = '    c.execute("UPDATE medical_records SET user_id=? WHERE user_id IS NULL", (_admin_id,))'
enforce = "    c.execute(\"UPDATE users SET role='admin' WHERE username='admin' AND (role IS NULL OR role!='admin')\")\n"
content = content.replace(target, enforce + target)

with open(fpath, 'w', encoding='utf-8') as f:
    f.write(content)
print("db_init.py patched OK, size=" + str(len(content)))
