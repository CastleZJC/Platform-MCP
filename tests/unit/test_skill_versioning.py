"""单元测试 — Skill 版本化双语存档（V3.0 M2.5，架构 §19.5.3 / §19.5.6 / 计划 M2.5、F-28）

覆盖：双语 README 生成（含盘内 README 优先 / 缺失模板兜底）/ 双语审核报告（三段式：基本信息 +
14 规则命中明细 + 广场比对结论；通过/未通过、merge/new/空相似）/ 审计摘要重建（计数 + 命中 +
非法枚举防御）/ 版本存档 upsert（insert 与覆盖两分支、仅 flush 不 commit、generated_by 兜底标记）/
部署期幂等补全（无存档行全量生成、完整条目跳过、部分缺失仅补 NULL 字段保留原值）/ 多语言补足
（readme_extra/report_extra 覆盖语义、pick_localized_text 分级取值、build_artifact_hint 补足提示、
latest_version_archive 最新存档，批次 5 设计定稿⑧）。

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
    build_artifact_hint,
    generate_bilingual_readme,
    generate_bilingual_report,
    latest_version_archive,
    next_patch_version,
    pick_localized_text,
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

    async def test_装饰器系统Skill_template存档_自愈刷新readme_en(self, tmp_path):
        """decorator+template 完整存档：readme_en 每次启动重生成（工具描述双语并列约定修复后
        Companion Tools 英文段自愈）；readme_zh/report 原值保留。upload 用户的 template
        完整存档不刷新（见 test_已完整条目_跳过不动）。"""
        row = _skill_row(tmp_path)
        row.register_method = "decorator"
        existing = PmcpSkillVersion(
            skill_id=1, version="1.0.0", checksum="cs",
            readme_zh="zh-old", readme_en="en-stale", report_zh="rzh", report_en="ren",
            audit_snapshot={"passed": True}, generated_by="template",
        )
        db = _SeqDB([
            _RowsResult([row]),
            _FakeResult(existing),
            _FakeResult(existing),               # archive 内部查询（覆盖分支）
        ])
        assert await backfill_missing_archives(db) == 1
        assert existing.readme_zh == "zh-old"    # 中文侧保留原值
        assert existing.readme_en != "en-stale"  # 英文侧自愈刷新
        assert "## Description" in existing.readme_en
        assert existing.report_zh == "rzh" and existing.report_en == "ren"


# ==================== 广场版本链自增（设计定稿⑤，2026-09-10）====================


class TestNextPatchVersion:
    def test_semver_patch自增(self):
        assert next_patch_version("1.2.3") == "1.2.4"
        assert next_patch_version("0.0.0") == "0.0.1"
        assert next_patch_version("10.20.30") == "10.20.31"

    def test_不可解析回退追加1(self):
        assert next_patch_version("1.0") == "1.0.1"
        assert next_patch_version("v2") == "v2.1"

    def test_空值兜底(self):
        assert next_patch_version(None) == "0.0.1"
        assert next_patch_version("") == "0.0.1"
        assert next_patch_version("   ") == "0.0.1"


# ==================== 多语言补足（批次 5，设计定稿⑧ 2026-09-11）====================


class _FirstResult:
    """scalars().first() 形结果（latest_version_archive 单行查询）。"""

    def __init__(self, row) -> None:
        self._row = row

    def scalars(self):
        return self

    def first(self):
        return self._row


class TestArchiveSkillVersionExtra:
    """readme_extra / report_extra 覆盖语义：未传保留既有（LLM 升级安全）/ 传入整体写入 /
    reset_extra=True 先清空再应用（内容变更重存档由调用方显式声明）。"""

    async def test_新版本带extra落库(self):
        db = _FakeDB(existing=None)
        record = await archive_skill_version(
            db, skill_id=1, version="0.1.0", checksum="abc",
            readme_zh="zh", readme_en="en", report_zh="rzh", report_en="ren",
            audit_snapshot={"passed": True}, operator="dev01",
            readme_extra={"ja-JP": "ja-rd"}, report_extra={"ja-JP": "ja-rp"},
        )
        assert record.readme_extra == {"ja-JP": "ja-rd"}
        assert record.report_extra == {"ja-JP": "ja-rp"}

    async def test_覆盖时未传extra保留既有值(self):
        # LLM 升级 / backfill 自愈重存档不传 extra：外部补档（external 级译文）绝不被兜底链路冲掉
        existing = PmcpSkillVersion(
            skill_id=1, version="0.1.0", checksum="cs",
            readme_zh="zh", readme_en="en", report_zh="rzh", report_en="ren",
            audit_snapshot={"passed": True}, generated_by="model", inserted_by="dev01",
            readme_extra={"ja-JP": "ja-rd"}, report_extra={"fr-FR": "fr-rp"},
        )
        db = _FakeDB(existing=existing)
        record = await archive_skill_version(
            db, skill_id=1, version="0.1.0", checksum="new",
            readme_zh="zh2", readme_en="en2", report_zh="rzh2", report_en="ren2",
            audit_snapshot={"passed": True}, operator="llm", generated_by="model",
        )
        assert record is existing
        assert record.readme_extra == {"ja-JP": "ja-rd"}
        assert record.report_extra == {"fr-FR": "fr-rp"}

    async def test_传入extra整体写入_未传列保留(self):
        existing = PmcpSkillVersion(
            skill_id=2, version="1.0.0", checksum="cs",
            readme_zh="zh", readme_en="en", report_zh="rzh", report_en="ren",
            audit_snapshot={"passed": True}, generated_by="template", inserted_by="dev01",
            readme_extra={"ja": "old"}, report_extra=None,
        )
        db = _FakeDB(existing=existing)
        record = await archive_skill_version(
            db, skill_id=2, version="1.0.0", checksum="new",
            readme_zh="zh", readme_en="en", report_zh="rzh", report_en="ren",
            audit_snapshot={"passed": True}, operator="cc",
            readme_extra={"ja": "new", "ko": "ko-rd"},  # 调用方自行合并后整体写入
        )
        assert record.readme_extra == {"ja": "new", "ko": "ko-rd"}
        assert record.report_extra is None  # 未传保留

    async def test_reset_extra先清空再应用传入(self):
        existing = PmcpSkillVersion(
            skill_id=3, version="2.0.0", checksum="cs",
            readme_zh="zh", readme_en="en", report_zh="rzh", report_en="ren",
            audit_snapshot={"passed": True}, generated_by="external", inserted_by="dev01",
            readme_extra={"ja-JP": "stale"}, report_extra={"fr-FR": "stale"},
        )
        db = _FakeDB(existing=existing)
        record = await archive_skill_version(
            db, skill_id=3, version="2.0.0", checksum="new",
            readme_zh="zh", readme_en="en", report_zh="rzh", report_en="ren",
            audit_snapshot={"passed": True}, operator="dev01",
            readme_extra={"ja-JP": "fresh"}, reset_extra=True,
        )
        assert record.readme_extra == {"ja-JP": "fresh"}  # 清空后仅剩传入值
        assert record.report_extra is None  # 清空且未传 → None

    async def test_reset_extra不传任何extra则全清(self):
        existing = PmcpSkillVersion(
            skill_id=4, version="1.0.0", checksum="cs",
            readme_zh="zh", readme_en="en", report_zh="rzh", report_en="ren",
            audit_snapshot={"passed": True}, generated_by="template", inserted_by="dev01",
            readme_extra={"ja-JP": "old"}, report_extra={"fr-FR": "old"},
        )
        db = _FakeDB(existing=existing)
        await archive_skill_version(
            db, skill_id=4, version="1.0.0", checksum="new",
            readme_zh="zh", readme_en="en", report_zh="rzh", report_en="ren",
            audit_snapshot={"passed": True}, operator="dev01", reset_extra=True,
        )
        assert existing.readme_extra is None and existing.report_extra is None


class TestPickLocalizedText:
    """多语言分级取值：zh/en 主列 → extra 命中（精确/小写/语言子标签）→ 回退中文优先。"""

    def test_zh取中文缺失回退英文(self):
        assert pick_localized_text("zh-CN", "中文", "en") == "中文"
        assert pick_localized_text("zh-TW", None, "en") == "en"

    def test_无locale默认中文(self):
        assert pick_localized_text(None, "中文", "en") == "中文"

    def test_en取英文缺失回退中文(self):
        assert pick_localized_text("en-US", "中文", "en") == "en"
        assert pick_localized_text("en-GB", "中文", None) == "中文"

    def test_extra原值精确命中(self):
        extra = {"ja-JP": "ja-text"}
        assert pick_localized_text("ja-JP", "中文", "en", extra) == "ja-text"

    def test_extra小写命中(self):
        extra = {"ja-JP": "ja-text"}
        assert pick_localized_text("ja-jp", "中文", "en", extra) == "ja-text"

    def test_extra语言子标签命中(self):
        # locale=ja-JP 命中 extra 的 ja 键（locale 语言子标签降级，与前端 localeText 同口径）
        assert pick_localized_text("ja-JP", "中文", "en", {"ja": "ja-text"}) == "ja-text"

    def test_无区域locale不命中带区域键(self):
        # 反向不成立：locale=ja 不命中 ja-JP 键（仅 键=locale 或 键=locale 语言子标签）
        assert pick_localized_text("ja", "中文", "en", {"ja-JP": "ja-text"}) == "中文"

    def test_extra未命中回退中文优先(self):
        assert pick_localized_text("fr-FR", "中文", "en", {"ja-JP": "ja"}) == "中文"
        assert pick_localized_text("fr-FR", None, "en", {"ja-JP": "ja"}) == "en"
        assert pick_localized_text("fr-FR", None, None, None) == ""

    def test_extra空文本不命中(self):
        # 空字符串译文视为未补档，回退主列
        assert pick_localized_text("ja-JP", "中文", None, {"ja-JP": ""}) == "中文"


class TestBuildArtifactHint:
    """产物补足提示：template/model 级返回文案（locale 定语言），external/未知/None 为终态无提示。"""

    def test_template与model返回提示(self):
        assert build_artifact_hint("template") is not None
        assert "submit_skill_artifact" in build_artifact_hint("model")

    def test_默认中文_en_locale切英文(self):
        assert build_artifact_hint("template").startswith("当前双语产物")
        en = build_artifact_hint("model", "en-US")
        assert en.startswith("Bilingual artifacts")

    def test_external未知None返回None(self):
        assert build_artifact_hint("external") is None
        assert build_artifact_hint("bogus") is None
        assert build_artifact_hint(None) is None


class TestLatestVersionArchive:
    async def test_取最新存档行(self):
        row = PmcpSkillVersion(
            skill_id=1, version="2.0.0", checksum="cs",
            readme_zh="zh", readme_en="en", report_zh="rzh", report_en="ren",
            audit_snapshot={"passed": True}, generated_by="external", inserted_by="cc",
        )
        db = _SeqDB([_FirstResult(row)])
        assert await latest_version_archive(db, 1) is row

    async def test_无存档返回None(self):
        db = _SeqDB([_FirstResult(None)])
        assert await latest_version_archive(db, 99) is None
