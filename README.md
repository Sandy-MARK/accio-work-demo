# Accio Work 知识库后台演示

Accio Work PRD「知识库构建与管理」与「检索链路」的可运行原型：上传文档 → 解析 → 按知识类型切块 → 向量化 → 建索引，再用检索测试页逐阶段查看召回、融合、重排和最终结果。向量化与重排调用阿里云百炼的真实模型。

## 和 PRD 的对应关系

| 功能 | 演示实现 | PRD 章节 |
|-|-|-|
| 文档解析 | PDF（带页码）、Word（标题与表格）、Excel / CSV（转 Markdown 表格）、Markdown、TXT、网页统一转为 Markdown | 文件解析 |
| 分块 | 6 种知识类型各用一种规则：规则类按条款切子块并保留父块，帮助文档 500 / 重叠 50，商品手册 800 / 重叠 100，说明表格每 20 行带表头，问答整条，案例按阶段 | 3.3 分块规则、3.4 父子块 |
| 向量化 | `text-embedding-v4`，1024 维，每批 10 条 | Embedding 选型 |
| 元数据 | 知识空间、知识类型、来源类型、权限级别、处理位置策略、业务域、平台、目标市场、语言、质量等级、风险等级、生效 / 失效时间、效力状态、原文定位、父块 ID | 6.2 元数据构建 |
| 权限 | 权限级别继承知识空间默认值，只能调严；检索前按身份过滤 | 10.1 权限分级 |
| 敏感信息 | 含身份证号、银行卡号的文档标记为 `local_only`，不发往云端向量化 | 6.2.3 处理位置策略 |
| 版本 | 同一知识空间内同名文件再次上传生成新版本，旧版本标记为「已被替代」，不参与检索 | 6.2.2 效力状态 |
| 检索 | 关键词（BM25）与向量各召回 30 条 → RRF 融合 30 条 → `qwen3-rerank` 重排 → 相关分 ≥ 0.4 → 最多 5 条 → 子块命中回填父块 | 8.2 Rerank、检索链路 |
| 兜底 | 重排报错或超过 2 秒未返回时，返回融合排序前 5 条并标记「未经重排」；全部低于阈值时返回「知识库无依据」 | 8.2 Rerank |

演示版未包含：音视频转写（fun-asr）与独立图片描述（qwen3-vl-plus）、扫描件 OCR、备用自部署重排模型、增量更新任务队列。

## 运行

需要 Python 3.10+、Node 18+ 和一个[阿里云百炼](https://bailian.console.aliyun.com) API Key。

```bash
# 后端
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # 填入 DASHSCOPE_API_KEY
uvicorn app.main:app --port 8000 --reload

# 前端（另开终端）
cd frontend
npm install
npm run dev                 # http://localhost:5173
```

`samples/` 里有两份虚构的示例文档：平台商品发布规则（选「平台规则库 / 平台规则」上传）和产品帮助 FAQ（选「帮助中心 / 标准问答」上传）。

## 目录

```
backend/app/
  parse.py     文件 → Markdown
  chunk.py     按知识类型切块
  bailian.py   百炼向量化与重排接口
  store.py     SQLite 存储
  search.py    过滤、混合召回、RRF、重排、阈值、父块回填
  main.py      HTTP 接口
frontend/src/pages/
  DocList.jsx    文档管理与上传
  DocDetail.jsx  元数据、处理记录、切块结果
  SearchTest.jsx 检索测试
```
