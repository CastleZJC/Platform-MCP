"""检查 admin 用户密码是否为已知的 bcrypt 哈希"""
import os

import psycopg2

# P1-4 修复：DB 密码从环境变量读取（PLATFORM_DB_PASSWORD），默认值仅用于本地开发
conn = psycopg2.connect(
    host=os.environ.get("PLATFORM_DB_HOST", "localhost"),
    port=int(os.environ.get("PLATFORM_DB_PORT", "5432")),
    user=os.environ.get("PLATFORM_DB_USER", "postgres"),
    password=os.environ.get("PLATFORM_DB_PASSWORD", ""),
    dbname=os.environ.get("PLATFORM_DB_NAME", "platform_mcp"),
)
cur = conn.cursor()
cur.execute("SELECT username, password, nickname FROM pmcp_user")
rows = cur.fetchall()
for username, pwd, nickname in rows:
    print(f"user={username}, nickname={nickname}, pwd_hash_prefix={pwd[:30]}...")
conn.close()
