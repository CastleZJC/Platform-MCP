"""单元测试 — Skill 版本化双语存档（V3.0 M2.5，架构 §19.5.3 / §19.5.6 / 计划 M2.5、F-28）

覆盖：双语 README 生成（含盘内 README 优先 / 缺失模板兜底）/ 双语审核报告（三段式：基本信息 +
14 规则命中明细 + 广场比对结论；通过/未通过、merge/new/空相似）/ 审计摘要重建（计数 + 命中 +
非法枚举防御）/ 版本存档 upsert（insert 与覆盖两分支、仅 flush 不 commit、generated_by 兜底标记）/
部署期幂等补全（无存档行全量生成、完整条目跳过、部分缺失仅补 NULL 字段保留原值）。

用轻量 FakeDB 替代真实 AsyncSession，隔离 DB；README 生成用 tmp_path 真实落盘校验读盘优先级。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from platform_mcp.skills.audit.models import AuditResult, AuditRuleResult, Severity
from platform_mcp.skills.models import PmcpSkillVersion
from platform_mcp.skills.versioning import (
    GENERATED_BY_TEMPLATE,
    archive_skill_version,
    audit_result_from_summary,
    backfill_missing_archives,
    generate_bilingual_readme,
    generate_bilingual_report,
)


# ==================== 测试替身 ====================


class _FakeResult:
    def __init__(self, scalar=None) -> None:
        self._scalar = scalar

    def scalar_one_or_none(self):
        return self._scalar


class _FakeDB:
    """轻量伪 AsyncSession：execute 恒返回预置 scalar，记录 add/flush/commit。"""

    def __init__(self, existing: PmcpSkillVersion | None = None) -> None:
        self.existing = existing
        self.added: list[object] = []
        self.flush_count = 0
        self.commit_count = 0

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        self.flush_count += 1

    async def commit(self) -> None:
        self.commit_count += 1

    async def execute(self, stmt):
        return _FakeResult(self.existing)


def _audit_passed() -> AuditResult:
    r = AuditResult(skill_name="demo")
    r.results = [AuditRuleResult(rule_id="R1-01", severity=Severity.SUGGESTION, passed=True)]
    r.compute_counts()
    return r


def _audit_failed() -> AuditResult:
    r = AuditResult(skill_name="demo")
    r.results = [
        AuditRuleResult(
            rule_id="R4-01", severity=Severity.CRITICAL, passed=False,
            file_path="main.py", line_number=3, description="硬编码密码", suggestion="移除敏感值",
        ),
        AuditRuleResult(
            rule_id="R1-02", severity=Severity.WARNING, passed=False,
            file_path="cleanup.sh", line_number=1, description="递归删除", suggestion="谨慎使用",
        ),
    ]
    r.compute_counts()
    return r


# ==================== 双语 README ====================


class TestBilingualReadme:
    def test_盘内README优先中文_英文恒模板生成(self, tmp_path):
        (tmp_path / "README.md").write_text("# 用户自定义中文说明\n原创内容", encoding="utf-8")
        zh, en = generate_bilingual_readme("demo", "描述", tmp_path, "1.0.0")
        assert zh == "# 用户自定义中文说明\n原创内容"  # 读盘优先，保留用户原文
        assert en != zh
        assert "Requirements" in en  # 英文模板骨架

    def test_缺README双语模板兜底(self, tmp_path):
        zh, en = generate_bilingual_readme("demo", "描述", tmp_path, "0.1.0")
        assert "## 功能描述" in zh and "环境要求" in zh  # 中文模板（功能描述=描述正文）
        assert "## Description" in en and "Requirements" in en  # 英文模板
        assert zh != en

    def test_描述为空不报错(self, tmp_path):
        zh, en = generate_bilingual_readme("demo", None, tmp_path)
        assert "## 功能描述" not in zh  # 描述为空省略章节
        assert "环境要求" in zh
        assert "Requirements" in en

    def test_空包路径不读CWD防毒化(self):
        # 内置 Skill source_path=None → backfill 传 ""：哨兵目录兜底，
        # 中文走模板（不得把 CWD 的 README.md 误读为包内原文），文件树为空
        zh, en = generate_bilingual_readme("demo", "描述", "")
        assert "## 功能描述" in zh and "环境要求" in zh
        assert "## Description" in en and "Requirements" in en
        assert "├──" not in en and "└──" not in en  # 不扫全仓库目录树
        assert len(en) < 5000 and len(zh) < 5000


class TestBilingualPurity:
    """双语 README/报告单语纯净：「中文 / English」并列描述/工具描述按语言拆分（不得跨语言残留）。"""

    _DESC = "SQL 执行能力 / SQL execution capability"

    def test_中文版无英文残留(self, tmp_path):
        zh, en = generate_bilingual_readme(
            "demo", self._DESC, tmp_path, tools=[("t", "列出数据源 / List datasources")]
        )
        assert "SQL 执行能力" in zh
        assert "SQL execution capability" not in zh
        assert "列出数据源" in zh and "List datasources" not in zh

    def test_英文版无中文残留(self, tmp_path):
        zh, en = generate_bilingual_readme(
            "demo", self._DESC, tmp_path, tools=[("t", "列出数据源 / List datasources")]
        )
        assert "SQL execution capability" in en
        assert "SQL 执行能力" not in en
        assert "List datasources" in en and "列出数据源" not in en

    def test_未并列描述两语言同值(self, tmp_path):
        zh, en = generate_bilingual_readme("demo", "纯中文描述", tmp_path)
        assert "纯中文描述" in zh and "纯中文描述" in en

    def test_中文段内工具清单斜杠不误切(self, tmp_path):
        desc = "查询异步任务状态（execute_command / upload_file）的 execution_id / Query async task status"
        zh, _en = generate_bilingual_readme("demo", desc, tmp_path)
        assert "（execute_command / upload_file）的 execution_id" in zh
        assert "Query async task status" not in zh

    def test_报告描述按语言拆分(self):
        zh, en = generate_bilingual_report(
            skill_code="demo", skill_name="demo", description=self._DESC,
            version="0.1.0", audit_result=_audit_passed(),
        )
        assert "SQL 执行能力" in zh and "SQL execution capability" not in zh
        assert "SQL execution capability" in en and "SQL 执行能力" not in en

    def test_内置skill描述走双语字典(self):
        """内置 Skill（skill.desc.* 已登记 RESOURCES）：英文版 Description 为真英文，不残留中文"""
        zh, en = generate_bilingual_readme("demo", "纯中文描述", "", skill_code="database")
        assert "SQL 执行能力" in zh
        assert "SQL execution" in en
        assert "SQL 执行能力" not in en

    def test_装饰器注册快速开始无审核(self):
        zh, en = generate_bilingual_readme("demo", "描述", "", register_method="decorator")
        assert "审核" not in zh
        assert "Review" not in en

    def test_未登记code回退并列拆分(self):
        zh, en = generate_bilingual_readme("demo", "中文说明 / English desc", "", skill_code="demo")
        assert "中文说明" in zh and "English desc" in en


# ==================== 双语审核报告 ====================


class TestBilingualReport:
    def test_通过且无相似_推荐新增(self):
        zh, en = generate_bilingual_report(
            skill_code="demo", skill_name="Demo", description="d",
            version="0.1.0", audit_result=_audit_passed(), similar_skills=None,
        )
        assert "Skill 审核报告：Demo" in zh
        assert "全部规则通过" in zh and "新增" in zh
        assert "generated_by=template" in zh  # 模板兜底声明
        assert "Skill Review Report: Demo" in en
        assert "All rules passed" in en and "**new**" in en
        assert "generated_by=template" in en

    def test_未通过命中明细表(self):
        zh, en = generate_bilingual_report(
            skill_code="demo", skill_name="Demo", description="d",
            version="0.1.0", audit_result=_audit_failed(),
        )
        assert "未通过" in zh and "R4-01" in zh and "🔴 严重" in zh
        assert "main.py" in zh  # 命中文件路径入表
        assert "FAILED" in en and "R4-01" in en and "Critical" in en

    def test_相似merge结论入表(self):
        similar = [
            {"plaza_id": 5, "skill_code": "exist", "skill_name": "Exist",
             "version": "1.0", "similarity": 0.8, "recommendation": "merge"},
        ]
        zh, en = generate_bilingual_report(
            skill_code="demo", skill_name="Demo", description="d",
            version="0.1.0", audit_result=_audit_passed(), similar_skills=similar,
        )
        assert "广场比对结论" in zh and "合并到广场现有 Skill" in zh
        assert "Exist" in zh and "0.8" in zh
        assert "Plaza Comparison" in en and "merge into the existing plaza skill" in en

    def test_相似new结论(self):
        similar = [
            {"plaza_id": 9, "skill_code": "far", "skill_name": "Far",
             "version": "2.0", "similarity": 0.2, "recommendation": "new"},
        ]
        zh, en = generate_bilingual_report(
            skill_code="demo", skill_name="Demo", description="d",
            version="0.1.0", audit_result=_audit_passed(), similar_skills=similar,
        )
        assert "作为新增 Skill 分享" in zh
        assert "share as a new skill" in en


# ==================== 审计摘要重建 ====================


class TestAuditResultFromSummary:
    def test_完整摘要重建计数与命中(self):
        summary = _audit_failed().to_audit_summary()
        rebuilt = audit_result_from_summary(summary, skill_name="demo")
        assert rebuilt.skill_name == "demo"
        assert rebuilt.total_rules == 14
        assert rebuilt.critical_count == 1
        assert rebuilt.warning_count == 1
        assert rebuilt.passed is False
        rule_ids = {r.rule_id for r in rebuilt.results}
        assert rule_ids == {"R4-01", "R1-02"}
        assert all(not r.passed for r in rebuilt.results)

    def test_空摘要返回默认(self):
        rebuilt = audit_result_from_summary(None)
        assert rebuilt.total_rules == 14
        assert rebuilt.passed is True
        assert rebuilt.results == []

    def test_非法severity回退suggestion(self):
        summary = {
            "total_rules": 14, "critical_count": 0, "warning_count": 0,
            "suggestion_count": 1, "passed": True,
            "failed_rules": [{"rule_id": "RX", "severity": "bogus", "file_path": "", "line_number": 0}],
        }
        rebuilt = audit_result_from_summary(summary)
        assert rebuilt.results[0].severity == Severity.SUGGESTION

    def test_缺字段容错(self):
        rebuilt = audit_result_from_summary({"failed_rules": [{"rule_id": "R1"}]})
        assert rebuilt.results[0].rule_id == "R1"
        assert rebuilt.results[0].file_path == ""
        assert rebuilt.results[0].line_number == 0


# ==================== 版本存档 upsert ====================


class TestArchiveSkillVersion:
    async def test_insert分支_add且flush不commit(self):
        db = _FakeDB(existing=None)
        record = await archive_skill_version(
            db, skill_id=1, version="0.1.0", checksum="abc",
            readme_zh="zh", readme_en="en", report_zh="rzh", report_en="ren",
            audit_snapshot={"passed": True}, operator="dev01",
        )
        assert isinstance(record, PmcpSkillVersion)
        assert db.added == [record]  # insert 分支入 session
        assert record.skill_id == 1 and record.version == "0.1.0"
        assert record.inserted_by == "dev01" and record.updated_by == "dev01"
        assert record.generated_by == GENERATED_BY_TEMPLATE
        assert db.flush_count == 1
        assert db.commit_count == 0  # 仅 flush，事务由调用方统一提交

    async def test_同版本再存档覆盖更新不新增(self):
        existing = PmcpSkillVersion(
            skill_id=1, version="0.1.0", checksum="old",
            readme_zh="old-zh", readme_en="old-en", report_zh="old-rzh", report_en="old-ren",
            audit_snapshot={"passed": False}, generated_by="template", inserted_by="dev01",
        )
        db = _FakeDB(existing=existing)
        record = await archive_skill_version(
            db, skill_id=1, version="0.1.0", checksum="new",
            readme_zh="new-zh", readme_en="new-en", report_zh="new-rzh", report_en="new-ren",
            audit_snapshot={"passed": True}, operator="dev02",
        )
        assert record is existing  # upsert 覆盖，返回同一实例
        assert db.added == []  # 未新增
        assert record.checksum == "new" and record.readme_zh == "new-zh"
        assert record.updated_by == "dev02"
        assert record.inserted_by == "dev01"  # 原始创建者不变
        assert db.flush_count == 1 and db.commit_count == 0

    async def test_generated_by可覆盖为model(self):
        db = _FakeDB(existing=None)
        record = await archive_skill_version(
            db, skill_id=2, version="1.0.0", checksum=None,
            readme_zh=None, readme_en=None, report_zh=None, report_en=None,
            audit_snapshot=None, operator="dev01", generated_by="model",
        )
        assert record.generated_by == "model"  # M4 挂本地模型后切换标记


# ==================== 部署期幂等补全 ====================


class _RowsResult:
    """scalars().all() 形结果（skills 扫描查询）。"""

    def __init__(self, rows: list) -> None:
        self._rows = rows

    def scalars(self):
        return self

    def all(self) -> list:
        return self._rows


class _SeqDB:
    """backfill 专用伪 AsyncSession：execute 按预置结果序列依次弹出。"""

    def __init__(self, results: list) -> None:
        self._results = list(results)
        self.added: list[object] = []
        self.flush_count = 0

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        self.flush_count += 1

    async def execute(self, stmt):
        return self._results.pop(0)


def _skill_row(tmp_path) -> SimpleNamespace:
    return SimpleNamespace(
        id=1, version="1.0.0", skill_code="demo", skill_name="Demo",
        description="d", source_path=str(tmp_path), source_checksum="cs",
        audit_result={"passed": True}, register_method="upload",
    )


class TestBackfillMissingArchives:
    """1.2 部署期自动补全：缺存档/缺字段的历史 Skill 每次启动补齐，完整条目跳过。"""

    async def test_无存档行_全量补全并入库(self, tmp_path):
        db = _SeqDB([
            _RowsResult([_skill_row(tmp_path)]),  # skills 扫描
            _FakeResult(None),                    # existing 查询
            _FakeResult(None),                    # archive 内部查询（insert 分支）
        ])
        filled = await backfill_missing_archives(db)
        assert filled == 1
        record = db.added[0]
        assert isinstance(record, PmcpSkillVersion)
        assert record.generated_by == GENERATED_BY_TEMPLATE
        assert "## 功能描述" in record.readme_zh and "## Description" in record.readme_en
        assert "Skill 审核报告：Demo" in record.report_zh
        assert db.flush_count == 1

    async def test_已完整条目_跳过不动(self, tmp_path):
        existing = PmcpSkillVersion(
            skill_id=1, version="1.0.0", checksum="cs",
            readme_zh="zh", readme_en="en", report_zh="rzh", report_en="ren",
            audit_snapshot={"passed": True}, generated_by="template",
        )
        db = _SeqDB([
            _RowsResult([_skill_row(tmp_path)]),
            _FakeResult(existing),
        ])
        assert await backfill_missing_archives(db) == 0
        assert db.added == [] and db.flush_count == 0  # 未触发存档写入

    async def test_部分缺失_仅补NULL字段保留原值(self, tmp_path):
        existing = PmcpSkillVersion(
            skill_id=1, version="1.0.0", checksum="cs",
            readme_zh="用户上传原文", readme_en=None,
            report_zh="历史审核报告", report_en=None,
            audit_snapshot={"passed": True}, generated_by="model",
        )
        db = _SeqDB([
            _RowsResult([_skill_row(tmp_path)]),
            _FakeResult(existing),
            _FakeResult(existing),               # archive 内部查询（覆盖分支）
        ])
        filled = await backfill_missing_archives(db)
        assert filled == 1
        assert db.added == []                    # 覆盖既有行，未新增
        assert existing.readme_zh == "用户上传原文"  # 非 NULL 字段保留原值
        assert existing.report_zh == "历史审核报告"
        assert "## Description" in existing.readme_en     # NULL 字段模板补全
        assert "Skill Review Report: Demo" in existing.report_en
        assert existing.generated_by == GENERATED_BY_TEMPLATE
