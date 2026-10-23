# 弗洛洛 ERP 文档导航

[项目首页](../README.md) · [版本日志](version.md) · [当前进度](IMPLEMENTATION.md)

当前版本 v1.0.10。文档已按主题从23份合并为9份，保留历史版本、迁移、安全限制和可信验收记录；避免同一主题分散查阅。

## 从这里开始

| 目的                               | 手册                                                   |
| ---------------------------------- | ------------------------------------------------------ |
| 查看已实现功能、测试与下一步       | [当前进度](IMPLEMENTATION.md)                          |
| 安装、升级、备份与安全             | [部署与安全](DEPLOYMENT.md)                            |
| 日常采购、销售、库存与报表         | [业务手册](BUSINESS.md)                                |
| 离线指令、AI采购、操作确认与OneBot | [交互手册](INTERACTION.md)                             |
| 架构、数据库和细粒度权限           | [架构手册](ARCHITECTURE.md)                            |
| 已实现HTTP接口及错误语义           | [API](API.md)                                          |
| 开发规范、Harness记录、登录与品牌  | [开发手册](DEVELOPMENT.md) · [AGENTS.md](../AGENTS.md) |
| 各版本变更和历史验收               | [版本日志](version.md)                                 |

<a id="business"></a>

## 业务快捷入口

[采购](BUSINESS.md#procurement) · [销售](BUSINESS.md#sales) · [出库](BUSINESS.md#shipments) · [报表](BUSINESS.md#reports) · [操作工作台](INTERACTION.md#operations) · [AI采购步骤](INTERACTION.md#ai-purchase) · [OneBot](INTERACTION.md#onebot)

<a id="development"></a>

## 开发快捷入口

[模块边界](ARCHITECTURE.md#architecture) · [数据库](ARCHITECTURE.md#database) · [权限](ARCHITECTURE.md#permissions) · [安全](DEPLOYMENT.md#security) · [Harness](DEVELOPMENT.md#harness)

文档仍使用Markdown，统一位于docx/；唯一版本日志为version.md。优先更新已有主题手册，不再为每个功能新增碎片文档。已实现、设计中和未验收能力必须分别说明。
