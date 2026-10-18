# 更新日志

本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [1.0.0]

首个公开版本。

### 状态条

- 底栏固定五项，从左到右：**速度 · 首字 · 缓存 / 上下文 / 会话累计 / 会话错误 / 今日合计**。
- 「速度 · 首字 · 缓存」三项并排，构成同一次请求快慢的因果链：
  - 速度为端到端口径（输出 tokens ÷ 请求总耗时，含首字等待与工具往返），纯生成速度放在悬停对照；
  - 首字延迟由 `first_token_at − started_at` 现算 —— 客户端写的 `time_to_first_token_ms`
    列约三分之一为 NULL，直接读会频繁显示成横杠；
  - 缓存命中率保留两位小数 —— 99.968% 用 `toFixed(0)`/`toFixed(1)` 都会变成 100%，而命中
    100% 在物理上不可能。
- 「会话累计」把 tokens、轮数、工具调用次数并到一项。
- 「会话错误」统计轮次真报错 + 工具失败 + 模型重试；**用户主动中断（cancelled）不计入**。
- 「上下文」为当前会话占用百分比 + 微进度条，超限被拒时红色闪烁并弹出处理建议气泡。
- 配色跟随 ZCode 浅色 / 深色主题；分屏时每个 pane 各自显示本 pane 会话的数字。
- 条面尺寸收紧：图标 12→11px、齿轮 17→15px、上下文进度条 46→38px、项内分隔左右留白 6→4px。

### 已知行为

- ZCode 升级会覆盖 `app.asar`，状态条随之消失，重新运行 `install.bat` 即可恢复。
- 实测全库 `cache_creation_input_tokens` 恒为 0（ZCode 不写该字段），因此缓存命中率的分母
  只能用 `input`，不能是 `cache_read + cache_creation`（那样会算出真正的 100%）。
- 排障信息只写 DevTools 控制台（帮助 → 开发者工具），不落盘；控制台输入
  `window.__zusageDiag` 可查看更多挂载信息。

### 数据查询

- 常驻 Python 查询进程（`zusage.py serve`，stdin/stdout 行协议），省掉每次查询的解释器启动开销；意外退出自动重启，不稳定时回退一次性进程。
- 事件触发：`fs.watch` 监听数据库写入 + 去抖 + 限频，完全空闲时零进程零轮询，仅保留兜底心跳。
- 只读打开 `~/.zcode/cli/db/db.sqlite`，全程只执行 `SELECT`。
- 可选 SSH 远程数据源，用于连的是远端 `zcode-server` 的会话。

### MCP 工具

- 只读 stdio MCP server，工具名 `token_usage`，支持 `current` / `today` / `week` / `days:N` / `sessions[:N]` / `models[:days]` / `session:<id前缀>` / `workspace:<目录关键词>`。

### 安装与卸载

- `install.bat`：一键安装。自动检测并按需安装 Python 3（优先 `winget`，否则官网静默安装包），检查 ZCode 是否完全退出，在受保护目录下自动弹 UAC 提权重跑，每步都有中文提示。
- `uninstall.bat`：一键卸载，同样带环境检查。
- `install.py`：复制文件、生成配置、备份并注入 `app.asar`、注册 MCP server；重复运行为幂等（字节级不变）。
- `uninstall.py`：移除注入行、注销 MCP、删除插件目录；可选 `--restore-backup` / `--keep-files` / `--dry-run`。
- 注入前后会校验 asar 头部与 SHA256 完整性；写入临时文件并通过校验后才替换原文件，失败不留半成品。

### 排障

- 状态条未挂载或报错时，排查信息写 DevTools 控制台（帮助 → 开发者工具），不落盘、不外发；在控制台输入 `window.__zusageDiag` 可查看更多挂载信息。
