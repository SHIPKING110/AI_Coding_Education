#!/usr/bin/env python3
"""PPT-Master 兼容适配器（one-shot 包装）：把 ppt-master 的多步生成/编辑流程收成一条命令。

官方流程是多阶段交互式的（project_manager -> 质量门禁 -> 导出，外加确认UI/模板候选/图片获取）。
工作台模型工具预算有限，自己摸多步路由极易漏步走偏（正是"生成不稳、二次编辑崩"的诱因）。
本脚本不重写 ppt-master，只编排它自带的脚本，把最稳的链路封成单入口，生成质量与官方一致。

  build  : 质量门禁 -> 导出 pptx（一步出成品）
  edit   : 把已有 .pptx 导入为可编辑工作区(roundtrip)
  export : 对已改好的 roundtrip 工作区导出
  init   : 初始化项目目录
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import subprocess
import sys
from pathlib import Path


def _find_skill_root() -> Path:
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        if (parent / "scripts" / "svg_to_pptx.py").is_file():
            return parent
    for parent in [here.parent, *here.parents]:
        cand = parent / "ppt-master-main" / "skills" / "ppt-master"
        if (cand / "scripts" / "svg_to_pptx.py").is_file():
            return cand
    raise SystemExit("找不到 ppt-master 脚本目录（scripts/svg_to_pptx.py）")


SKILL_ROOT = _find_skill_root()
SCRIPTS = SKILL_ROOT / "scripts"
PY = sys.executable

_NUM_PREFIX = re.compile(r"^(\d+)[_\-\s]*(.*)$")


def _normalize_svg_order(project: Path) -> None:
    """导出前把 svg_output/*.svg 规范为「连续唯一」的两位序号前缀，保证页序确定。

    为什么需要：svg_to_pptx 严格按文件名排序导出。模型增/删/调序时若没重排序号，
    会出现重号（如两个 02_）——此时顺序退化为「数字相同再按整串字母序」，等于碰运气。
    本函数按「数字前缀（缺失视为最大）→ 文件名」排序后统一重编号为 01_ 02_ 03_…
    （保留原描述后缀），既消除重号，又让导出顺序与模型文件名语义一致。

    局限（诚实说明）：它只保证「确定 + 无重号」，不猜模型意图——真正的页序仍取决于
    模型给的前缀数字（SKILL.md 快速通道已要求重排序号）。二者配合才稳。
    """
    svg_dir = project / "svg_output"
    if not svg_dir.is_dir():
        return
    files = [p for p in svg_dir.iterdir() if p.is_file() and p.suffix.lower() == ".svg"]
    if len(files) <= 1:
        return

    def _key(p: Path):
        m = _NUM_PREFIX.match(p.name)
        num = int(m.group(1)) if m else 10 ** 9
        return (num, p.name.lower())

    ordered = sorted(files, key=_key)
    nums = []
    has_dup = False
    for p in ordered:
        m = _NUM_PREFIX.match(p.name)
        n = int(m.group(1)) if m else -1
        nums.append(n)
    seen = set()
    for n in nums:
        if n in seen:
            has_dup = True
        seen.add(n)
    is_consecutive = nums == list(range(1, len(nums) + 1))

    if is_consecutive and not has_dup:
        return  # 已经规范，无需改

    # 需要重排：按当前排序结果重新连续编号（先改到临时名避免命名冲突）
    plan = []
    for i, p in enumerate(ordered):
        stem = p.stem  # 文件名去扩展名，如 "02_syllabus"
        m = _NUM_PREFIX.match(stem)
        slug = (m.group(2) if m and m.group(2) else stem).strip("_- ") or stem
        new_name = f"{i + 1:02d}_{slug}.svg"
        plan.append((p, new_name))

    tmp_pairs = []
    for p, new_name in plan:
        tmp = svg_dir / (".renumber_" + p.name)
        p.rename(tmp)
        tmp_pairs.append((tmp, svg_dir / new_name))
    for tmp, dest in tmp_pairs:
        tmp.rename(dest)

    print("[已自动重排页序] 检测到 SVG 序号重复/断号，已按当前顺序重编号为 01..N：")
    for _, dn in plan:
        print("  ->", dn)


def _run(args):
    p = subprocess.run([PY, *args], cwd=str(SKILL_ROOT), capture_output=True, text=True)
    out = ((p.stdout or "") + (("\n" + p.stderr) if p.stderr else "")).strip()
    return p.returncode, out


def _tail(text, n=1600):
    return text if len(text) <= n else "..." + text[-n:]


def _newest_pptx(project):
    files = sorted(glob.glob(str(project / "**" / "*.pptx"), recursive=True),
                   key=lambda f: os.path.getmtime(f))
    return files[-1] if files else None


def _resolve_project(project: Path) -> Path:
    """容忍路径不一致：若给定 project 目录不存在，但 SKILL_ROOT 下有
    conversations/*/projects/<同名> 或 projects/<同名>，回退到实际存在且有 svg_output 的那个。

    背景：模型可能把 SVG 写到「会话隔离目录 conversations/conv_xxx/projects/X」，
    但 build 用了未隔离的「projects/X」；这里做一次确定性回退，避免"写了页却 build 空目录"。
    """
    if (project / "svg_output").is_dir():
        return project
    name = project.name
    candidates = []
    for base in [SKILL_ROOT / "projects", *list((SKILL_ROOT / "conversations").glob("*/projects"))]:
        cand = base / name
        if (cand / "svg_output").is_dir():
            # 选 svg 最近改过的那个（当前会话产物最新）
            svgs = list((cand / "svg_output").glob("*.svg"))
            mtime = max((p.stat().st_mtime for p in svgs), default=0)
            candidates.append((mtime, cand))
    if candidates:
        candidates.sort(reverse=True)
        chosen = candidates[0][1]
        print(f"[路径回退] {project} 不存在，改用 {chosen}")
        return chosen
    return project


def _sanitize_svg_colors(project: Path) -> None:
    """导出前修正模型常见的「非法颜色值」，避免质量门禁因小瑕疵整单失败。

    典型：stroke='#33island'（模型把颜色写成非法 token）、#RRGGBB 后跟杂字符等。
    规则：把 `#hex` 后面粘连的非十六进制字符截断；对明显过短/非法的 hex 回退到安全色。
    只动颜色属性值，不改结构与文案。
    """
    import re as _re

    svg_dir = project / "svg_output"
    if not svg_dir.is_dir():
        return
    color_attr = _re.compile(
        r"""(fill|stroke|color|stop-color)\s*=\s*(["'])([^"']*)(["'])""", _re.IGNORECASE
    )
    hex_ok = _re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
    fixed = 0
    for p in svg_dir.glob("*.svg"):
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        def _fix(m):
            nonlocal fixed
            attr, q1, val, q2 = m.group(1), m.group(2), m.group(3).strip(), m.group(4)
            if val.lower() in ("none", "currentcolor", "transparent") or val.startswith("url("):
                return m.group(0)
            nv = val
            if val.startswith("#"):
                # 截断到第一个非 hex 字符
                mm = _re.match(r"#([0-9a-fA-F]+)", val)
                hexpart = "#" + (mm.group(1) if mm else "")
                # 规整长度：补到 6 位（3→6 复制，其他取前6）
                h = hexpart[1:]
                if len(h) == 3:
                    h = h[0]*2 + h[1]*2 + h[2]*2
                h = h[:6] if len(h) >= 6 else (h + "0" * (6 - len(h)))
                nv = "#" + h
                if not hex_ok.match(nv):
                    nv = "#000000"
                if nv != val:
                    fixed += 1
            return f'{attr}={q1}{nv}{q2}'

        new = color_attr.sub(_fix, text)
        if new != text:
            try:
                p.write_text(new, encoding="utf-8")
            except OSError:
                pass
    if fixed:
        print(f"[颜色修正] 已规范化 {fixed} 处非法颜色值")


def _sanitize_svg_fonts(project: Path) -> None:
    """导出前修正「font-size 为 0/过小」的文本载体，避免质量门禁整单失败。

    典型：模型用 `<text font-size="0"> </text>` 当空白占位符。DrawingML 最小字号 1pt
    （输出 sz=100），font-size=0 会让 PowerPoint 判定文件需修复 → 质量门禁判 blocking error，
    整份课件 16 页写好也不出片。
    规则（保持视觉不变）：
      - 内容只有空白 → 整段 <text> 移除（本来就看不见，不留无意义载体）；
      - 内容非空但字号 < 2px → 字号改为 12（宁可可见，不让导出失败）。
    """
    import re as _re

    svg_dir = project / "svg_output"
    if not svg_dir.is_dir():
        return
    text_el = _re.compile(r"<text\b[^>]*>.*?</text>", _re.S)
    fs_attr = _re.compile(r"""font-size\s*=\s*(["'])([^"']*)(["'])""", _re.I)

    def _fs_num(tag: str) -> float | None:
        m = fs_attr.search(tag)
        if not m:
            return None
        try:
            return float(_re.match(r"\s*([0-9]*\.?[0-9]+)", m.group(2)).group(1))
        except (AttributeError, ValueError):
            return None

    fixed = 0
    for p in svg_dir.glob("*.svg"):
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        def _fix(m):
            nonlocal fixed
            el = m.group(0)
            open_tag = el[: el.index(">") + 1]
            num = _fs_num(open_tag)
            if num is None or num >= 2:
                return el
            inner = el[el.index(">") + 1 : -len("</text>")]
            if not inner.strip():
                fixed += 1
                return ""
            new_tag = fs_attr.sub(lambda mm: f"{mm.group(1)}12{mm.group(3)}", open_tag, count=1)
            fixed += 1
            return new_tag + el[len(open_tag):]

        new = text_el.sub(_fix, text)
        if new != text:
            try:
                p.write_text(new, encoding="utf-8")
            except OSError:
                pass
    if fixed:
        print(f"[字号修正] 已处理 {fixed} 处非法 font-size（0/过小）")


def _sanitize_pptx_role_ids(project: Path) -> None:
    """补齐 `data-pptx-role` 元素的稳定 id（质量门禁的唯一常见 error）。

    规则：凡带 data-pptx-role 却缺 id 的元素（背景/装饰 rect 等），按角色生成
    唯一 id（如 id="role-bg-1"）。这是「文件写了 24 页却卡在门禁出不来」的直接原因——
    完全可确定性修复，不该让用户反复催。
    """
    import re as _re

    svg_dir = project / "svg_output"
    if not svg_dir.is_dir():
        return
    elem_re = _re.compile(r"<([a-zA-Z][\w:-]*)\b([^>/]*)(/?)>")
    fixed = 0
    for p in svg_dir.glob("*.svg"):
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        used: set[str] = set(_re.findall(r'\bid\s*=\s*["\']([^"\']+)["\']', text))
        counter: dict[str, int] = {}

        def _fix(m):
            nonlocal fixed
            tag, attrs, tail = m.group(1), m.group(2), m.group(3)
            role_m = _re.search(r'data-pptx-role\s*=\s*["\']([^"\']+)["\']', attrs)
            if not role_m:
                return m.group(0)
            if _re.search(r'\bid\s*=', attrs):
                return m.group(0)
            role = _re.sub(r"[^0-9a-zA-Z-]+", "-", role_m.group(1)).strip("-") or "el"
            while True:
                counter[role] = counter.get(role, 0) + 1
                cand = f"role-{role}-{counter[role]}"
                if cand not in used:
                    break
            used.add(cand)
            fixed += 1
            return f"<{tag}{attrs} id=\"{cand}\"{tail}>"

        new = elem_re.sub(_fix, text)
        if new != text:
            try:
                p.write_text(new, encoding="utf-8")
            except OSError:
                pass
    if fixed:
        print(f"[自动修复] 已为 {fixed} 个 data-pptx-role 元素补齐稳定 id")


def _sanitize_root_bounds_overlap(project: Path) -> None:
    """解除根级模块 data-pptx-bounds 重叠（门禁 error → 降级为 warning）。

    背景：quick-generate 模式不强制要求 bounds，但两组 root <g> 的 bounds 互相重叠
    会判 error 整单卡住（模型手写坐标时很常见）。确定性修复：重叠时移除**较小**那组
    的 data-pptx-bounds 声明——缺 bounds 在非模板模式只是 warning，不阻断出片。
    """
    import re as _re

    svg_dir = project / "svg_output"
    if not svg_dir.is_dir():
        return
    fixed = 0
    for p in svg_dir.glob("*.svg"):
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        tags = list(_re.finditer(r"<g\b[^>]*>", text))
        rects: list[tuple[int, int, tuple[float, float, float, float]]] = []
        for m in tags:
            bm = _re.search(r'data-pptx-bounds\s*=\s*["\']([^"\']+)["\']', m.group(0))
            if not bm:
                continue
            try:
                nums = [float(x) for x in _re.split(r"[,\s]+", bm.group(1).strip()) if x]
            except ValueError:
                continue
            if len(nums) != 4:
                continue
            x, y, w, h = nums
            rects.append((m.start(), m.end(), (x, y, x + w, y + h)))
        drop_spans: dict[int, int] = {}
        for i, (s1, e1, r1) in enumerate(rects):
            if s1 in drop_spans:
                continue
            for s2, e2, r2 in rects[i + 1:]:
                if s2 in drop_spans:
                    continue
                ox = min(r1[2], r2[2]) - max(r1[0], r2[0])
                oy = min(r1[3], r2[3]) - max(r1[1], r2[1])
                if ox > 1 and oy > 1:  # 门禁容差 1px
                    a1 = max(1.0, (r1[2] - r1[0]) * (r1[3] - r1[1]))
                    a2 = max(1.0, (r2[2] - r2[0]) * (r2[3] - r2[1]))
                    smaller = s2 if a2 <= a1 else s1
                    if smaller not in drop_spans:
                        drop_spans[smaller] = smaller
        if not drop_spans:
            continue
        # 从后往前删，避免位移；移除较小那组的 data-pptx-bounds 属性
        new = text
        for start in sorted(drop_spans, reverse=True):
            m = next((t for t in tags if t.start() == start), None)
            if m is None:
                continue
            tag = m.group(0)
            new_tag = _re.sub(r'\s+data-pptx-bounds\s*=\s*["\'][^"\']*["\']', "", tag)
            if new_tag != tag:
                new = new[: m.start()] + new_tag + new[m.end():]
                fixed += 1
        if new != text:
            try:
                p.write_text(new, encoding="utf-8")
            except OSError:
                pass
    if fixed:
        print(f"[自动修复] 已解除 {fixed} 处 data-pptx-bounds 重叠（降级为 warning）")


def _sanitize_svg_xml(project) -> None:
    """修复最常见的 XML 非法字符问题（未转义的 & / 控制字符），避免「Invalid XML」整单失败。

    只做**无损**变换：把孤立的 `&`（不是 &amp; &lt; &gt; &quot; &apos; &#xx;）替换成 &amp;，
    并剔除 XML 1.0 不允许的控制字符。不会改动任何可见文本内容。
    """
    import re as _re

    svg_dir = project / "svg_output"
    if not svg_dir.is_dir():
        return
    ent = _re.compile(r"&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)")
    ctrl = _re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
    fixed = 0
    for p in svg_dir.glob("*.svg"):
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        new = ent.sub("&amp;", text)
        new = ctrl.sub("", new)
        if new != text:
            try:
                p.write_text(new, encoding="utf-8")
                fixed += 1
            except OSError:
                pass
    if fixed:
        print(f"[自动修复] 已修正 {fixed} 个页面的 XML 转义/控制字符")


def _sanitize_svg_overflow(project) -> None:
    """把越出画布的元素拉回 viewBox 内（质量门禁 error「exceeds the root viewBox」）。

    规则：rect 的 x/y 为负则归零，x+width / y+height 超出画布则回收到边界；
    text 的 x/y 越界则夹到画布内。只做边界回收，不改变页内相对排布逻辑。
    """
    import re as _re

    svg_dir = project / "svg_output"
    if not svg_dir.is_dir():
        return
    vb_re = _re.compile(r'viewBox\s*=\s*["\']\s*(-?[\d.]+)[,\s]+(-?[\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)')
    attr_re = _re.compile(r'(?<![\w-])(x|y|width|height)\s*=\s*["\'](-?[\d.]+)(?:px)?["\']')
    fixed = 0
    for p in svg_dir.glob("*.svg"):
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        vm = vb_re.search(text)
        if not vm:
            continue
        cx, cy, cw, ch = (float(vm.group(i)) for i in range(1, 5))
        changed = {"n": 0}

        def _fix(m):
            tag = m.group(0)
            name = _re.match(r"<([a-zA-Z][\w:-]*)", tag)
            if not name or name.group(1) not in ("rect", "text", "image"):
                return tag
            vals = {k: float(v) for k, v in attr_re.findall(tag)}
            if not vals:
                return tag
            x, y = vals.get("x", 0.0), vals.get("y", 0.0)
            w, h = vals.get("width"), vals.get("height")
            nx, ny = x, y
            if nx < cx:
                nx = cx
            if ny < cy:
                ny = cy
            if nx > cx + cw:
                nx = cx + cw
            if ny > cy + ch:
                ny = cy + ch
            nw = w
            nh = h
            if w is not None and nx + w > cx + cw:
                nw = max(1.0, cx + cw - nx)
            if h is not None and ny + h > cy + ch:
                nh = max(1.0, cy + ch - ny)
            if (nx, ny, nw, nh) == (x, y, w, h):
                return tag

            def _sub(mm):
                k, v = mm.group(1), mm.group(2)
                nv = {"x": nx, "y": ny, "width": nw, "height": nh}[k]
                if nv == v:
                    return mm.group(0)
                return f'{k}="{round(nv, 1):g}"'

            new_tag = attr_re.sub(_sub, tag)
            if new_tag != tag:
                changed["n"] += 1
            return new_tag

        new = _re.sub(r"<(?:rect|text|image)\b[^>]*>", _fix, text)
        if changed["n"]:
            try:
                p.write_text(new, encoding="utf-8")
                fixed += changed["n"]
            except OSError:
                pass
    if fixed:
        print(f"[自动修复] 已把 {fixed} 个越界元素回收到画布内")


def _sanitize_root_role(project) -> None:
    """移除根 `<svg>` 上的 data-pptx-role（门禁 error：role 只允许出现在可视子元素上）。

    模型常把 `data-pptx-role="slide"` 写到根 svg 上，触发「belongs on a visual SVG element」+
    「<svg> with data-pptx-role requires a stable id」两条 error；删掉根上的 role 即消解。
    """
    import re as _re

    svg_dir = project / "svg_output"
    if not svg_dir.is_dir():
        return
    fixed = 0
    for p in svg_dir.glob("*.svg"):
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        m = _re.search(r"<svg\b[^>]*>", text)
        if not m or "data-pptx-role" not in m.group(0):
            continue
        tag = m.group(0)
        new_tag = _re.sub(r'\s+data-pptx-role\s*=\s*["\'][^"\']*["\']', "", tag)
        if new_tag != tag:
            text = text[: m.start()] + new_tag + text[m.end():]
            try:
                p.write_text(text, encoding="utf-8")
                fixed += 1
            except OSError:
                pass
    if fixed:
        print(f"[自动修复] 已移除 {fixed} 个页面根 svg 上的 data-pptx-role")


def _sanitize_spans(project) -> None:
    """把 `<text>` 里的 `<span>` 转成 `<tspan>`（门禁 error：span 不参与原生 PPTX 导出）。

    模型常把 Markdown/HTML 习惯带进 SVG（`<text><span font-weight>…</span></text>`），
    质量门禁与导出都判不支持。`tspan` 是 SVG 标准文本分片，样式能力等价；
    文本块之外的残留 span 直接解包（去标签留内容）。
    """
    import re as _re

    svg_dir = project / "svg_output"
    if not svg_dir.is_dir():
        return
    text_el = _re.compile(r"<text\b[^>]*>.*?</text>", _re.S)
    fixed = 0
    for p in svg_dir.glob("*.svg"):
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        def _conv(m):
            nonlocal fixed
            el = m.group(0)
            new = _re.sub(r"<span\b", "<tspan", el)
            new = new.replace("</span>", "</tspan>")
            if new != el:
                fixed += 1
            return new

        new = text_el.sub(_conv, text)
        # 文本块外残留的 span：去标签留内容（避免再触发 Unsupported element）
        new = _re.sub(r"</?span\b[^>]*>", "", new)
        if new != text:
            try:
                p.write_text(new, encoding="utf-8")
            except OSError:
                pass
    if fixed:
        print(f"[自动修复] 已把 {fixed} 个文本块内的 span 转为 tspan")


def _sanitize_filters(project) -> None:
    """移除 `<g>` 上的 filter（门禁 error：filter 只允许在 rect/circle/image/path/polygon/text 等原生目标）。

    模型喜欢给分组加模糊/发光滤镜（`<g filter="url(#blur)">`），但导出只认叶子图形上的滤镜。
    确定性修复：删掉 `<g>` 上的 filter 属性（视觉略损失，但保证整份能出片）。
    """
    import re as _re

    svg_dir = project / "svg_output"
    if not svg_dir.is_dir():
        return
    fixed = 0
    g_tag = _re.compile(r"<g\b[^>]*>")
    for p in svg_dir.glob("*.svg"):
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        def _fix(m):
            nonlocal fixed
            tag = m.group(0)
            if not _re.search(r"\bfilter\s*=", tag):
                return tag
            new_tag = _re.sub(r'\s+filter\s*=\s*["\'][^"\']*["\']', "", tag)
            if new_tag != tag:
                fixed += 1
            return new_tag

        new = g_tag.sub(_fix, text)
        if new != text:
            try:
                p.write_text(new, encoding="utf-8")
            except OSError:
                pass
    if fixed:
        print(f"[自动修复] 已移除 {fixed} 处 <g> 上的 filter（不被原生导出支持）")


def _text_estimate_width(label: str, font_size: float) -> float:
    """粗估文本渲染宽度（中文/全角按 1em，西文按字宽比例）——用于越界收缩。"""
    import unicodedata

    units = 0.0
    for ch in label:
        if ch.isspace():
            units += 0.32
        elif unicodedata.east_asian_width(ch) in ("W", "F"):
            units += 1.0
        elif ch.isdigit():
            units += 0.56
        elif ch.isupper():
            units += 0.64
        else:
            units += 0.55
    return max(1.0, units * max(font_size, 1.0))


def _sanitize_text_fit(project) -> None:
    """文本越出画布（门禁 error「exceeds the root viewBox」）：按估算宽度缩字号/夹坐标。

    旧逻辑只夹 x 坐标，没考虑文本自身宽度（如 font-size 180 的「C++」）。这里：
      - 按 text-anchor 估算文本左右边界；右侧越界 → 等比缩小 font-size（≥12px）；
      - 纵向 y 超界 → 夹回画布。
    """
    import re as _re

    svg_dir = project / "svg_output"
    if not svg_dir.is_dir():
        return
    vb_re = _re.compile(r'viewBox\s*=\s*["\']\s*(-?[\d.]+)[,\s]+(-?[\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)')
    fs_re = _re.compile(r"""font-size\s*=\s*["']([0-9.]+)(?:px)?["']""")
    x_re = _re.compile(r"""(?<![\w-])x\s*=\s*["'](-?[0-9.]+)["']""")
    y_re = _re.compile(r"""(?<![\w-])y\s*=\s*["'](-?[0-9.]+)["']""")
    anchor_re = _re.compile(r"""text-anchor\s*=\s*["'](start|middle|end)["']""")
    fixed = 0
    for p in svg_dir.glob("*.svg"):
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        vm = vb_re.search(text)
        if not vm:
            continue
        cx, cy, cw, ch = (float(vm.group(i)) for i in range(1, 5))
        right, bottom = cx + cw, cy + ch

        def _fix(m):
            nonlocal fixed
            el = m.group(0)
            open_tag = el[: el.index(">") + 1]
            fm = fs_re.search(open_tag)
            if not fm:
                return el
            fs = float(fm.group(1))
            if fs < 2:
                return el
            xm = x_re.search(open_tag)
            ym = y_re.search(open_tag)
            am = anchor_re.search(open_tag)
            x = float(xm.group(1)) if xm else cx
            y = float(ym.group(1)) if ym else cy
            anchor = am.group(1) if am else "start"
            label = _re.sub(r"<[^>]+>", "", el[el.index(">") + 1: el.rfind("</text>")])
            label = label.strip()
            if not label:
                return el
            changed = False
            # 横向：按估宽收缩字号，直到右边不越界
            width = _text_estimate_width(label, fs)
            left = x if anchor == "start" else (x - width / 2 if anchor == "middle" else x - width)
            if left + width > right and left < right:
                new_fs = max(12.0, fs * (right - left) / width)
                if new_fs < fs:
                    open_tag2 = fs_re.sub(f'font-size="{round(new_fs, 1):g}"', open_tag, count=1)
                    if open_tag2 != open_tag:
                        open_tag = open_tag2
                        fs = new_fs
                        changed = True
            elif left < cx:
                # 文本整体越出左边界：以左边界为起点（start 锚点直接右移）
                if anchor == "start":
                    open_tag2 = x_re.sub(f'x="{round(cx, 1):g}"', open_tag, count=1)
                    if open_tag2 != open_tag:
                        open_tag = open_tag2
                        changed = True
            # 纵向：基线上沿不要越过画布顶部/底部
            if y > bottom:
                open_tag2 = y_re.sub(f'y="{round(bottom, 1):g}"', open_tag, count=1)
                if open_tag2 != open_tag:
                    open_tag = open_tag2
                    changed = True
            elif y - fs < cy:
                ny = cy + fs
                if ny > bottom:
                    ny = bottom
                open_tag2 = y_re.sub(f'y="{round(ny, 1):g}"', open_tag, count=1)
                if open_tag2 != open_tag:
                    open_tag = open_tag2
                    changed = True
            if changed:
                fixed += 1
                return open_tag + el[len(open_tag):]
            return el

        new = _re.sub(r"<text\b[^>]*>.*?</text>", _fix, text, flags=_re.S)
        if new != text:
            try:
                p.write_text(new, encoding="utf-8")
            except OSError:
                pass
    if fixed:
        print(f"[自动修复] 已收缩/回收到画布内的越界文本 {fixed} 处")


def _ensure_spec_lock(project) -> None:
    """保证 `spec_lock.md` 有 typography 的 title/body 行（Master 导出硬性要求）。

    模型跳过 spec_lock 时导出会报「Master export requires spec_lock.md typography…」。
    确定性补全：缺文件就建最小版；已有文件缺行就在 `## typography` 段补默认值。
    """
    import re as _re

    lock = project / "spec_lock.md"
    default = (
        "# Spec Lock\n\n## typography\n"
        "- title: 44\n- body: 22\n\n## colors\n- primary: #0E1B2C\n- accent: #F0902E\n"
    )
    try:
        if not lock.is_file():
            lock.write_text(default, encoding="utf-8")
            print("[自动修复] 已补建 spec_lock.md（typography title/body）")
            return
        text = lock.read_text(encoding="utf-8", errors="ignore")
        rows = dict(_re.findall(r"^-\s+([A-Za-z0-9_]+)\s*:\s*(.+?)\s*$", text, _re.M))
        missing = [k for k in ("title", "body") if k not in rows]
        if not missing:
            return
        add = "".join(
            f"- {k}: {44 if k == 'title' else 22}\n" for k in missing
        )
        if _re.search(r"^##\s*typography\s*$", text, _re.M):
            text = _re.sub(
                r"(^##\s*typography\s*$\n(?:[^\n#].*\n)*)",
                lambda m: m.group(1) + add,
                text, count=1, flags=_re.M,
            )
        else:
            text = text.rstrip() + "\n\n## typography\n" + add
        lock.write_text(text, encoding="utf-8")
        print(f"[自动修复] 已补全 spec_lock.md typography 行：{', '.join(missing)}")
    except OSError:
        pass


def _qc_errors_only(out: str) -> bool:
    """从质量检查输出判断「是否只有 warning、没有 error」。

    返回 True 表示可放行导出（仅有 warning / 仅 passed:0 但 errors:0）。
    """
    import re as _re
    txt = out or ""
    # 抓 JSON 摘要里的 errors 计数（--json 会带 summary）
    m = _re.search(r'"errors"\s*:\s*(\d+)', txt)
    if m:
        try:
            return int(m.group(1)) == 0
        except ValueError:
            return False
    # 无 json 摘要时，按关键字判断：出现 ERROR 视为阻断
    return not _re.search(r"\[ERROR\]|\berrors?\s*[:：]\s*[1-9]", txt, _re.IGNORECASE)


def _print_pages(project) -> None:
    """回执「本次成品包含的全部页」（按导出顺序）：让后端据此刷新工作区大纲，
    保证调整后的大纲/预览覆盖整份成品，而不只是本次改动过的页。"""
    import re as _re

    svg_dir = project / "svg_output"
    if not svg_dir.is_dir():
        return
    files = [p for p in svg_dir.iterdir() if p.is_file() and p.suffix.lower() == ".svg"]
    if not files:
        return

    def _key(p):
        m = _re.match(r"^(\d+)", p.name)
        return (int(m.group(1)) if m else 10 ** 9, p.name.lower())

    names = [p.name for p in sorted(files, key=_key)]
    print("[PAGES]" + ",".join(names))


def _repair_pass(project) -> None:
    """一轮确定性自愈：按质量门禁已知 error 模式依次修复（顺序即依赖：先结构后几何）。"""
    _sanitize_svg_xml(project)
    _sanitize_spans(project)
    _sanitize_svg_colors(project)
    _sanitize_svg_fonts(project)
    _sanitize_filters(project)
    _sanitize_pptx_role_ids(project)
    _sanitize_root_role(project)
    _sanitize_root_bounds_overlap(project)
    _sanitize_svg_overflow(project)
    _sanitize_text_fit(project)
    _ensure_spec_lock(project)


def cmd_build(args):
    project = _resolve_project(Path(args.project).resolve())
    _normalize_svg_order(project)
    _repair_pass(project)
    qc = [str(SCRIPTS / "svg_quality_checker.py"), str(project),
          "--quick-generate", "--canonical-authoring", "--stage", "final", "--json"]
    code, out = _run(qc)
    # 质量门禁：**仅 warning 不阻断出片**（errors:0 即放行）；只有存在 error 才停。
    # 自愈：报 error 时再走一轮确定性修复并复检（多轮，最多 3 次）——用户要的是成品，
    # 不该因可自动修的规范问题反复卡住、反复找用户确认。
    for attempt in range(3):
        if code == 0 or _qc_errors_only(out):
            break
        print(f"[质量检查发现 error，自动修复第 {attempt + 1} 轮并复检]")
        _repair_pass(project)
        code, out = _run(qc)
    if code != 0 and not _qc_errors_only(out):
        print("[质量检查未通过（自动修复后仍有 error）]\n" + _tail(out))
        return code
    if code != 0:
        print("[质量检查：仅有 warning，已放行出片]\n" + _tail(out)[:600])
    # 导出（--quick-generate 自带宽松导出；不能再叠 --enable-dangerous-nonconforming，二者冲突）
    code, out = _run([str(SCRIPTS / "svg_to_pptx.py"), str(project), "--quick-generate"])
    print(_tail(out))
    if code != 0:
        return code
    _print_pages(project)
    pptx = _newest_pptx(project)
    if pptx:
        print("\n[PPTX]" + pptx)
    return 0


def cmd_edit(args):
    src = Path(args.pptx).resolve()
    project = Path(args.project).resolve()
    if not src.is_file():
        print("[错误] 源 pptx 不存在：" + str(src))
        return 2
    code, out = _run([str(SCRIPTS / "pptx_to_svg.py"), str(src), "-o", str(project),
                      "--inheritance-mode", "both", "--roundtrip"])
    print(_tail(out))
    return code


def cmd_export(args):
    project = Path(args.project).resolve()
    code, out = _run([str(SCRIPTS / "svg_to_pptx.py"), str(project), "--roundtrip"])
    print(_tail(out))
    if code != 0:
        return code
    pptx = _newest_pptx(project)
    if pptx:
        print("\n[PPTX]" + pptx)
    return 0


def cmd_init(args):
    code, out = _run([str(SCRIPTS / "project_manager.py"), "init", args.name])
    print(_tail(out))
    return code


def main():
    ap = argparse.ArgumentParser(description="PPT-Master 兼容适配器（one-shot）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="质量门禁 + 导出 pptx")
    b.add_argument("project")
    b.set_defaults(func=cmd_build)
    e = sub.add_parser("edit", help="把已有 pptx 导入为可编辑工作区")
    e.add_argument("pptx")
    e.add_argument("project")
    e.set_defaults(func=cmd_edit)
    x = sub.add_parser("export", help="对改好的工作区做 roundtrip 导出")
    x.add_argument("project")
    x.set_defaults(func=cmd_export)
    i = sub.add_parser("init", help="初始化项目目录")
    i.add_argument("name")
    i.set_defaults(func=cmd_init)
    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
