#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Zcode-Status-TypeBar —— 安装器（Windows）。

做四件事：
  1. 把插件文件复制到 %USERPROFILE%\\.zcode\\Zcode-Status-TypeBar；
  2. 生成 config.json（写入当前 Python 路径与 app.asar 路径）；
  3. 在 app.asar 的主进程入口末尾追加一行动态 import，并同步修正
     asar 头部中的文件大小、偏移与 SHA256 完整性信息；
  4. 把 usage_mcp.py 注册为 ZCode 的 MCP server。

运行前请完全退出 ZCode。重复运行 = 升级/修复（会先移除旧注入行再加新的）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
from pathlib import Path
from typing import NoReturn

PLUGIN_NAME = "Zcode-Status-TypeBar"
PLUGIN_VERSION = "1.0.0"
PLUGIN_FILES = ("inject-main.cjs", "overlay.js", "zusage.py", "usage_mcp.py")
INJECT_MARKER = "[zusage] load failed"

# 匹配旧版/本安装器写入的注入行（整行删除，重复安装不会叠加）
INJECT_RE = re.compile(
    r'(?m)^[ \t]*;?import\("file:///[^"\r\n]*inject-main\.cjs"\)'
    r'\.then\(\(\) => null, \(e\) => console\.error\("\[zusage\] load failed", e\)\);[ \t]*\r?\n?'
)

DEFAULT_CONFIG = {
    "activity_min_ms": 1500,
    "heartbeat_ms": 30000,
    "hot_reload": True,
    "context_window": 1000000,
    "lang": "zh",
}


# ---------------------------------------------------------------- 控制台输出
def say(msg: str = "") -> None:
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        print(msg.encode("utf-8", "replace").decode("utf-8", "replace"), flush=True)


def fail(msg: str) -> NoReturn:
    say("\n[错误] " + msg)
    raise SystemExit(1)


# ------------------------------------------------------------------ asar 读写
def parse_asar(fh) -> tuple[dict, int]:
    """读取 asar 头部。返回 (header, 数据区起始偏移)。

    asar 头部是 Chromium pickle：4/len(b)/len(c)/len(json) 四个 uint32，之后是 JSON。
    其中 b = json_len + 8，数据区从 8 + b 开始。
    """
    raw = fh.read(16)
    if len(raw) != 16:
        raise ValueError("文件太小，不是有效的 asar")
    magic, b, c, d = struct.unpack("<IIII", raw)
    if magic != 4 or d <= 0 or b != d + 8 or c != d + 4:
        raise ValueError("不是有效的 asar 头部（pickle 字段异常）")
    header = json.loads(fh.read(d))
    if not isinstance(header, dict) or not isinstance(header.get("files"), dict):
        raise ValueError("asar 头部缺少 files 目录")
    return header, 8 + b


def iter_entries(header: dict):
    """按头部顺序遍历所有叶子条目，产出 (内部路径, 条目 dict)。"""
    def walk(node: dict, prefix: str):
        for name, entry in node.get("files", {}).items():
            full = prefix + "/" + name if prefix else name
            if isinstance(entry, dict) and "files" in entry:
                yield from walk(entry, full)
            else:
                yield full, entry

    yield from walk(header, "")


def get_entry(header: dict, path: str):
    node = header
    for seg in path.replace("\\", "/").strip("/").split("/"):
        node = node.get("files", {}).get(seg)
        if node is None:
            return None
    return node


def read_entry(fh, data_start: int, entry: dict) -> bytes:
    fh.seek(data_start + int(entry["offset"]))
    return fh.read(int(entry["size"]))


def make_integrity(data: bytes, block_size: int = 4 * 1024 * 1024) -> dict:
    blocks = [hashlib.sha256(data[i:i + block_size]).hexdigest()
              for i in range(0, len(data), block_size)]
    return {
        "algorithm": "SHA256",
        "hash": hashlib.sha256(data).hexdigest(),
        "blockSize": block_size,
        "blocks": blocks,
    }


def repack_asar(src: Path, dst: Path, replacements: dict[str, bytes]) -> None:
    """完整重打包 asar：只替换 replacements 中的文件，其余内容逐字节复制。"""
    with open(src, "rb") as fin:
        header, data_start = parse_asar(fin)

        items = []
        for full, entry in iter_entries(header):
            if entry.get("unpacked") or "link" in entry or "offset" not in entry:
                items.append((full, entry, None, 0, None))
                continue
            old_off = int(entry["offset"])
            old_size = int(entry["size"])
            items.append((full, entry, old_off, old_size, replacements.get(full)))

        # 按头部顺序重新分配偏移（asar 的文件区顺序与头部遍历顺序一致）
        cursor = 0
        for full, entry, old_off, old_size, new_data in items:
            if old_off is None:
                continue
            size = len(new_data) if new_data is not None else old_size
            entry["size"] = size
            entry["offset"] = str(cursor)
            if new_data is not None and "integrity" in entry:
                entry["integrity"] = make_integrity(new_data)
            cursor += size

        header_bytes = json.dumps(
            header, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        prefix = struct.pack("<IIII", 4, len(header_bytes) + 8,
                             len(header_bytes) + 4, len(header_bytes))

        with open(dst, "wb") as fout:
            fout.write(prefix)
            fout.write(header_bytes)
            for full, entry, old_off, old_size, new_data in items:
                if old_off is None:
                    continue
                if new_data is not None:
                    fout.write(new_data)
                    continue
                fin.seek(data_start + old_off)
                remaining = old_size
                while remaining:
                    chunk = fin.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise ValueError(f"读取 asar 内容失败（文件被截断）: {full}")
                    fout.write(chunk)
                    remaining -= len(chunk)
            fout.flush()
            os.fsync(fout.fileno())


def asar_version_and_main(asar_path: Path) -> tuple[str, str]:
    with open(asar_path, "rb") as fh:
        header, data_start = parse_asar(fh)
        pkg_entry = get_entry(header, "package.json")
        if not pkg_entry or "offset" not in pkg_entry:
            return "unknown", "out/main/index.js"
        try:
            pkg = json.loads(read_entry(fh, data_start, pkg_entry).decode("utf-8"))
        except Exception:
            return "unknown", "out/main/index.js"
        version = str(pkg.get("version") or "unknown")
        main = str(pkg.get("main") or "out/main/index.js").replace("\\", "/")
        if main.startswith("./"):
            main = main[2:]
    return version, main.lstrip("/")


def patch_asar(asar_path: Path, entry_path: str, url: str) -> dict:
    with open(asar_path, "rb") as fh:
        header, data_start = parse_asar(fh)
        entry = get_entry(header, entry_path)
        if not entry or "offset" not in entry:
            raise ValueError(f"在 asar 中找不到入口文件: {entry_path}")
        text = read_entry(fh, data_start, entry).decode("utf-8")
        had_injection = INJECT_MARKER in text

        cleaned = INJECT_RE.sub("", text).rstrip()
        line = (';import(' + json.dumps(url, ensure_ascii=False) +
                ').then(() => null, (e) => console.error("[zusage] load failed", e));')
        patched = cleaned + "\n\n" + line + "\n"
        if patched.count(INJECT_MARKER) != 1:
            raise ValueError("注入行生成异常（标记数量不为 1），已中止，未修改客户端")
        data = patched.encode("utf-8")
        replacements = {entry_path: data}

    tmp = asar_path.with_name(asar_path.name + ".zusage-tmp")
    try:
        repack_asar(asar_path, tmp, replacements)
        # 校验临时包：入口可解析、注入行存在、哈希一致、package.json 可读
        with open(tmp, "rb") as fh:
            new_header, new_start = parse_asar(fh)
            new_entry = get_entry(new_header, entry_path)
            content = read_entry(fh, new_start, new_entry)
            if INJECT_MARKER not in content.decode("utf-8"):
                raise ValueError("临时 asar 校验失败：未找到注入行")
            if "integrity" in new_entry:
                if hashlib.sha256(content).hexdigest() != new_entry["integrity"]["hash"]:
                    raise ValueError("临时 asar 校验失败：SHA256 不一致")
            pkg_entry = get_entry(new_header, "package.json")
            if pkg_entry:
                json.loads(read_entry(fh, new_start, pkg_entry).decode("utf-8"))
        os.replace(tmp, asar_path)
    except Exception:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise

    return {"entry": entry_path, "old_size": len(text.encode("utf-8")),
            "new_size": len(data), "had_injection": had_injection}


# ------------------------------------------------------------------ 通用工具
def is_zcode_running() -> bool:
    if os.name != "nt":
        return False
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq ZCode.exe", "/NH"],
            capture_output=True, text=True, errors="ignore", timeout=10,
        ).stdout
        return "ZCode.exe" in out
    except Exception:
        return False


def find_asar(explicit: str | None, plugin_dir: Path) -> Path:
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    cfg_path = plugin_dir / "config.json"
    if cfg_path.exists():
        try:
            asar_cfg = json.loads(cfg_path.read_text(encoding="utf-8")).get("asar_path")
            if asar_cfg:
                candidates.append(Path(asar_cfg))
        except Exception:
            pass
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.append(Path(local) / "Programs" / "ZCode" / "resources" / "app.asar")
        candidates.append(Path(local) / "ZCode" / "resources" / "app.asar")
    for env in ("PROGRAMFILES", "PROGRAMFILES(X86)"):
        base = os.environ.get(env)
        if base:
            candidates.append(Path(base) / "ZCode" / "resources" / "app.asar")
    for c in candidates:
        try:
            if c.is_file():
                return c.resolve()
        except OSError:
            pass
    fail(
        "没有找到 ZCode 的 app.asar。请用 --asar 参数指定，例如：\n"
        r'  python install.py --asar "C:\Users\你\AppData\Local\Programs\ZCode\resources\app.asar"'
    )


def copy_plugin_files(src_dir: Path, dest_dir: Path) -> None:
    missing = [f for f in PLUGIN_FILES if not (src_dir / f).is_file()]
    if missing:
        fail("安装包不完整，缺少文件: " + ", ".join(missing))
    if src_dir.resolve() == dest_dir.resolve():
        return
    dest_dir.mkdir(parents=True, exist_ok=True)
    for f in PLUGIN_FILES:
        shutil.copy2(src_dir / f, dest_dir / f)


def write_json_atomic(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def register_mcp(config_path: Path, python_path: str, mcp_script: Path) -> bool:
    cfg: dict = {}
    if config_path.exists():
        try:
            cfg = json.loads(config_path.read_text(encoding="utf-8-sig"))
        except Exception as e:
            fail(f"无法解析 {config_path}: {e}\n为避免破坏现有配置，安装已中止。")
        if not isinstance(cfg, dict):
            fail(f"{config_path} 不是 JSON 对象，安装已中止。")
        backup = config_path.with_name(config_path.name + ".zusage.bak")
        if not backup.exists():
            shutil.copy2(config_path, backup)
    servers = cfg.setdefault("mcp", {}).setdefault("servers", {})
    if not isinstance(servers, dict):
        fail(f"{config_path} 中的 mcp.servers 不是对象，安装已中止。")
    servers[PLUGIN_NAME] = {"command": python_path, "args": [str(mcp_script)]}
    write_json_atomic(config_path, cfg)
    return True


# ---------------------------------------------------------------------- 主流程
def main() -> None:
    parser = argparse.ArgumentParser(
        description="安装 Zcode-Status-TypeBar（Windows）。运行前请完全退出 ZCode。")
    parser.add_argument("--asar", help="ZCode 的 app.asar 路径（默认自动查找）")
    parser.add_argument("--dest", help="插件安装目录（默认 %%USERPROFILE%%\\.zcode\\"
                                      + PLUGIN_NAME + "）")
    parser.add_argument("--skip-mcp", action="store_true",
                        help="不注册 MCP server（只装状态条）")
    parser.add_argument("--mcp-config", help="覆盖 ZCode CLI 配置文件路径（调试用）")
    parser.add_argument("--force", action="store_true",
                        help="跳过 ZCode 进程检查（仅建议用于测试副本）")
    args = parser.parse_args()

    if sys.version_info < (3, 8):
        fail("需要 Python 3.8 或更高版本。")

    src_dir = Path(__file__).resolve().parent
    dest_dir = (Path(args.dest).expanduser() if args.dest
                else Path.home() / ".zcode" / PLUGIN_NAME).resolve()
    if args.asar:
        explicit = Path(args.asar).expanduser()
        if not explicit.is_file():
            fail("--asar 指定的文件不存在: " + str(explicit))
    asar_path = find_asar(args.asar, dest_dir)

    say("Zcode-Status-TypeBar 安装器 v" + PLUGIN_VERSION)
    say("  插件目录: " + str(dest_dir))
    say("  app.asar: " + str(asar_path))

    if is_zcode_running() and not args.force:
        fail("检测到 ZCode 正在运行。请完全退出 ZCode（包括托盘图标）后重新运行。\n"
             "      如果只是想测试安装器，可对 app.asar 的副本使用 --asar 和 --force。")

    try:
        zcode_version, entry_path = asar_version_and_main(asar_path)
    except Exception as e:
        fail(f"读取 app.asar 失败: {e}")

    say("  ZCode 版本: " + zcode_version)
    say("  注入入口: " + entry_path)

    # 1. 复制文件
    copy_plugin_files(src_dir, dest_dir)
    say("[1/4] 插件文件已就位")

    # 2. 生成配置（保留已有配置里的自定义项）
    cfg_path = dest_dir / "config.json"
    cfg = dict(DEFAULT_CONFIG)
    if cfg_path.exists():
        try:
            old = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
            if isinstance(old, dict):
                cfg.update(old)
        except Exception:
            pass
    cfg["python_path"] = str(Path(sys.executable).resolve())
    cfg["asar_path"] = str(asar_path)
    cfg["plugin_version"] = PLUGIN_VERSION
    write_json_atomic(cfg_path, cfg)
    say("[2/4] 配置已写入: " + str(cfg_path))

    # 3. 备份并注入 app.asar
    backup = asar_path.with_name(asar_path.name + f".zusage-backup-{zcode_version}")
    if not backup.exists():
        say("      正在备份 app.asar（约 " + str(asar_path.stat().st_size // (1024 * 1024))
            + " MB）...")
        shutil.copy2(asar_path, backup)
    inject_url = (dest_dir / "inject-main.cjs").as_uri()
    try:
        info = patch_asar(asar_path, entry_path, inject_url)
    except PermissionError as e:
        fail(f"没有权限写入 app.asar: {e}\n"
             "      请关闭 ZCode；如果 ZCode 安装在 Program Files，请用管理员终端运行本脚本。")
    except Exception as e:
        fail(f"注入 app.asar 失败（原文件未改动）: {e}")
    say("[3/4] 已注入 app.asar" + ("（替换了旧注入）" if info["had_injection"] else ""))
    say("      备份: " + str(backup))

    # 4. 注册 MCP
    if args.skip_mcp:
        say("[4/4] 已跳过 MCP 注册（--skip-mcp）")
    else:
        mcp_cfg = (Path(args.mcp_config).expanduser() if args.mcp_config
                   else Path.home() / ".zcode" / "cli" / "config.json")
        register_mcp(mcp_cfg, cfg["python_path"], dest_dir / "usage_mcp.py")
        say("[4/4] 已注册 MCP server: " + str(mcp_cfg))

    say("")
    say("安装完成。请启动 ZCode：输入框下方会出现 token 用量状态条。")
    say("首次数值会在模型请求完成后出现；点击状态条右侧的齿轮可配置显示项。")
    say("MCP 工具 token_usage 在新会话中可用（若未出现，重启一次 ZCode）。")
    say("")
    say("提示：ZCode 客户端升级会覆盖 app.asar，升级后重新运行本安装器即可恢复。")


def _use_console_encoding() -> None:
    """把 stdout/stderr 对齐到控制台当前编码。

    强制 utf-8 会在中文 Windows 的 cmd（GBK/936）里变成乱码 —— 一键安装脚本
    双击运行时正是这种环境。控制台不支持 utf-8 时退回系统 ANSI 编码，
    非 ASCII 输出仍用 errors="replace" 保证不抛异常。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            encoding = (stream.encoding or "").lower()
            if "utf" in encoding:
                stream.reconfigure(encoding="utf-8", errors="replace")
            else:
                stream.reconfigure(encoding=encoding or None, errors="replace")
        except Exception:
            pass


if __name__ == "__main__":
    _use_console_encoding()
    main()
