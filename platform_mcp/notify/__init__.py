"""邮件组提醒模块（V3.0 M5，架构 §19.5.5 / 计划 5.1-5.3）

组成：
- models.py   —— 三表 ORM（组 / 成员 / outbox，migration 009）；
- service.py  —— 通知分发（模板渲染 + 收件人解析 + outbox 落库）与组管理支撑；
- sender.py   —— aiosmtplib 发送器 + outbox flush（SMTP 参数经运行时配置中心 smtp.*）；
- tasks.py    —— Web 进程周期 flush 任务（单写多读：MCP 进程只写 outbox，Web 统一发送）。

仅 Web 功能（架构 §19.5.7「系统管理四类仅 Web」）：无 MCP 工具。
"""
