"""本地启动前置检查脚本 — 生成 crypto key + 同步迁移 + 检查 seed 用户"""
import os
import sys
import subprocess

# 1. 生成 crypto-secret.key
key_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "crypto-secret.key")
if not os.path.exists(key_path):
    from platform_mcp.common.crypto import CryptoUtils
    key = CryptoUtils.generate_key()
    with open(key_path, "wb") as f:
        f.write(key)
    print(f"[OK] crypto-secret.key created at {key_path} ({len(key)} bytes)")
else:
    print(f"[SKIP] crypto-secret.key already exists")

# 2. 检查 alembic 当前 head
print("\n--- Alembic current head ---")
result = subprocess.run(
    ["python", "-m", "alembic", "current"],
    capture_output=True, text=True, cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
print(result.stdout or result.stderr)

# 3. 同步迁移到 head
print("--- Alembic upgrade head ---")
result = subprocess.run(
    ["python", "-m", "alembic", "upgrade", "head"],
    capture_output=True, text=True, cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
print(result.stdout or result.stderr)

# 4. 检查 seed 用户
print("--- Seed users check ---")
import psycopg2
# P1-4 修复：DB 密码从环境变量读取（PLATFORM_DB_PASSWORD）
conn = psycopg2.connect(
    host=os.environ.get("PLATFORM_DB_HOST", "localhost"),
    port=int(os.environ.get("PLATFORM_DB_PORT", "5432")),
    user=os.environ.get("PLATFORM_DB_USER", "postgres"),
    password=os.environ.get("PLATFORM_DB_PASSWORD", ""),
    dbname=os.environ.get("PLATFORM_DB_NAME", "platform_mcp"),
)
cur = conn.cursor()
cur.execute("SELECT version_num FROM alembic_version")
print("DB alembic head:", cur.fetchone())
cur.execute("SELECT to_regclass('pmcp_datasource')")
print("pmcp_datasource table exists:", cur.fetchone())
cur.execute("""
    SELECT column_name FROM information_schema.columns
    WHERE table_name='pmcp_datasource' ORDER BY ordinal_position
""")
print("pmcp_datasource columns:", [r[0] for r in cur.fetchall()])
cur.execute("""
    SELECT u.username, u.status, r.role_code
    FROM pmcp_user u
    LEFT JOIN pmcp_user_role ur ON ur.user_id = u.id
    LEFT JOIN pmcp_role r ON r.id = ur.role_id
""")
print("existing users:", cur.fetchall())
conn.close()
