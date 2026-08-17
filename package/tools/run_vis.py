#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 李时瑀律师
# Based on the MIT-licensed v2026.07.28 runner (dedb6402fbe74958062a2d2126dda52411095ee5).
# The original MIT notice is preserved in LICENSES/MIT.txt; R4 modifications and
# the combined file are distributed under GPL-3.0-only.
"""诉讼可视化唯一公开runner（07-only硬门）。
用法: run_vis.py --enable-vis --case-id <ID> --frozen07-dir <目录> --text-pass-receipt <路径> --out <包外输出目录>
门（任一命中exit3零产物）：未显式--enable-vis｜TEXT-PASS收据缺失/非PASS/跨案｜冻结07缺失/哈希不符/跨案｜A01-A09锚集不全或失配。
唯一语义输入=同案冻结07文本＋A01-A09锚集；不读case-views.json或任何其他案件态。"""
import sys
sys.dont_write_bytecode = True  # 公开runner卫生门：普通python3调用亦不得向包树写回pyc缓存
import os, json, hashlib, subprocess, importlib.util, shutil, stat, struct, tempfile
from pathlib import Path
import xml.etree.ElementTree as ET
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
VIEW_RENDERERS = (
    ("01-主体关系图", "render_01"),
    ("02-关键事件时间线", "render_02"),
    ("03-要件证据矩阵", "render_03"),
    ("04-阶段计划与风险", "render_04"),
)
PATH_ERRORS = (OSError, RuntimeError, ValueError)
def fsha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def hold(m): print(f"HOLD-VIS: {m}"); return 3
def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); return mod

def within(path, root):
    path, root = Path(path), Path(root)
    if path == root or root in path.parents:
        return True
    # macOS 默认大小写不敏感；仅做字符串父级比较会被 /users vs /Users 绕过。
    cursor = path
    while True:
        try:
            if cursor.exists() and os.path.samefile(cursor, root):
                return True
        except PATH_ERRORS:
            pass
        if cursor == cursor.parent:
            return False
        cursor = cursor.parent

def is_regular_file(path):
    try:
        return not path.is_symlink() and stat.S_ISREG(path.stat(follow_symlinks=False).st_mode)
    except PATH_ERRORS:
        return False

def valid_svg(path):
    if not is_regular_file(path) or path.stat().st_size == 0:
        return False
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError):
        return False
    return (root.tag.rsplit("}", 1)[-1].lower() == "svg"
            and root.attrib.get("width") == "1600"
            and root.attrib.get("height") == "900"
            and root.attrib.get("viewBox") == "0 0 1600 900")

def valid_png_1600x900(path):
    if not is_regular_file(path):
        return False
    try:
        with path.open("rb") as handle:
            header = handle.read(24)
    except OSError:
        return False
    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n":
        return False
    if header[8:12] != b"\x00\x00\x00\r" or header[12:16] != b"IHDR":
        return False
    return struct.unpack(">II", header[16:24]) == (1600, 900)

def read_json(path, label):
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError) as exc:
        return None, f"{label}不可解析:{type(exc).__name__}"

def output_target_error(path):
    try:
        if path.is_symlink():
            return "--out不得为symlink"
        if not path.exists():
            return None
        if not path.is_dir():
            return "--out已存在且不是目录"
        if any(path.iterdir()):
            return "--out已存在且非空，拒绝复用旧产物"
    except PATH_ERRORS as exc:
        return f"--out不可检查:{type(exc).__name__}"
    return None

def main():
    a = sys.argv[1:]
    def arg(n):
        if n not in a: return None
        index = a.index(n)
        return a[index + 1] if index + 1 < len(a) else None
    if "--enable-vis" not in a: return hold("VIS默认关闭：未显式--enable-vis（关闭态零产物）")
    case_id, f7d, tpr, out = arg("--case-id"), arg("--frozen07-dir"), arg("--text-pass-receipt"), arg("--out")
    if not all((case_id, f7d, tpr, out)): print(__doc__); return 2
    if any("\x00" in value for value in (case_id, f7d, tpr, out)):
        return hold("参数含NUL字符")
    root = Path(__file__).resolve().parent.parent
    try:
        out_input = Path(out).expanduser()
        if out_input.is_symlink(): return hold("--out不得为symlink")
        out = out_input.resolve()
    except PATH_ERRORS as exc:
        return hold(f"--out路径不可解析:{type(exc).__name__}")
    if within(out, root): return hold("--out须在包外")
    out_error = output_target_error(out)
    if out_error: return hold(out_error)
    # TEXT PASS绑定
    try:
        tp = Path(tpr).expanduser()
        if not tp.is_file(): return hold("TEXT-PASS收据缺失")
    except PATH_ERRORS as exc:
        return hold(f"TEXT-PASS收据路径不可解析:{type(exc).__name__}")
    tj, json_error = read_json(tp, "TEXT-PASS收据")
    if json_error: return hold(json_error)
    if not isinstance(tj, dict): return hold("TEXT-PASS收据必须为JSON对象")
    if tj.get("result") != "PASS": return hold("TEXT未过")
    if tj.get("case_id") != case_id: return hold(f"TEXT收据跨案:{tj.get('case_id')}≠{case_id}")
    # 冻结07门
    try:
        f7d_input = Path(f7d).expanduser()
        if f7d_input.is_symlink(): return hold("冻结07目录不得为symlink")
        f7d = f7d_input.resolve(strict=True)
    except PATH_ERRORS as exc:
        return hold(f"冻结07目录不可解析:{type(exc).__name__}")
    if not f7d.is_dir(): return hold("冻结07目录缺失")
    mp = f7d/"FROZEN-07-MANIFEST.json"
    try:
        if mp.is_symlink() or not mp.is_file(): return hold("冻结07 manifest缺失或为symlink")
    except PATH_ERRORS as exc:
        return hold(f"冻结07 manifest路径不可解析:{type(exc).__name__}")
    man, json_error = read_json(mp, "冻结07 manifest")
    if json_error: return hold(json_error)
    if not isinstance(man, dict): return hold("冻结07 manifest必须为JSON对象")
    if man.get("case_id") != case_id: return hold(f"冻结07跨案:{man.get('case_id')}≠{case_id}")
    md_relpath = man.get("md_relpath")
    if not isinstance(md_relpath, str) or not md_relpath or "\x00" in md_relpath:
        return hold("冻结07 md_relpath无效")
    rel = Path(md_relpath)
    if rel.is_absolute(): return hold("冻结07 md_relpath必须为相对路径")
    cursor = f7d
    try:
        for part in rel.parts:
            cursor = cursor / part
            if cursor.is_symlink(): return hold("冻结07路径不得含symlink")
        md = (f7d/rel).resolve(strict=True)
    except PATH_ERRORS as exc:
        return hold(f"冻结07缺失:{type(exc).__name__}")
    if not within(md, f7d): return hold("冻结07 md_relpath逃逸冻结目录")
    if not md.is_file(): return hold("冻结07缺失")
    md_sha256 = man.get("md_sha256")
    if not isinstance(md_sha256, str) or len(md_sha256) != 64 or any(c not in "0123456789abcdef" for c in md_sha256.lower()):
        return hold("冻结07 md_sha256无效")
    try:
        md_bytes = md.read_bytes()
    except PATH_ERRORS as exc:
        return hold(f"冻结07不可读取:{type(exc).__name__}")
    if hashlib.sha256(md_bytes).hexdigest() != md_sha256.lower(): return hold("冻结07哈希不符")
    try:
        text = md_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return hold("冻结07不是有效UTF-8")
    # 07-only构建（唯一语义输入=07文本）
    eng = root/"viz-engine"
    build_t4 = load("build_t4", eng/"mother-build_t4.py")
    render_t4 = load("render_t4", eng/"mother-render_t4.py")
    cv, err = build_t4.build_case_views(text, case_id)
    if err: return hold(f"07解析失败:{err}")
    used = set()
    for _vn, _vd in cv["views"].items():
        for _k, _items in _vd.items():
            if _k == "anchor_ids" or not isinstance(_items, list): continue
            for _it in _items:
                if isinstance(_it, dict): used |= set(_it.get("anchor_ids", []))
    if used != {f"A{i:02d}" for i in range(1, 10)}:
        return hold(f"A01-A09锚集不全或失配（实得{len(used)}项）")
    # 全部产物先写同卷唯一 staging；精确核验后才原子提交到正式输出目录。
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
    except PATH_ERRORS as exc:
        return hold(f"输出父目录不可创建:{type(exc).__name__}")
    out_error = output_target_error(out)
    if out_error: return hold(out_error)
    stage = None
    try:
        stage = Path(tempfile.mkdtemp(prefix=f".{out.name}.staging-", dir=out.parent))
        expected = set()
        for vname, renderer_name in VIEW_RENDERERS:
            renderer = getattr(render_t4, renderer_name)
            svg = renderer(cv, f"{case_id}·{vname[3:]}")
            sp = stage/f"{vname}.svg"
            sp.write_text(svg, encoding="utf-8")
            if not valid_svg(sp):
                return hold(f"{vname}SVG生成失败")
            pp = stage/f"{vname}.png"
            try:
                result = subprocess.run(
                    [CHROME, "--headless", "--disable-gpu", "--force-device-scale-factor=1", f"--screenshot={pp}",
                     "--window-size=1600,900", "--hide-scrollbars", sp.resolve().as_uri()],
                    capture_output=True, timeout=120,
                )
            except subprocess.TimeoutExpired:
                return hold(f"{vname}PNG渲染超时")
            except OSError as exc:
                return hold(f"{vname}PNG渲染器不可用:{type(exc).__name__}")
            if result.returncode != 0 or not valid_png_1600x900(pp):
                return hold(f"{vname}PNG渲染失败")
            expected.update({sp.name, pp.name})
        entries = list(stage.iterdir())
        actual = {path.name for path in entries}
        if (actual != expected or len(entries) != 8
                or not all(is_regular_file(path) for path in entries)):
            return hold(f"产物集合不闭合:expected=8 actual={len(actual)}")
        out_error = output_target_error(out)
        if out_error: return hold(f"输出提交前状态变化:{out_error}")
        try:
            os.replace(stage, out)
        except OSError as exc:
            return hold(f"输出原子提交失败:{type(exc).__name__}")
        stage = None
        print(f"VALID: {case_id} 4SVG+4PNG（07-only·九锚精确集）")
        return 0
    except Exception as exc:
        return hold(f"渲染事务失败:{type(exc).__name__}")
    finally:
        if stage is not None and stage.exists():
            shutil.rmtree(stage, ignore_errors=True)
if __name__ == "__main__": sys.exit(main())
