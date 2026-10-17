"""按 PRD 3.3「按业务文档类型的分块规则」切块。

每种知识类型只用一种策略；长度为估算 token（中文按字、英文按词 × 1.3），
与 text-embedding-v4 实际计数有偏差，仅用于控制块大小。
"""
import re
from dataclasses import dataclass, field

STRATEGIES = {
    "rule": {
        "label": "平台规则/制度/合同",
        "strategy": "按结构（章 → 节 → 条）",
        "size": "子块 200–400，不重叠；父块 ≤1,500",
        "parent_child": "父块 = 所在小节，子块 = 单条条款",
    },
    "guide": {
        "label": "帮助文档/操作指南/SOP",
        "strategy": "递归分块（标题 → 段落 → 句子）",
        "size": "500，重叠 50",
        "parent_child": "否",
    },
    "manual": {
        "label": "商品手册/研究资料",
        "strategy": "递归分块（标题 → 段落 → 句子）",
        "size": "800，重叠 100",
        "parent_child": "否",
    },
    "table": {
        "label": "说明类表格",
        "strategy": "按内容类型：转 Markdown 后按行组切",
        "size": "每块 ≤20 行，每块重复表头",
        "parent_child": "否",
    },
    "data_table": {
        "label": "数据表格",
        "strategy": "结构化抽取（商品目录 / 价格 / 运价 / 成本）：表头映射为标准字段，逐行写入业务表",
        "size": "不切块；商品目录每个 SKU 另生成 1 条描述块，其余不向量化",
        "parent_child": "否",
    },
    "qa": {
        "label": "标准问答",
        "strategy": "按内容类型：一条问答为一块，同时抽取标准问、相似问、答案写入 QA 库",
        "size": "整条不切，不重叠",
        "parent_child": "否",
    },
    "case": {
        "label": "案例/会话",
        "strategy": "按内容类型：问题 → 证据 → 处理 → 结果为一块",
        "size": "≤1,000，不重叠",
        "parent_child": "仅超长时：父块 = 完整案例，子块 = 单个阶段",
    },
}

_CJK = re.compile(r"[\u3400-\u9fff\uf900-\ufaff\u3000-\u303f\uff00-\uffef]")
_WORD = re.compile(r"[A-Za-z0-9_]+")
_PAGE = re.compile(r"^<!-- p:(\d+) -->$")
_HEAD = re.compile(r"^(#{1,6})\s+(.+?)\s*#*$")
_CLAUSE_LEVELS = [
    re.compile(r"^\s*第[一二三四五六七八九十百零〇\d]+条"),
    re.compile(r"^\s*[一二三四五六七八九十]+、"),
    re.compile(r"^\s*\d+(\.\d+)*[\.、]\s*\S"),
    re.compile(r"^\s*[（(][一二三四五六七八九十\d]+[）)]"),
]
_QUESTION = re.compile(r"^\s*(\*\*)?\s*(Q\d*|问|问题)\s*[:：]")
_STAGE = re.compile(r"^\s*(\*\*)?\s*【?(问题|背景|证据|处理|处理过程|结果|结论|复盘)】?\s*[:：]")


def ntok(text: str) -> int:
    return len(_CJK.findall(text)) + int(len(_WORD.findall(text)) * 1.3)


@dataclass
class Section:
    path: list[str]
    page: int | None
    text: str


@dataclass
class Chunk:
    kind: str  # parent / child / normal
    text: str
    heading_path: str
    page: int | None
    rows: str = ""
    parent: int | None = None  # 父块在本次结果列表中的下标
    tokens: int = field(init=False)

    def __post_init__(self):
        self.tokens = ntok(self.text)

    @property
    def locator(self) -> str:
        parts = []
        if self.page:
            parts.append(f"p{self.page}")
        if self.heading_path:
            parts.append(self.heading_path)
        if self.rows:
            parts.append(self.rows)
        return "；".join(parts)


def sections(md: str) -> list[Section]:
    out: list[Section] = []
    path: list[str] = []
    page: int | None = None
    start_page: int | None = None
    buf: list[str] = []

    def flush():
        text = "\n".join(buf).strip()
        if text:
            out.append(Section(list(path), start_page, text))
        buf.clear()

    for line in md.splitlines():
        if m := _PAGE.match(line.strip()):
            page = int(m.group(1))
            if not buf:
                start_page = page
            continue
        if m := _HEAD.match(line):
            flush()
            level = len(m.group(1))
            path = path[: level - 1] + [m.group(2).strip()]
            start_page = page
            continue
        if not buf:
            start_page = page
        buf.append(line)
    flush()
    return out


def _split_keep(text: str, sep: str) -> list[str]:
    parts = re.split(f"(?<={re.escape(sep)})", text)
    return [p for p in parts if p]


def _pieces(text: str, size: int, seps: list[str]) -> list[str]:
    if ntok(text) <= size:
        return [text]
    for i, sep in enumerate(seps):
        if sep in text:
            res: list[str] = []
            for p in _split_keep(text, sep):
                res += _pieces(p, size, seps[i + 1 :]) if ntok(p) > size else [p]
            return res
    step = max(size, 1)
    return [text[i : i + step] for i in range(0, len(text), step)]


def recursive(text: str, size: int, overlap: int) -> list[str]:
    pieces = _pieces(text, size, ["\n\n", "\n", "。", "；", "！", "？", ". ", "，", " "])
    chunks: list[str] = []
    cur: list[str] = []
    for p in pieces:
        if cur and ntok("".join(cur) + p) > size:
            chunks.append("".join(cur).strip())
            tail: list[str] = []
            t = 0
            for q in reversed(cur):
                if t + ntok(q) > overlap:
                    break
                tail.insert(0, q)
                t += ntok(q)
            cur = tail
        cur.append(p)
    if cur and "".join(cur).strip():
        chunks.append("".join(cur).strip())
    return [c for c in chunks if c]


def _group_lines(lines: list[str], is_start) -> list[str]:
    groups: list[list[str]] = []
    for ln in lines:
        if is_start(ln) or not groups:
            groups.append([ln])
        else:
            groups[-1].append(ln)
    return ["\n".join(g).strip() for g in groups if "\n".join(g).strip()]


def _rule(secs: list[Section]) -> list[Chunk]:
    out: list[Chunk] = []
    for s in secs:
        hp = " > ".join(s.path)
        for parent_text in recursive(s.text, 1500, 0):
            lines = parent_text.splitlines()
            clauses = [parent_text]
            for pat in _CLAUSE_LEVELS:
                if sum(1 for ln in lines if pat.match(ln)) >= 2:
                    clauses = _group_lines(lines, lambda ln, p=pat: bool(p.match(ln)))
                    break
            pieces = [p for c in clauses for p in recursive(c, 400, 0)]
            if len(pieces) == 1:
                out.append(Chunk("normal", pieces[0], hp, s.page))
                continue
            out.append(Chunk("parent", parent_text, hp, s.page))
            pi = len(out) - 1
            out += [Chunk("child", p, hp, s.page, parent=pi) for p in pieces]
    return out


def _recursive_type(secs: list[Section], size: int, overlap: int) -> list[Chunk]:
    return [
        Chunk("normal", piece, " > ".join(s.path), s.page)
        for s in secs
        for piece in recursive(s.text, size, overlap)
    ]


def _table(secs: list[Section]) -> list[Chunk]:
    out: list[Chunk] = []
    for s in secs:
        hp = " > ".join(s.path)
        lines = s.text.splitlines()
        i = 0
        prose: list[str] = []
        while i < len(lines):
            is_table = lines[i].lstrip().startswith("|")
            has_rule = i + 1 < len(lines) and re.match(r"^\s*\|?\s*:?-+", lines[i + 1])
            if is_table and has_rule:
                if prose:
                    out += [Chunk("normal", p, hp, s.page) for p in recursive("\n".join(prose), 500, 50)]
                    prose = []
                header = lines[i : i + 2]
                j = i + 2
                rows = []
                while j < len(lines) and lines[j].lstrip().startswith("|"):
                    rows.append(lines[j])
                    j += 1
                for k in range(0, len(rows), 20):
                    group = rows[k : k + 20]
                    out.append(
                        Chunk("normal", "\n".join(header + group), hp, s.page, rows=f"第 {k + 1}–{k + len(group)} 行")
                    )
                i = j
            else:
                prose.append(lines[i])
                i += 1
        if "\n".join(prose).strip():
            out += [Chunk("normal", p, hp, s.page) for p in recursive("\n".join(prose), 500, 50)]
    return out


def _qa(secs: list[Section]) -> list[Chunk]:
    out: list[Chunk] = []
    for s in secs:
        hp = " > ".join(s.path)
        items = _group_lines(s.text.splitlines(), lambda ln: bool(_QUESTION.match(ln)))
        if len(items) <= 1 and not _QUESTION.match(s.text):
            items = [s.text]
        out += [Chunk("normal", it, hp, s.page) for it in items]
    return out


def _case(secs: list[Section]) -> list[Chunk]:
    groups: dict[str, list[Section]] = {}
    for s in secs:
        key = " > ".join(s.path[:2])
        groups.setdefault(key, []).append(s)
    out: list[Chunk] = []
    for key, ss in groups.items():
        text = "\n\n".join(("#" * len(s.path) + " " + s.path[-1] + "\n" if len(s.path) > 2 else "") + s.text for s in ss)
        page = ss[0].page
        if ntok(text) <= 1000:
            out.append(Chunk("normal", text, key, page))
            continue
        out.append(Chunk("parent", text, key, page))
        pi = len(out) - 1
        stages = _group_lines(text.splitlines(), lambda ln: bool(_STAGE.match(ln) or ln.startswith("###")))
        if len(stages) <= 1:
            stages = recursive(text, 1000, 0)
        for st in stages:
            for piece in recursive(st, 1000, 0):
                out.append(Chunk("child", piece, key, page, parent=pi))
    return out


def chunk(md: str, knowledge_type: str) -> list[Chunk]:
    if knowledge_type not in STRATEGIES:
        raise ValueError(f"未知知识类型：{knowledge_type}")
    secs = sections(md)
    if knowledge_type == "rule":
        return _rule(secs)
    if knowledge_type == "guide":
        return _recursive_type(secs, 500, 50)
    if knowledge_type == "manual":
        return _recursive_type(secs, 800, 100)
    if knowledge_type == "table":
        return _table(secs)
    if knowledge_type == "qa":
        return _qa(secs)
    if knowledge_type == "data_table":
        return []
    return _case(secs)
