"""验证所有新模块可成功 import"""
import sys
errors = []

def check(name, mod):
    try:
        __import__(mod, fromlist=["*"])
        print(f"  OK  {name}")
    except Exception as e:
        print(f"  FAIL {name}: {e}")
        errors.append(name)

print("=== 新建模块 ===")
check("api_key_models", "platform_mcp.auth.api_key_models")
check("api_key_service", "platform_mcp.auth.api_key_service")
check("api_keys", "platform_mcp.api.api_keys")

print("=== 修改模块 ===")
check("api.__init__", "platform_mcp.api")
check("api.users", "platform_mcp.api.users")
check("api.guide", "platform_mcp.api.guide")
check("mcp_server", "platform_mcp.mcp_server")
check("skills.database", "platform_mcp.skills.database")

if errors:
    print(f"\n{len(errors)} FAILED: {errors}")
    sys.exit(1)
else:
    print("\n全部通过")
