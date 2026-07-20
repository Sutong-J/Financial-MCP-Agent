from __future__ import annotations

import re
from dataclasses import dataclass, field

MAX_CHUNK_SIZE = 900
MIN_CHUNK_SIZE = 80
MIN_NO_SPLIT = 400
SEARCH_WINDOW = 150

HEADING_RE = re.compile(r"^(#{1,3})\s+(.+)$")
CODE_FENCE_RE = re.compile(r"^```")

PROTECTED_PATTERNS = (
    r"\d+\.\d+%?",
    r"\d{4}[-年/]\d{1,2}[-月/]\d{1,2}日?",
    r"(?:sh|sz)\.\d{6}",
    r"\b\d{6}\b",
    r"\d+\.?\d*[万亿千百]?元",
    r"\d+[）.)]",
)

CUT_PRIORITY = (
    ("\n\n", 5),
    ("。\n", 4),
    ("！\n", 4),
    ("？\n", 4),
    ("\n- ", 3),
    ("\n* ", 3),
    ("\n|", 3),
    ("；", 2),
    ("，", 1),
    ("\n", 1),
    (" ", 0),
)


@dataclass
class RagChunk:
    text: str
    heading: str = ""
    heading_level: int = 0
    breadcrumb: str = ""
    heading_slug: str = "_root_"
    chunk_index: int = 0

    @property
    def char_count(self) -> int:
        return len(self.text)


@dataclass
class _Section:
    level: int
    heading: str
    parent_heading: str = ""
    body: str = ""
    children: list[_Section] = field(default_factory=list)


def chunk_for_rag(
    text: str,
    *,
    source: str = "",
    source_label: str = "",
    company_name: str = "",
    stock_code: str = "",
    max_chunk_size: int = MAX_CHUNK_SIZE,
    min_chunk_size: int = MIN_CHUNK_SIZE,
    min_no_split: int = MIN_NO_SPLIT,
) -> list[RagChunk]:
    """按 Markdown 标题优先切分，超长章节在安全边界子切，并注入检索前缀。"""
    text = (text or "").strip()
    if not text:
        return []

    if len(text) <= min_no_split and not _has_markdown_headings(text):
        return [_finalize_chunk(text, heading="", breadcrumb="", chunk_index=0, meta_kwargs={
            "source": source,
            "source_label": source_label,
            "company_name": company_name,
            "stock_code": stock_code,
        })]

    sections = _parse_markdown_sections(text)
    if sections:
        raw_chunks = _chunk_sections(sections, max_chunk_size=max_chunk_size, min_chunk_size=min_chunk_size)
    else:
        raw_chunks = _chunk_plain_text(text, max_chunk_size=max_chunk_size, min_chunk_size=min_chunk_size)

    meta = {
        "source": source,
        "source_label": source_label,
        "company_name": company_name,
        "stock_code": stock_code,
    }
    return [
        _finalize_chunk(
            chunk.text,
            heading=chunk.heading,
            breadcrumb=chunk.breadcrumb,
            chunk_index=index,
            meta_kwargs=meta,
        )
        for index, chunk in enumerate(raw_chunks)
    ]


def chunk_text(text: str, *, chunk_size: int = 600, overlap: int = 80) -> list[str]:
    """兼容旧接口：返回纯文本块列表。"""
    scale = MAX_CHUNK_SIZE / 600 if chunk_size else 1
    chunks = chunk_for_rag(
        text,
        max_chunk_size=chunk_size or MAX_CHUNK_SIZE,
        min_chunk_size=min(MIN_CHUNK_SIZE, max(20, chunk_size // 8)),
        min_no_split=max(chunk_size, MIN_NO_SPLIT),
    )
    return [chunk.text for chunk in chunks]


def _has_markdown_headings(text: str) -> bool:
    for line in text.splitlines():
        if HEADING_RE.match(line.strip()):
            return True
    return False


def _parse_markdown_sections(text: str) -> list[_Section]:
    lines = text.splitlines()
    h2_sections: list[_Section] = []
    current_h2: _Section | None = None
    current_h3: _Section | None = None
    preamble: list[str] = []
    in_code_block = False

    def flush_h3() -> None:
        nonlocal current_h3
        if current_h2 is not None and current_h3 is not None:
            current_h2.children.append(current_h3)
        current_h3 = None

    def flush_h2() -> None:
        nonlocal current_h2
        flush_h3()
        if current_h2 is not None:
            h2_sections.append(current_h2)
        current_h2 = None

    for line in lines:
        stripped = line.strip()
        if CODE_FENCE_RE.match(stripped):
            in_code_block = not in_code_block

        heading_match = None if in_code_block else HEADING_RE.match(stripped)
        if heading_match:
            level = len(heading_match.group(1))
            heading = heading_match.group(2).strip()
            if level == 1:
                continue
            if level == 2:
                flush_h2()
                current_h2 = _Section(level=2, heading=heading)
                current_h3 = None
                continue
            if level == 3:
                flush_h3()
                parent = current_h2.heading if current_h2 else ""
                current_h3 = _Section(level=3, heading=heading, parent_heading=parent)
                continue

        if current_h3 is not None:
            current_h3.body = _append_line(current_h3.body, line)
        elif current_h2 is not None:
            current_h2.body = _append_line(current_h2.body, line)
        else:
            preamble.append(line)

    flush_h2()

    if preamble and h2_sections:
        h2_sections[0].body = _append_line("\n".join(preamble).strip(), h2_sections[0].body)
    elif preamble and not h2_sections:
        return [_Section(level=0, heading="", body="\n".join(preamble).strip())]

    return h2_sections


def _chunk_sections(
    sections: list[_Section],
    *,
    max_chunk_size: int,
    min_chunk_size: int,
) -> list[RagChunk]:
    chunks: list[RagChunk] = []

    for section in sections:
        if section.children:
            child_chunks: list[RagChunk] = []
            if section.body.strip():
                child_chunks.extend(
                    _chunk_body(
                        section.body,
                        heading=section.heading,
                        breadcrumb=section.heading,
                        max_chunk_size=max_chunk_size,
                        min_chunk_size=min_chunk_size,
                    )
                )
            for child in section.children:
                breadcrumb = f"{section.heading} > {child.heading}" if section.heading else child.heading
                child_chunks.extend(
                    _chunk_body(
                        child.body,
                        heading=child.heading,
                        breadcrumb=breadcrumb,
                        max_chunk_size=max_chunk_size,
                        min_chunk_size=min_chunk_size,
                    )
                )
            chunks.extend(_merge_tiny_chunks(child_chunks, min_chunk_size=min_chunk_size))
            continue

        section_text = _section_text(section)
        chunks.extend(
            _chunk_body(
                section_text,
                heading=section.heading,
                breadcrumb=section.heading,
                max_chunk_size=max_chunk_size,
                min_chunk_size=min_chunk_size,
            )
        )

    return _merge_tiny_chunks(chunks, min_chunk_size=min_chunk_size)


def _chunk_plain_text(
    text: str,
    *,
    max_chunk_size: int,
    min_chunk_size: int,
) -> list[RagChunk]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[RagChunk] = []
    buffer = ""

    for para in paragraphs:
        if len(para) > max_chunk_size:
            if buffer:
                chunks.append(RagChunk(text=buffer.strip()))
                buffer = ""
            chunks.extend(
                _chunk_body(
                    para,
                    heading="",
                    breadcrumb="",
                    max_chunk_size=max_chunk_size,
                    min_chunk_size=min_chunk_size,
                )
            )
            continue

        candidate = f"{buffer}\n\n{para}".strip() if buffer else para
        if len(candidate) <= max_chunk_size:
            buffer = candidate
        else:
            if buffer:
                chunks.append(RagChunk(text=buffer.strip()))
            buffer = para

    if buffer:
        chunks.append(RagChunk(text=buffer.strip()))

    return _merge_tiny_chunks(chunks, min_chunk_size=min_chunk_size)


def _chunk_body(
    body: str,
    *,
    heading: str,
    breadcrumb: str,
    max_chunk_size: int,
    min_chunk_size: int,
) -> list[RagChunk]:
    body = (body or "").strip()
    if not body:
        return []

    display = _format_section_content(heading, body)
    if len(display) <= max_chunk_size:
        return [RagChunk(text=display, heading=heading, breadcrumb=breadcrumb, heading_level=_heading_level(heading))]

    parts = _safe_split(body, max_chunk_size=max_chunk_size)
    return [
        RagChunk(
            text=_format_section_content(heading, part),
            heading=heading,
            breadcrumb=breadcrumb,
            heading_level=_heading_level(heading),
            chunk_index=index,
        )
        for index, part in enumerate(parts)
    ]


def _safe_split(text: str, *, max_chunk_size: int) -> list[str]:
    protected = _find_protected_spans(text)
    parts: list[str] = []
    start = 0
    text_len = len(text)

    while start < text_len:
        remaining = text_len - start
        if remaining <= max_chunk_size:
            parts.append(text[start:].strip())
            break

        target = start + max_chunk_size
        cut = _find_safe_cut(text, target, protected=protected)
        if cut <= start:
            cut = min(start + max_chunk_size, text_len)

        parts.append(text[start:cut].strip())
        if cut >= text_len:
            break

        overlap_start = _find_overlap_start(text, start, cut)
        start = overlap_start if overlap_start > start else cut

    return [part for part in parts if part]


def _find_protected_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for pattern in PROTECTED_PATTERNS:
        for match in re.finditer(pattern, text):
            spans.append((match.start(), match.end()))
    if not spans:
        return []
    spans.sort()
    merged = [spans[0]]
    for start, end in spans[1:]:
        prev_start, prev_end = merged[-1]
        if start <= prev_end:
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))
    return merged


def _is_in_protected(pos: int, protected: list[tuple[int, int]]) -> bool:
    return any(start < pos < end for start, end in protected)


def _find_safe_cut(text: str, target: int, *, protected: list[tuple[int, int]]) -> int:
    lower = max(1, target - SEARCH_WINDOW)
    candidates: list[tuple[int, int]] = []

    for delimiter, score in CUT_PRIORITY:
        search_start = lower
        while True:
            idx = text.rfind(delimiter, search_start, target)
            if idx < 0:
                break
            cut = idx + len(delimiter)
            if cut <= 0 or _is_in_protected(cut, protected):
                search_start = idx - 1
                if search_start < 0:
                    break
                continue
            candidates.append((score, cut))
            search_start = idx - 1

    if candidates:
        candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return candidates[0][1]

    cut = min(target, len(text))
    while cut > lower and _is_in_protected(cut, protected):
        cut -= 1
    return cut


def _find_overlap_start(text: str, start: int, cut: int) -> int:
    paragraph_break = text.rfind("\n\n", start, cut)
    if paragraph_break >= start:
        return paragraph_break + 2
    sentence_break = max(text.rfind("。\n", start, cut), text.rfind("！", start, cut), text.rfind("？", start, cut))
    if sentence_break >= start:
        return sentence_break + 1
    return cut


def _merge_tiny_chunks(chunks: list[RagChunk], *, min_chunk_size: int) -> list[RagChunk]:
    if not chunks:
        return []

    merged: list[RagChunk] = []
    for chunk in chunks:
        if merged and len(chunk.text) < min_chunk_size:
            prev = merged[-1]
            if prev.heading == chunk.heading and prev.breadcrumb == chunk.breadcrumb:
                prev.text = f"{prev.text}\n\n{chunk.text}".strip()
                continue
        merged.append(RagChunk(
            text=chunk.text,
            heading=chunk.heading,
            breadcrumb=chunk.breadcrumb,
            heading_level=chunk.heading_level,
            heading_slug=chunk.heading_slug,
            chunk_index=chunk.chunk_index,
        ))
    return merged


def _finalize_chunk(
    text: str,
    *,
    heading: str,
    breadcrumb: str,
    chunk_index: int,
    meta_kwargs: dict[str, str],
) -> RagChunk:
    slug = _heading_slug(heading or breadcrumb)
    prefix = _build_prefix(
        source_label=meta_kwargs.get("source_label", ""),
        breadcrumb=breadcrumb or heading,
        company_name=meta_kwargs.get("company_name", ""),
        stock_code=meta_kwargs.get("stock_code", ""),
    )
    return RagChunk(
        text=f"{prefix}{text}".strip(),
        heading=heading,
        heading_level=_heading_level(heading),
        breadcrumb=breadcrumb or heading,
        heading_slug=slug,
        chunk_index=chunk_index,
    )


def _build_prefix(
    *,
    source_label: str,
    breadcrumb: str,
    company_name: str,
    stock_code: str,
) -> str:
    parts: list[str] = []
    if source_label:
        parts.append(f"来源: {source_label}")
    if breadcrumb:
        parts.append(f"章节: {breadcrumb}")
    if company_name:
        target = company_name if not stock_code else f"{company_name} {stock_code}"
        parts.append(f"标的: {target}")
    if not parts:
        return ""
    return f"[{' | '.join(parts)}]\n\n"


def _heading_slug(heading: str) -> str:
    if not heading:
        return "_root_"
    slug = re.sub(r"[^\w\u4e00-\u9fff]+", "-", heading.strip()).strip("-")
    return slug[:40] or "_root_"


def _heading_level(heading: str) -> int:
    return 2 if heading else 0


def _section_text(section: _Section) -> str:
    if section.heading:
        return section.body.strip()
    return section.body.strip()


def _format_section_content(heading: str, body: str) -> str:
    body = body.strip()
    if heading:
        return f"## {heading}\n\n{body}" if body else f"## {heading}"
    return body


def _append_line(existing: str, line: str) -> str:
    if not existing:
        return line
    return f"{existing}\n{line}"


def make_chunk_id(session_id: str, source: str, chunk: RagChunk) -> str:
    return f"{session_id}:{source}:{chunk.heading_slug}:{chunk.chunk_index}"
