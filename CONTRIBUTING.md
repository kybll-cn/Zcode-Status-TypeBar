# 贡献指南

感谢参与。这个项目会改写 ZCode 客户端的 `app.asar` 并向渲染进程注入 JS，
改动有真实的破坏性风险，所以下面几条是硬性要求，不是建议。

## 硬性要求

**任何改动都必须在 `app.asar` 的副本上验证，不能拿用户机器上的客户端试。**

```bat
:: 1. 从客户端备份一份
copy "%LOCALAPPDATA%\Programs\ZCode\resources\app.asar" D:\test\app.asar

:: 2. 对副本安装（--force 跳过 ZCode 进程检查）
python install.py --asar D:\test\app.asar --dest D:\test\plugindir ^
    --mcp-config D:\test\mcp.json --force

:: 3. 对副本卸载，确认内容还原
python uninstall.py --asar D:\test\app.asar --dest D:\test\plugindir ^
    --mcp-config D:\test\mcp.json --force
```

### 提交前必过的检查

| 检查 | 怎么做 |
| --- | --- |
| Python 能编译 | `python -m py_compile install.py uninstall.py zusage.py usage_mcp.py` |
| JS 语法正确 | `new Function(fs.readFileSync("overlay.js","utf8"))`，ZCode 用同一套方式校验热更新 |
| 卸载后文件内容还原 | 逐字节比对全部打包文件（应为 0 差异），且完整性哈希全部有效 |
| 重复安装幂等 | 连跑两次 `install.py`，`app.asar` 的 SHA256 应完全相同 |
| 无本机路径泄漏 | `grep -rn "C:\\\\Users\\\\<你的用户名>" .` 应无结果 |

最后一条特别重要：`config.example.json` 是示例配置，里面不能出现任何真实用户名或路径。

## 代码约定

### 改 `install.bat` / `uninstall.bat` 之前先读这段

这两个文件是 **GBK 编码 + CRLF 换行**，按系统 ANSI 码页解析。这不是疏忽，是踩过坑之后的
选择 —— 它们必须能在用户双击运行时的那种 cmd 里正常工作。以下规则改的时候务必遵守：

- **不要加 `chcp 65001`。** 命令行会改成 UTF-8，于是把 GBK 字节当 UTF-8 读，后续行全部错位，
  表现为 `'某行片段' 不是内部或外部命令`。
- **注释行只写 ASCII。** 中文注释在部分码页下会让 cmd 吞掉后续字符。中文只放在 `echo` 里。
- **`echo` 行里不要出现 `->`。** 会被当成重定向符，整行连同括号块一起被吞掉。用 `：` 或文字代替。
- **不要在括号块里 `shift`。** 在 ( ) 块里 shift 不影响 `%*`。而且 `%*` 本来就在解析期展开，
  shift 对它无效 —— 剩余参数要逐个搬进 `REST`。
- **`find` / `tasklist` 用 `%SystemRoot%\System32\` 绝对路径。** 装了 Git for Windows 时
  PATH 里的 `find.exe` 是 GNU find，`find /I "x"` 会把 `/I` 当文件名直接报错。
- **保持 CRLF。** 用编辑器保存成 LF 会让 cmd 解析错乱（症状和加了 `chcp` 类似）。

改完务必在真实环境验证一次，至少跑通「ZCode 在运行」和「正常安装」两条路径。

### 其他约定

- **注释解释「为什么」，不复述「做了什么」。** 这个项目的注释密度本来就高，改动时保持同样风格：
  写清楚踩过的坑和约束（尤其是那些看起来可以简化、但一简化就翻车的地方）。
- **注入行只有一个来源。** `install.py` 的 `INJECT_RE` 和 `INJECT_MARKER` 必须一起改，
  否则重复安装会叠加注入行。用 `[zusage] load failed` 作为唯一标记。
- **不要在 overlay 里引入外部依赖。** 它被当作一段字符串注入进页面，没有模块系统，
  只能用一个自包含 IIFE。
- **查询侧保持只读。** `zusage.py` 只允许 `SELECT`，别加任何写操作。

## 版本号

`install.py` 顶部的 `PLUGIN_VERSION` 与 `CHANGELOG.md` 要同步更新，
并在 `CHANGELOG.md` 里写清这版改了什么。

## 提交 issue 时请附上

- ZCode 版本和版本号（帮助 → 关于）；
- Python 版本；
- 状态条不出现 / 数字不对 / 崩溃，分别属于不同问题，描述时区分开；
- 如果状态条没出现，先看 **帮助 → 开发者工具** 的控制台，里面有 `[zusage]` 开头的排查信息。

## 风险提示也要如实

改动涉及客户端文件注入，如果你的改动让某些人更难以卸载或更难以理解风险，
即使功能更好也应该拒绝合并。保持安装器「失败不留半成品」「可完整还原」的性质。

## 许可

提交即表示你同意你的贡献以 **GNU AGPL v3.0 或更高版本** 发布。

AGPL 的网络条款对二次分发的场景有约束：改造后通过网络提供给用户使用时，需要向这些用户
提供你的修改版源码。如果你的用法不涉及网络分发，AGPL 的要求与 GPL 基本一致。
