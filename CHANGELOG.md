# CHANGELOG

> 本项目在 **AI-refactor** 分支上的重构/变更记录。
> 记录只包含变更摘要与回滚/验证信息，不包含任何 secrets。

## 2026-03-06 13:49 CST — 结构化对齐 tdl download 特性 + 可配置并发 + 上传占位

## 2026-03-06 14:17 CST — 全量代码中文注释 + 修复按钮回归

### 目标

- 为项目主要 Python 代码添加中文注释/中文模块说明，便于维护与二次开发。
- 修复一次重构过程中引入的按钮类回归（`TagButtons.build` 丢失、`RetryButtons` 重复定义）。

### 改动摘要

- 为 `app.py` 与 `tdl_bot/*.py` 增加中文模块 docstring、关键逻辑中文注释。
- 修复 `tdl_bot/bot.py`：
  - 恢复 `TagButtons.build()`
  - `RetryButtons` 仅保留单一 `build()`
  - 保持现有行为与接口不变。

### 验证方法

```bash
python -m py_compile app.py tdl_bot/*.py
```

### 回滚

```bash
git checkout AI-refactor
# 回退到上一个提交
# git reset --hard <previous_commit>
```

---

### 目标

- 将 `tdl download` 的常用特性（group/skip-same/rewrite-ext/include/exclude/template/takeout 等）结构化进入配置文件，并由代码生成 argv 调用 tdl。
- 并发默认=1，但可以通过配置文件调整。
- 上传功能暂不实现，仅保留配置与代码占位（默认关闭）。

### 改动摘要

- 新增/扩展配置结构：`[bot]` / `[tdl]` / `[download]` / `[upload]`（upload 为占位）。
- 执行方式从 `create_subprocess_shell(cmd)` 改为 `create_subprocess_exec(tdl_path, *argv)`，减少引号/转义问题。
- `download.group / skip_same / rewrite_ext` 默认值与 tdl 保持一致（默认关闭，可配置开启）。
- `bot.max_concurrency` 控制 bot 任务并发（默认 1）。

### 影响范围

- 运行配置文件 `tdl_bot_config.toml` 若使用新表结构，需按新增字段配置。
- 兼容性：保留了对旧平铺键（如 `tdl_path`）的读取兼容，但推荐迁移到新结构。

### 验证方法

1) 语法检查：

```bash
python -m py_compile app.py tdl_bot/*.py
```

2) 运行检查：

- 首次运行若无配置文件：会生成默认 `tdl_bot_config.toml` 并退出。
- 配置 `bot_token / download_path / tags` 后再次运行：

```bash
python app.py
```

3) 在 Telegram 里发送 `https://t.me/...` 链接，选择 tag，确认下载任务启动并有进度更新。

### 回滚

- 回滚到之前实现：

```bash
git checkout AI-refactor
# 回滚到本次变更前的提交（示例：用 git log 找到上一个提交 hash）
# git reset --hard <previous_commit>
```

- 或直接切回原分支：

```bash
git checkout dev
```

---
