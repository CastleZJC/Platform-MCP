"""MCP 接入指南 API"""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_mcp.auth.middleware import get_current_user
from platform_mcp.common.database import get_db
from platform_mcp.common.response import ResponseBase
from platform_mcp.config import get_settings
from platform_mcp.mcp_server.models import PmcpSkill
from platform_mcp.mcp_server.skill.registry import get_skill_instance as _get_skill_instance

router = APIRouter(prefix="/guide", tags=["MCP 接入指南"])


@router.get("/config")
async def get_config(_user: dict = Depends(get_current_user)):
    settings = get_settings()
    host = settings.mcp.http_host
    port = settings.mcp.http_port
    path = settings.mcp.http_path
    config = {
        "dev": {
            "description": "本地开发（stdio 模式，仅限本机）",
            "mcpServers": {
                "Platform-MCP": {
                    "command": "python",
                    "args": ["-m", "platform_mcp.mcp_server"],
                    "env": {
                        "PLATFORM_MCP_API_KEY": "<your-api-key>",
                        "PLATFORM_MCP_ENV": settings.env,
                    },
                }
            },
        },
        "prod": {
            "description": "远程服务器（streamable-http 模式）— 部署后请将 <your-server-ip> 替换为实际服务器 IP/域名",
            "mcpServers": {
                "Platform-MCP": {
                    "url": f"http://<your-server-ip>:{port}{path}/",
                    "type": "http",
                    "headers": {
                        "PLATFORM_MCP_API_KEY": "<your-api-key>",
                    },
                }
            },
            "current_runtime": {"host": host, "port": port, "path": path},
        },
    }
    return ResponseBase(data=config)


@router.get("/tools")
async def get_tools(db: AsyncSession = Depends(get_db), _user: dict = Depends(get_current_user)):
    result = await db.execute(select(PmcpSkill).where(PmcpSkill.status == 1).order_by(PmcpSkill.id))
    skills = result.scalars().all()
    data = []
    for s in skills:
        instance = _get_skill_instance(s.skill_code)
        tools = []
        if instance is not None:
            for meta in instance.list_tools():
                tools.append({
                    "tool_name": meta.tool_name,
                    "display_name": meta.display_name,
                    "description": meta.description,
                    "risk_level": meta.risk_level,
                })
        data.append({
            "skill_code": s.skill_code,
            "skill_name": s.skill_name,
            "description": s.description,
            "register_method": s.register_method,
            "tool_count": len(tools),
            "tools": tools,
        })
    return ResponseBase(data=data)


@router.get("/usage")
async def get_usage(_user: dict = Depends(get_current_user)):
    """返回 MCP SQL 执行 + Shell 命令执行的使用建议（交互范式 + 注意事项）。"""
    settings = get_settings()
    local_dirs = settings.datasource.allowed_sql_dirs or []
    return ResponseBase(data={
        "scenarios": [
            {
                "title": "模糊匹配数据源（SQL）",
                "user_says": "用 app-sample-1 执行 documents/samples/x.sql",
                "behavior": "Claude 查询 list_datasources，按 app-sample-1 子串匹配 datasource_code / name / host；唯一命中直接执行，多匹配时弹出候选让用户选择",
            },
            {
                "title": "显式选择数据源（SQL）",
                "user_says": "执行 documents/samples/x.sql",
                "behavior": "Claude 列出当前角色可访问的数据源（admin 全部，developer 自动排除 PROD），让用户选择后执行",
            },
            {
                "title": "完整指定数据源（SQL）",
                "user_says": "用 ora-app-dev 执行 x.sql",
                "behavior": "直接调用 execute_sql_file，无中间交互",
            },
            {
                "title": "模糊匹配服务器（Shell）",
                "user_says": "在 linux-app-dev 上执行 uname -a",
                "behavior": "Claude 查询 list_servers，按 linux-app-dev 子串匹配 server_code / name / host；唯一命中直接执行 execute_command，多匹配时弹候选",
            },
            {
                "title": "上传/下载文件（SFTP）",
                "user_says": "把 D:\\pkg\\x.tar.gz 传到 linux-app-dev 的 /tmp/",
                "behavior": "Claude 调 upload_file，本地路径必须在 settings.allowed_sql_dirs 白名单内，远端路径必须在 server.allowed_paths 白名单内",
            },
            {
                "title": "Claude 自动判断 SQL vs Shell",
                "user_says": "app-sample-1 上查 Oracle 的 dual 表 / linux-app-dev 上看磁盘空间",
                "behavior": "Claude 依据意图自动选 execute_sql_text 或 execute_command；模糊场景（如『linux-app-dev 上检查一下』）Claude 会反问用户：『是查 Oracle 数据库还是看服务器磁盘？』，确认后再调用对应 skill",
            },
        ],
        "tips": [
            "数据源/服务器关键字优先用编码片段（如 app-sample-1、app-sample-2），匹配精度高于主机名",
            "PROD 环境仅 admin 可执行，developer 角色会被自动过滤",
            "HIGH / CRITICAL 风险 SQL 或 Shell 命令会先返回 confirm_token，Claude 会自动完成二次确认",
            "Shell：rm -rf 根目录、mkfs、dd 写块设备、fork bomb、shutdown 等直接判 CRITICAL；sudo / systemctl stop 等判 HIGH",
            "SFTP：本地路径受 settings.allowed_sql_dirs 限制，远端路径受 server.allowed_paths 限制；文件上限 500MB；路径风险：写入 /etc /boot 等系统目录强制 CRITICAL，需二次确认",
            "Claude 自动意图识别：依据用户语义选择 database/server skill；当指令模糊（如『检查一下 linux-app-dev』『修复 216』）时反问用户，避免误用 skill",
            "意图识别补充验证：用户在指令断言中包含 SQL 关键字（SELECT/INSERT/UPDATE/DELETE/表名/视图）→ database；包含 shell 关键字（执行/传输/上传/下载/cron/服务/进程/磁盘）→ server；同时命中或都不命中 → 反问",
        ],
        "current_whitelist": {
            "local_dirs": local_dirs,
            "local_dirs_warning": (
                f"当前已配置: {local_dirs}" if local_dirs
                else "⚠ 当前 allowed_sql_dirs 为空 — DEV 容许任意本地路径；PROD 强制要求配置，未配置时文件操作将被拒绝"
            ),
            "remote_per_server": "每台服务器的远端白名单见 server.allowed_paths（Web 端『服务器管理』表单）；为空时同上规则",
        },
    })
