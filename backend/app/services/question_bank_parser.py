"""DOCX 题库解析：规则优先，保留原文与图片，异常题目进入待审核。"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import docx
from docx.oxml.ns import qn

from app.core.config import get_settings

QUESTION_START_RE = re.compile(r"^\s*(\d{1,3})\s*[.、．]\s*(?=[^\d\s])")
SECTION_RE = re.compile(
    r"^\s*[一二三四五六七八九十]+\s*[、.．]\s*(.+?)\s*[(（]\s*共\s*(\d+)\s*题[，,]\s*共\s*(\d+)\s*分\s*[)）]"
)
SECTION_RE_NO_SCORE = re.compile(r"^\s*[一二三四五六七八九十]+\s*[、.．]\s*(.+?)\s*[(（]\s*共\s*(\d+)\s*题")
OPTION_RE = re.compile(r"^\s*([A-H])\s*[.、．]\s*(.*)$")
META_RE = re.compile(
    r"^\s*(试题编号|题编号|试题类型|题型分类|标准答案|参考答案|试题难度|难易程度|试题解析|解析|评分标准|参考代码|参考程序[①-⑩]?|分值|建议得分|考生答案|考生得分|是否评分|评价描述|展示地址|是否判分|分数|题数)\s*[：:]\s*(.*)$"
)
IGNORED_META = {
    "考生答案",
    "考生得分",
    "是否评分",
    "评价描述",
    "展示地址",
    "是否判分",
}

# 行内选项：选项字母前需有空白或行首；标点后空格可有可无
INLINE_OPTION_RE = re.compile(r"\s([A-H])\s*[.、．]\s*")
INLINE_OPTION_FIRST_RE = re.compile(r"(?:^|\s)([A-H])\s*[.、．]\s*")
_INLINE_META_RE = re.compile(
    r"(试题编号|题编号|试题类型|题型分类|标准答案|参考答案|试题难度|难易程度|难度|试题解析|解析|评分标准|参考代码|参考程序|分值|建议得分)\s*[：:]"
)


def _strip_inline_meta(text: str) -> str:
    """截掉选项内容里误并入的行内元信息（如“D.xxx 标准答案：A”）。"""
    m = _INLINE_META_RE.search(text)
    return text[: m.start()].rstrip() if m else text


def _split_after_first_option(value: str) -> tuple[str, list[tuple[str, str]]]:
    """把“首个选项内容 B.内容 C.内容”里‘首个选项之后’的剩余内容拆成后续选项。

    输入为已去掉首个选项标签后的剩余文本；返回 (首个选项内容, [(后续标签, 内容), ...])。
    """
    markers = list(INLINE_OPTION_RE.finditer(value))
    if not markers:
        return value.strip(), []
    first = _strip_inline_meta(value[: markers[0].start()]).strip()
    rest: list[tuple[str, str]] = []
    for i, m in enumerate(markers):
        end = markers[i + 1].start() if i + 1 < len(markers) else len(value)
        rest.append((m.group(1), _strip_inline_meta(value[m.end():end].strip())))
    return first, rest


def _options_from_stem(stem: str) -> tuple[dict[str, str], str]:
    """若题干里内联了整段选项（以 A. 起头），抽取选项并返回 (选项表, 去掉选项后的题干)。"""
    m = INLINE_OPTION_FIRST_RE.search(stem)
    if not m or m.group(1) != "A":
        return {}, stem
    head = stem[: m.start()].rstrip()
    tail = stem[m.start():].lstrip()
    markers = list(INLINE_OPTION_FIRST_RE.finditer(tail))
    opts: dict[str, str] = {}
    for i, mm in enumerate(markers):
        end = markers[i + 1].start() if i + 1 < len(markers) else len(tail)
        opts[mm.group(1)] = _strip_inline_meta(tail[mm.end():end].strip())
    if sum(1 for v in opts.values() if v) < 2:
        return {}, stem
    return opts, head or stem


@dataclass
class ParsedLine:
    text: str = ""  # 仅去行尾空白，保留行首缩进（代码段需要）
    images: list[tuple[str, bytes, str]] = field(default_factory=list)


@dataclass
class ParsedQuestion:
    order_no: int
    type: str
    stem: str
    options: list[str] | None
    answer: Any
    analysis: str | None
    difficulty: int
    score: int
    language: str | None
    reference_code: str | None
    media: list[dict[str, str]]
    source_excerpt: str
    knowledge_points: list[str] = field(default_factory=list)


@dataclass
class ParsedPaper:
    name: str
    institution: str | None
    exam_year: int | None
    subject: str | None
    level: str | None
    total_score: int | None
    questions: list[ParsedQuestion]
    warnings: list[str]
    sections: list[dict[str, Any]]
    declared_count: int | None = None  # 文档声明的题目总数（“题数：37”等）
    issues: list[dict[str, Any]] = field(default_factory=list)


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_lines(path: Path) -> list[ParsedLine]:
    document = docx.Document(str(path))
    lines: list[ParsedLine] = []
    rel_attr = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed"
    for p in document.paragraphs:
        images: list[tuple[str, bytes, str]] = []
        for blip in p._p.findall(".//" + qn("a:blip")):
            rel_id = blip.get(rel_attr)
            if not rel_id:
                continue
            try:
                part = document.part.related_parts[rel_id]
                ext = Path(str(part.partname)).suffix or ".png"
                images.append((rel_id, part.blob, ext))
            except Exception:
                continue
        # 保留行首缩进：代码段/含代码题干的缩进依赖 leading spaces
        text = p.text.rstrip()
        if text.strip() or images:
            lines.append(ParsedLine(text=text, images=images))
    # 同时保留表格纯文本（部分真题把选项放表格里），图片暂不处理
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                text = cell.text.rstrip()
                if text.strip():
                    lines.append(ParsedLine(text=text))
    return lines


def _extract_title(lines: list[ParsedLine]) -> str:
    for line in lines:
        text = line.text.strip()
        if not text:
            continue
        if text.startswith("分数") or text.startswith("题数"):
            continue
        return text
    return "未命名题库套卷"


def _infer_meta(name: str, filename: str) -> tuple[str | None, int | None, str | None, str | None, int | None]:
    blob = f"{name} {filename}"
    subject = None
    if re.search(r"python", blob, re.I):
        subject = "Python"
    elif re.search(r"c\+\+|c语言", blob, re.I):
        subject = "C++"
    elif "图形化" in blob:
        subject = "图形化"
    elif "机器人" in blob:
        subject = "机器人"
    elif "无人机" in blob:
        subject = "无人机"

    year = None
    m = re.search(r"(20\d{2})", blob)
    if m:
        year = int(m.group(1))

    level = None
    m = re.search(r"([一二三四五六七八九十]+级)", blob)
    if m:
        level = m.group(1)

    institution = None
    if "蓝桥" in blob:
        institution = "蓝桥杯"
    elif any(k in blob for k in ("电子学会", "等级考试", "青少年软件编程", "青少年机器人")):
        institution = "中国电子学会"

    total_score = None
    m = re.search(r"共\s*(\d+)\s*分|分数[：:]\s*(\d+)", blob)
    if m:
        total_score = int(m.group(1) or m.group(2))
    return subject, year, level, institution, total_score


def _infer_type(text: str) -> str | None:
    if "单选" in text:
        return "single_choice"
    if "多选" in text:
        return "multiple_choice"
    if "判断" in text:
        return "judgement"
    if "编程" in text or "代码" in text:
        return "programming"
    if "填空" in text:
        return "code_fill"
    return None


def _normalize_answer(value: str, qtype: str) -> Any:
    text = (value or "").strip()
    if not text:
        return None
    if qtype == "single_choice":
        letters = re.findall(r"[A-H]", text.upper())
        return ord(letters[-1]) - ord("A") if letters else None
    if qtype == "multiple_choice":
        letters = re.findall(r"[A-H]", text.upper())
        return sorted({ord(c) - ord("A") for c in letters}) if letters else None
    if qtype == "judgement":
        if any(k in text for k in ("正确", "√", "对", "True", "true")):
            return True
        if any(k in text for k in ("错误", "×", "错", "False", "false")):
            return False
        return None
    return text


def _parse_difficulty(value: str) -> int:
    text = (value or "").strip()
    m = re.search(r"([1-9]|10)\s*级", text)
    if m:
        return min(10, max(1, int(m.group(1))))
    mapping = {"简单": 2, "较易": 3, "容易": 2, "一般": 5, "中等": 5, "较难": 8, "难": 9, "困难": 9}
    for key, val in mapping.items():
        if key in text:
            return val
    m = re.search(r"\d+", text)
    return min(10, max(1, int(m.group()))) if m else 3


def _language_for(subject: str | None) -> str | None:
    if subject == "Python":
        return "python"
    if subject == "C++":
        return "cpp"
    return None


def _media_url(root_url: str, name: str) -> str:
    return f"{root_url.rstrip('/')}/{name}"


def parse_docx(path: Path, *, media_dir: Path | None = None, media_url_prefix: str | None = None) -> ParsedPaper:
    """解析 DOCX，返回结构化套卷。图片保存到 media_dir，URL 使用 media_url_prefix。"""
    filename = path.name
    lines = _read_lines(path)
    title = _extract_title(lines)
    subject, year, level, institution, total_score = _infer_meta(title, filename)

    settings = get_settings()
    media_dir = media_dir or (Path(settings.UPLOAD_DIR) / "question_bank" / uuid.uuid4().hex)
    media_dir.mkdir(parents=True, exist_ok=True)
    prefix = media_url_prefix or f"/uploads/question_bank/{media_dir.name}"

    comments: list[str] = []
    issues: list[dict[str, Any]] = []

    def note(message: str, code: str, question_no: int | None = None, level: str = "warning") -> None:
        comments.append(message)
        issues.append({"code": code, "level": level, "message": message, "question_no": question_no})

    # 文档首部常声明“分数：100  题数：37”，记录它以核对拆分质量
    declared_count: int | None = None
    for line in lines[:15]:
        m = re.search(r"题数\s*[：:]\s*(\d+)", line.text) or re.search(r"共\s*(\d+)\s*题", line.text)
        if m:
            declared_count = int(m.group(1))
            break

    sections: list[dict[str, Any]] = []
    questions: list[ParsedQuestion] = []
    current_section: str | None = None
    current_type: str | None = None
    current_section_total = 0
    current_section_count = 0
    expected_no: int | None = None
    actual_by_section: dict[str, int] = {}
    image_seq = 0

    def save_images(images: list[tuple[str, bytes, str]]) -> list[str]:
        nonlocal image_seq
        urls: list[str] = []
        for _rid, blob, ext in images:
            image_seq += 1
            name = f"img_{image_seq:03d}{ext}"
            (media_dir / name).write_bytes(blob)
            urls.append(_media_url(prefix, name))
        return urls

    def default_score(qtype: str) -> int:
        if current_section_count and current_section_total:
            return max(1, round(current_section_total / current_section_count))
        return 10 if qtype == "programming" else 2

    def flush_block(block: list[ParsedLine], order_no: int) -> None:
        if not block:
            return
        qtype = current_type or "single_choice"
        stem_parts: list[str] = []
        options_map: dict[str, str] = {}
        media: list[dict[str, str]] = []
        meta: dict[str, str] = {}
        analysis_parts: list[str] = []
        code_parts: list[str] = []
        mode = "stem"
        last_opt: str | None = None
        first_text = block[0].text
        m = QUESTION_START_RE.match(first_text)
        if m:
            first_text = first_text[m.end() :].strip()
        if first_text:
            stem_parts.append(first_text)
        for img in block[0].images:
            for url in save_images([img]):
                media.append({"scope": "stem", "url": url})

        for line in block[1:]:
            text = line.text.strip()
            # raw 保留行首缩进（代码块/含代码题干缩进需要），仅去行尾空白
            raw = line.text.rstrip()
            meta_match = META_RE.match(text)
            if meta_match:
                key = meta_match.group(1)
                value = meta_match.group(2).strip()
                if key in IGNORED_META:
                    mode = "skip"
                    continue
                if key in ("参考代码", "参考程序") or key.startswith("参考程序"):
                    mode = "code"
                    if value:
                        code_parts.append(value)
                    continue
                if key in ("试题解析", "解析", "评分标准"):
                    mode = "analysis"
                    if value:
                        analysis_parts.append(f"{key}：{value}")
                    continue
                if key in ("试题编号", "题编号"):
                    meta["source_no"] = value
                    mode = "skip"
                    continue
                if key in ("试题类型", "题型分类"):
                    mapped = _infer_type(value)
                    if mapped:
                        qtype = mapped
                    meta[key] = value
                    mode = "skip"
                    continue
                if key in ("标准答案", "参考答案"):
                    if qtype == "programming" or qtype == "code_fill":
                        mode = "code"
                        if value:
                            code_parts.append(value)
                    else:
                        meta[key] = value
                        mode = "skip"
                    continue
                if key in ("试题难度", "难易程度"):
                    meta[key] = value
                    mode = "skip"
                    continue
                if key in ("分值", "建议得分"):
                    meta[key] = value
                    mode = "skip"
                    continue
                if key == "分数":
                    mode = "skip"
                    continue
                if key == "题数":
                    mode = "skip"
                    continue
                mode = "skip"
                continue

            opt_match = OPTION_RE.match(text)
            if opt_match and mode not in ("code", "analysis"):
                label = opt_match.group(1)
                value = opt_match.group(2).strip()
                options_map[label] = value
                last_opt = label
                mode = "option"
                # 若同一行内联了后续选项（“B. xx C. xx”），拆开作为独立选项
                first_val, rest_opts = _split_after_first_option(value)
                options_map[label] = first_val
                for r_label, r_value in rest_opts:
                    options_map[r_label] = r_value
                last_opt = rest_opts[-1][0] if rest_opts else label
                for url in save_images(line.images):
                    media.append({"scope": f"option:{label}", "url": url})
                continue

            if line.images:
                scope = f"option:{last_opt}" if mode == "option" and last_opt else "stem"
                for url in save_images(line.images):
                    media.append({"scope": scope, "url": url})
                if text:
                    if mode == "option" and last_opt:
                        options_map[last_opt] = (options_map[last_opt] + "\n" + text).strip()
                    elif mode == "code":
                        code_parts.append(raw)
                    elif mode == "analysis":
                        analysis_parts.append(text)
                    else:
                        stem_parts.append(text)
                continue

            if not text:
                if mode == "code":
                    code_parts.append("")
                continue
            if mode == "code":
                code_parts.append(raw)
            elif mode == "analysis":
                analysis_parts.append(text)
            elif mode == "option" and last_opt:
                options_map[last_opt] = (options_map[last_opt] + "\n" + text).strip()
            else:
                stem_parts.append(raw)

        stem = "\n".join(stem_parts).strip()
        if qtype == "judgement":
            # 判断题干尾部独立成行的「正确/错误（可带 A./B. 前缀）」属冗余选项文案，按钮已内置
            judgement_noise = re.compile(r"^\s*(?:[A-Ha-h][.、．:：)）]\s*)?(?:正确|错误|对|错|√|×)\s*$")
            cleaned = [ln.rstrip() for ln in stem.split("\n")]
            while cleaned and (not cleaned[-1].strip() or judgement_noise.match(cleaned[-1])):
                cleaned.pop()
            stem = "\n".join(cleaned).strip()
        options = None
        if qtype in ("single_choice", "multiple_choice"):
            labels = sorted(options_map.keys())
            if labels:
                max_idx = max(ord(lb) - ord("A") for lb in labels)
                options = [options_map.get(chr(ord("A") + i), "") for i in range(max_idx + 1)]
                # 去除选项值里重复标注的题标前缀（如 "A. 我爱Python"）
                options = [
                    re.sub(rf"^{chr(65 + i)}\s*[.、．:：)）]\s*", "", opt or "").strip()
                    for i, opt in enumerate(options)
                ]
            if not options and qtype in ("single_choice", "multiple_choice") and stem:
                stem_opts, new_stem = _options_from_stem(stem)
                if stem_opts:
                    labels2 = sorted(stem_opts.keys())
                    max_idx = max(ord(lb) - ord("A") for lb in labels2)
                    options = [
                        re.sub(rf"^{chr(65 + i)}\s*[.、．:：)）]\s*", "", stem_opts.get(chr(ord("A") + i), "")).strip()
                        for i in range(max_idx + 1)
                    ]
                    stem = new_stem

        answer_raw = meta.get("标准答案") or meta.get("参考答案")
        answer = _normalize_answer(answer_raw or "", qtype) if qtype not in ("programming", "code_fill") else None
        reference_code = "\n".join(code_parts).strip() or None
        if qtype in ("programming", "code_fill") and reference_code:
            answer = reference_code
        analysis = "\n".join(analysis_parts).strip() or None
        difficulty = _parse_difficulty(meta.get("试题难度") or meta.get("难易程度") or "")
        score = default_score(qtype)
        if meta.get("建议得分") or meta.get("分值"):
            m_score = re.search(r"\d+", meta.get("建议得分") or meta.get("分值") or "")
            if m_score and int(m_score.group()) > 0:
                score = int(m_score.group())
        excerpt = "\n".join(line.text for line in block if line.text).strip()

        if qtype in ("single_choice", "multiple_choice") and answer is None:
            note(f"第 {order_no} 题缺少可识别答案", "missing_answer", order_no)
        if qtype in ("programming", "code_fill") and not reference_code:
            note(f"第 {order_no} 题缺少参考代码", "missing_reference_code", order_no)
        if qtype in ("single_choice", "multiple_choice") and not options:
            note(f"第 {order_no} 题缺少选项", "missing_options", order_no)
        if qtype in ("single_choice", "multiple_choice", "judgement", "code_fill") and not analysis:
            note(f"第 {order_no} 题缺少解析", "missing_analysis", order_no)

        questions.append(
            ParsedQuestion(
                order_no=order_no,
                type=qtype,
                stem=stem,
                options=options,
                answer=answer,
                analysis=analysis,
                difficulty=difficulty,
                score=score,
                language=_language_for(subject),
                reference_code=reference_code,
                media=media,
                source_excerpt=excerpt[:4000],
            )
        )
        if current_section:
            actual_by_section[current_section] = actual_by_section.get(current_section, 0) + 1

    block: list[ParsedLine] = []
    block_looks_complete = False  # 当前块是否已出现“标准答案/解析/参考代码”等收尾元信息
    current_no = 0
    for line in lines:
        text = line.text.strip()
        section_match = SECTION_RE.match(text) or SECTION_RE_NO_SCORE.match(text)
        if section_match:
            flush_block(block, current_no)
            block = []
            block_looks_complete = False
            current_section = section_match.group(1).strip()
            current_section_count = int(section_match.group(2))
            current_section_total = (
                int(section_match.group(3)) if len(section_match.groups()) >= 3 and section_match.group(3) else 0
            )
            current_type = _infer_type(current_section)
            expected_no = None
            sections.append(
                {
                    "name": current_section,
                    "count": current_section_count,
                    "score": current_section_total,
                    "type": current_type,
                }
            )
            continue
        q_match = QUESTION_START_RE.match(text)
        if q_match:
            number = int(q_match.group(1))
            if current_section is None:
                current_section = "未分章节"
                current_section_count = 0
                current_section_total = 0
                current_type = None
                sections.append({
                    "name": current_section,
                    "count": current_section_count,
                    "score": current_section_total,
                    "type": current_type,
                })
            accept_new = False
            if not block:
                accept_new = True
            elif expected_no is not None and number == expected_no:
                accept_new = True
            elif number > current_no and block_looks_complete:
                # 文档每章编号重启（如单选 1-20，判断 1-10），且当前块已收尾，按新题拆分
                accept_new = True
            if accept_new:
                if block:
                    if expected_no is not None and number != expected_no:
                        note(f"题号从 {expected_no} 跳到 {number}，请核对是否漏题", "number_gap", number)
                    flush_block(block, current_no)
                    block_looks_complete = False
                block = [line]
                current_no = number
                expected_no = number + 1
            else:
                # 编号不连续且当前块未收尾，大概率是题干/代码/评分标准里的行内编号，归入当前题
                block.append(line)
            continue
        if block:
            block.append(line)
            meta_match = META_RE.match(text)
            if meta_match:
                key = meta_match.group(1)
                if key in {"标准答案", "参考答案", "试题解析", "解析", "评分标准", "参考代码"} or key.startswith("参考程序"):
                    block_looks_complete = True
    flush_block(block, current_no)

    if not questions:
        note("未识别到题目，请检查文档结构或使用 AI 清洗", "no_questions")
    declared_by_section: dict[str, int] = {}
    for section in sections:
        declared_by_section[section["name"]] = declared_by_section.get(section["name"], 0) + section["count"]
    for name, sec_declared in declared_by_section.items():
        parsed_count = actual_by_section.get(name, 0)
        if parsed_count != sec_declared:
            note(
                f"章节「{name}」声明 {sec_declared} 题，实际解析 {parsed_count} 题，与原文档不一致，请核对拆分",
                "section_count_mismatch",
                level="error",
            )
    if declared_count is not None and len(questions) != declared_count:
        note(
            f"文档声明 {declared_count} 题，实际解析 {len(questions)} 题，与原文档不一致，请核对题目拆分",
            "total_count_mismatch",
            level="error",
        )

    return ParsedPaper(
        name=title,
        institution=institution,
        exam_year=year,
        subject=subject,
        level=level,
        total_score=total_score or (sum(q.score for q in questions) or None),
        questions=questions,
        warnings=comments,
        sections=sections,
        declared_count=declared_count,
        issues=issues,
    )
