"""重置 admin 密码为 admin123（使用 bcrypt）"""
import os

import psycopg2
from platform_mcp.auth.service import hash_password

new_hash = hash_password("admin123")
print(f"new bcrypt hash: {new_hash}")

# P1-4 修复：DB 密码从环境变量读取（PLATFORM_DB_PASSWORD）
conn = psycopg2.connect(
    host=os.environ.get("PLATFORM_DB_HOST", "localhost"),
    port=int(os.environ.get("PLATFORM_DB_PORT", "5432")),
    user=os.environ.get("PLATFORM_DB_USER", "postgres"),
    password=os.environ.get("PLATFORM_DB_PASSWORD", ""),
    dbname=os.environ.get("PLATFORM_DB_NAME", "platform_mcp"),
)
cur = conn.cursor()
cur.execute("UPDATE pmcp_user SET password = %s WHERE username = 'admin'", (new_hash,))
conn.commit()
cur.execute("SELECT username, password FROM pmcp_user WHERE username = 'admin'")
print("after update:", cur.fetchone())
conn.close()
