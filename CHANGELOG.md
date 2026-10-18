# 更新日志

本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [1.0.0]

首个公开版本。

### 状态条

- 输入框下方悬浮胶囊条，实时显示上下文占用、本轮消耗、会话累计、今日合计、工具调用与子代理用量。
- 悬停任意条目查看明细拆解（input / output / cache read / 耗时 / 首 token 延迟）。
- 点击「子代理」查看逐个子代理的独立消耗与运行状态。
- 点击齿轮可勾选显示项、覆盖上下文窗口大小、切换中英文。
- 配色跟随 ZCode 浅色 / 深色主题；分屏时每个 pane 各自显示本 pane 会话的数字。

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
