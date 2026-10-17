"""元数据取值、知识空间与检索身份。取值与 PRD 6.2 元数据字典一致；用列表保证前端下拉顺序。"""
from .chunk import STRATEGIES

OPTIONS = {
    "knowledge_space_id": [
        ("kb_platform_rules", "平台规则库"),
        ("kb_help", "帮助中心"),
        ("kb_team_demo", "企业团队库（演示商家）"),
        ("kb_user_demo", "个人知识库（张三）"),
    ],
    "knowledge_type": [(k, v["label"]) for k, v in STRATEGIES.items()],
    "table_kind": [("catalog", "商品目录"), ("price", "价格表"), ("freight", "运价表"), ("cost", "成本表")],
    "source_type": [
        ("official_rule", "平台官方规则"),
        ("help_doc", "官方帮助"),
        ("user_upload", "商家上传"),
        ("qa", "标准问答"),
        ("case", "案例"),
        ("web", "公开网页"),
    ],
    "platform": [
        ("general", "通用"),
        ("1688", "1688"),
        ("alibaba_com", "Alibaba.com"),
        ("amazon", "Amazon"),
        ("shopify", "Shopify"),
        ("tiktok_shop", "TikTok Shop"),
        ("unknown", "未知"),
    ],
    "market": [
        ("unknown", "未知"),
        ("US", "美国"),
        ("CN", "中国"),
        ("CA", "加拿大"),
        ("GB", "英国"),
        ("DE", "德国"),
        ("JP", "日本"),
    ],
    "language": [("zh", "中文"), ("en", "英语"), ("ja", "日语"), ("de", "德语"), ("fr", "法语"), ("es", "西班牙语")],
    "business_domain": [
        ("sourcing", "选品"),
        ("procurement", "采购比价"),
        ("listing", "发品"),
        ("store_analytics", "店铺分析"),
        ("ads", "广告"),
        ("sales", "销售跟进"),
        ("service", "客服售后"),
        ("logistics", "物流关税"),
        ("common", "通用"),
    ],
    "access_level": [
        ("public", "公开"),
        ("internal", "平台内部"),
        ("enterprise", "企业全员"),
        ("department", "指定部门"),
        ("private", "仅本人"),
    ],
    "dept_ids": [("sales", "销售部"), ("finance", "财务部"), ("operations", "运营部")],
    "quality_grade": [("gold", "黄金"), ("reviewed", "已审核"), ("candidate", "候选"), ("to_recheck", "待复核")],
    "risk_level": [("normal", "一般"), ("notice", "提示"), ("high", "高风险"), ("prohibited", "禁止")],
    "review_status": [("unreviewed", "待审核"), ("approved", "已审核"), ("rejected", "已驳回")],
    "pii_level": [("none", "无"), ("high", "高")],
}
OPTION_KEYS = {f: {k for k, _ in v} for f, v in OPTIONS.items()}

# 知识层、默认权限、可选权限（只能比默认更严）、是否需审核后才可检索
SPACES = {
    "kb_platform_rules": {"layer": "平台公共知识层", "access": ["public", "internal"], "review": True},
    "kb_help": {"layer": "平台公共知识层", "access": ["public", "internal"], "review": True},
    "kb_team_demo": {"layer": "企业私域知识层", "access": ["enterprise", "department"], "review": False},
    "kb_user_demo": {"layer": "个人知识层", "access": ["private"], "review": False},
}

ROLES = {
    "zhangsan": {
        "label": "张三：商家销售部成员，个人库所有者",
        "access": {"public", "enterprise", "department", "private"},
        "dept": "sales",
        "exclude_pii": False,
    },
    "lisi": {
        "label": "李四：商家财务部成员",
        "access": {"public", "enterprise", "department"},
        "dept": "finance",
        "exclude_pii": False,
    },
    "reception": {
        "label": "AI 接待助手：面向买家",
        "access": {"public", "enterprise"},
        "dept": None,
        "exclude_pii": True,
    },
    "official": {
        "label": "Accio Work 官方 Agent",
        "access": {"public", "internal"},
        "dept": None,
        "exclude_pii": False,
    },
}


def label(field: str, value: str) -> str:
    return dict(OPTIONS[field]).get(value, value)
