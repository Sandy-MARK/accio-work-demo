"""数据表格结构化抽取：表头按同义词映射为标准字段，逐行写入业务表。

商品目录为每个 SKU 生成一条描述块参与语义检索；价格、运价、成本只走结构化查询，不向量化。
"""
import re
from datetime import date

# 标准字段：(key, 中文名, 表头同义词)
FIELDS = {
    "catalog": [
        ("sku_id", "SKU", ["sku", "sku_id", "货号", "商品编码", "款号", "型号"]),
        ("name", "品名", ["品名", "商品名称", "产品名称", "名称", "product", "name"]),
        ("category_id", "类目 ID", ["类目id", "类目", "category"]),
        ("material", "材质", ["材质", "材料", "material"]),
        ("size", "尺寸", ["尺寸", "规格", "size"]),
        ("weight", "重量", ["重量", "净重", "毛重", "weight"]),
        ("color", "颜色", ["颜色", "color"]),
        ("certification", "认证", ["认证", "证书", "certification"]),
        ("moq", "MOQ", ["moq", "起订量", "最小起订量"]),
        ("lead_time", "交期", ["交期", "生产周期", "lead time", "lead_time"]),
        ("image_url", "主图地址", ["主图", "主图地址", "图片", "image"]),
    ],
    "price": [
        ("sku_id", "SKU", ["sku", "sku_id", "货号", "商品编码", "款号", "型号"]),
        ("qty_range", "起订数量段", ["起订数量段", "数量段", "数量", "阶梯", "quantity"]),
        ("unit_price", "单价", ["单价", "价格", "unit price", "price"]),
        ("currency", "币种", ["币种", "货币", "currency"]),
        ("incoterm", "贸易术语", ["贸易术语", "incoterm", "价格条款"]),
        ("customer_tier", "客户等级", ["客户等级", "客户类型", "等级"]),
        ("effective_from", "生效日期", ["生效日期", "开始日期", "effective"]),
        ("expires_at", "失效日期", ["失效日期", "截止日期", "有效期至", "expires"]),
    ],
    "freight": [
        ("carrier", "承运商", ["承运商", "物流商", "货代", "渠道", "carrier"]),
        ("destination", "目的国", ["目的国", "国家", "目的地", "destination"]),
        ("weight_range", "重量段", ["重量段", "重量", "weight"]),
        ("unit_price", "单价", ["单价", "运费", "价格", "price"]),
        ("currency", "币种", ["币种", "货币", "currency"]),
        ("effective_from", "生效日期", ["生效日期", "开始日期", "effective"]),
    ],
    "cost": [
        ("sku_id", "SKU", ["sku", "sku_id", "货号", "商品编码", "款号", "型号"]),
        ("cost_item", "成本项", ["成本项", "项目", "费用项"]),
        ("amount", "金额", ["金额", "成本", "amount"]),
        ("currency", "币种", ["币种", "货币", "currency"]),
        ("month", "统计月份", ["统计月份", "月份", "month"]),
    ],
}
REQUIRED = {"catalog": ["sku_id", "name"], "price": ["sku_id", "unit_price", "currency"], "freight": ["carrier", "destination", "unit_price"], "cost": ["sku_id", "amount"]}

_NORM = re.compile(r"[\s_（）()]+")


def _norm(s: str) -> str:
    return _NORM.sub("", s).lower()


def map_header(kind: str, header: list[str]) -> tuple[dict[int, str], list[str]]:
    """返回 {列下标: 标准字段} 与未映射的表头。"""
    mapping: dict[int, str] = {}
    unmapped = []
    used = set()
    for i, h in enumerate(header):
        n = _norm(h)
        hit = None
        for key, _, syns in FIELDS[kind]:
            if key in used:
                continue
            if any(n == _norm(s) for s in syns):
                hit = key
                break
        if hit is None:
            for key, _, syns in FIELDS[kind]:
                if key not in used and any(_norm(s) in n for s in syns if len(_norm(s)) >= 2):
                    hit = key
                    break
        if hit:
            mapping[i] = hit
            used.add(hit)
        elif h:
            unmapped.append(h)
    return mapping, unmapped


def extract(kind: str, sheets: list[tuple[str, list[list[str]]]]) -> tuple[list[dict], str]:
    """抽取全部 sheet，返回 (行记录, 处理说明)。每条记录 {sheet, row_no, fields, extra}。"""
    records = []
    notes = []
    for sheet, rows in sheets:
        mapping, unmapped = map_header(kind, rows[0])
        missing = [k for k in REQUIRED[kind] if k not in mapping.values()]
        if missing:
            names = "、".join(field_label(kind, k) for k in missing)
            notes.append(f"「{sheet}」缺少必需列：{names}，已跳过")
            continue
        header = rows[0]
        for n, r in enumerate(rows[1:], 2):
            r = r + [""] * (len(header) - len(r))
            fields = {mapping[i]: r[i] for i in mapping if r[i]}
            if not all(fields.get(k) for k in REQUIRED[kind]):
                continue
            extra = {header[i]: r[i] for i in range(len(header)) if i not in mapping and header[i] and r[i]}
            records.append({"sheet": sheet, "row_no": n, "fields": fields, "extra": extra})
        mapped = "、".join(f"{rows[0][i]}→{field_label(kind, k)}" for i, k in mapping.items())
        note = f"「{sheet}」映射 {mapped}"
        if unmapped:
            note += f"；未映射列保留为附加字段：{'、'.join(unmapped)}"
        notes.append(note)
    if not records:
        raise ValueError("没有抽取到有效行。" + "；".join(notes))
    return records, f"{len(records)} 行。" + "；".join(notes)


def field_label(kind: str, key: str) -> str:
    return next((label for k, label, _ in FIELDS[kind] if k == key), key)


def sku_text(rec: dict) -> str:
    """商品目录每个 SKU 的描述块正文。"""
    f = rec["fields"]
    parts = [f"{field_label('catalog', k)}：{v}" for k, v in f.items() if k not in ("sku_id", "name", "image_url")]
    parts += [f"{k}：{v}" for k, v in rec["extra"].items()]
    return f"SKU {f['sku_id']} {f['name']}。" + "；".join(parts)


def row_status(kind: str, fields: dict, today: str | None = None) -> str:
    """价格类行的效力：active / expired / pending。"""
    today = today or date.today().isoformat()
    exp = _date(fields.get("expires_at"))
    eff = _date(fields.get("effective_from"))
    if exp and exp < today:
        return "expired"
    if eff and eff > today:
        return "pending"
    return "active"


def _date(v: str | None) -> str | None:
    if not v:
        return None
    m = re.match(r"(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})", v)
    return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else None


SKU_TOKEN = re.compile(r"[A-Za-z]{1,6}-?\d{2,}[A-Za-z0-9-]*")
