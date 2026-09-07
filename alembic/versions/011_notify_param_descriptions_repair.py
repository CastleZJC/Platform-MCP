"""notify 模板参数说明双重编码修复

009 seed 曾以 json.dumps 字符串 + JSONB 绑定类型写入 param_descriptions（绑定处理器
再次序列化），导致 JSONB 列内存的是 JSON 字符串标量而非对象：SQLAlchemy 读回 str，
前端 Object.entries 逐字符遍历，模板编辑弹窗显示"参数 = {{0}}，说明 = {"。

本迁移将字符串标量行解包回对象（幂等：仅处理 jsonb_typeof = 'string' 的行；
经 documents/db 发布版 SQL 或 UI 编辑过的行本就是对象，不受影响）。

Revision ID: 011
Revises: 010
Create Date: 2026-09-07
"""

from typing import Union

from alembic import op

revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE pmcp_notify_group "
        "SET param_descriptions = (param_descriptions #>> '{}')::jsonb, "
        "    updated_at = now() "
        "WHERE param_descriptions IS NOT NULL "
        "  AND jsonb_typeof(param_descriptions) = 'string'"
    )


def downgrade() -> None:
    # 数据修复无回滚必要：不重新引入双重编码
    pass
