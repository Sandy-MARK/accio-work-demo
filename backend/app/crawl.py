"""网页抓取入库：单页 / 站点地图 / 目录页链接。按正文内容哈希判断是否变化，只为变化的页面生成新版本。"""
import json
import re
import uuid
from datetime import datetime
from html.parser import HTMLParser
from urllib.parse import urldefrag, urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx

from . import bailian, config, ingest, store
from .parse import ParseError, parse

MODES = {"page": "单个页面", "sitemap": "站点地图（sitemap.xml）", "index": "目录页（抓取页内同站链接）"}
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
MIN_TEXT = 80


class _Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: list[str] = []
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag == "a" and (href := dict(attrs).get("href")):
            self.links.append(href)
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data


def _html_info(html: str) -> _Links:
    p = _Links()
    p.feed(html)
    p.title = re.sub(r"\s+", " ", p.title).strip()
    return p


def _locs(xml: str) -> list[str]:
    return [u.strip() for u in re.findall(r"<loc>\s*(?:<!\[CDATA\[)?([^<\]]+?)(?:\]\]>)?\s*</loc>", xml)]


def discover(client: httpx.Client, url: str, mode: str) -> list[str]:
    if mode == "page":
        return [url]
    r = client.get(url)
    r.raise_for_status()
    if mode == "sitemap":
        urls = _locs(r.text)
        if not urls:
            raise ValueError("没有在站点地图中找到 <loc> 地址；该页面可能不是 XML 站点地图")
        nested = [u for u in urls if u.lower().endswith(".xml")]
        if nested and len(nested) == len(urls):
            urls = []
            for sub in nested[:5]:
                try:
                    urls += _locs(client.get(sub).text)
                except httpx.HTTPError:
                    continue
    else:
        host = urlparse(str(r.url)).netloc
        urls = [url]
        for href in _html_info(r.text).links:
            u = urldefrag(urljoin(str(r.url), href))[0]
            if urlparse(u).scheme in ("http", "https") and urlparse(u).netloc == host:
                urls.append(u)
    seen, out = set(), []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out[: config.CRAWL_MAX_PAGES]


class _Robots:
    """按站点缓存 robots.txt；读取失败时视为允许。"""

    def __init__(self, client: httpx.Client):
        self.client = client
        self.cache: dict[str, RobotFileParser | None] = {}

    def allowed(self, url: str) -> bool:
        p = urlparse(url)
        base = f"{p.scheme}://{p.netloc}"
        if base not in self.cache:
            try:
                r = self.client.get(base + "/robots.txt")
                rp = RobotFileParser()
                rp.parse(r.text.splitlines() if r.status_code == 200 else [])
                self.cache[base] = rp
            except httpx.HTTPError:
                self.cache[base] = None
        rp = self.cache[base]
        return rp is None or rp.can_fetch("*", url)


def create(url: str, mode: str, m: dict) -> dict:
    if mode not in MODES:
        raise ingest.IngestError("抓取方式无效")
    if urlparse(url).scheme not in ("http", "https"):
        raise ingest.IngestError("请输入 http 或 https 开头的网址")
    m = ingest.validate(m)
    if m["knowledge_type"] == "data_table":
        raise ingest.IngestError("网页抓取不支持数据表格类型")
    src = {
        "source_id": f"src_{uuid.uuid4().hex[:10]}",
        "url": url,
        "mode": mode,
        "meta": json.dumps(m, ensure_ascii=False),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    with store.conn() as c:
        c.execute(f"INSERT INTO crawl_sources ({','.join(src)}) VALUES ({','.join('?' * len(src))})", list(src.values()))
    return run(src["source_id"])


def run(source_id: str) -> dict:
    with store.conn() as c:
        src = store.row(c.execute("SELECT * FROM crawl_sources WHERE source_id = ?", (source_id,)).fetchone())
    if not src:
        raise ingest.IngestError("抓取来源不存在")
    res = {"pages": 0, "new": [], "updated": [], "unchanged": [], "gaps": [], "failed": []}
    with httpx.Client(follow_redirects=True, timeout=15, headers={"User-Agent": UA}) as client:
        try:
            urls = discover(client, src["url"], src["mode"])
        except (httpx.HTTPError, ValueError) as e:
            res["error"] = f"读取入口地址失败：{e}"
            urls = []
        res["pages"] = len(urls)
        robots = _Robots(client)
        for u in urls:
            item = {"url": u}
            if not robots.allowed(u):
                res["gaps"].append(item | {"reason": "站点 robots.txt 不允许抓取该页面"})
                continue
            try:
                r = client.get(u)
                r.raise_for_status()
            except httpx.HTTPError as e:
                res["gaps"].append(item | {"reason": f"抓取失败：{e}"})
                continue
            if "html" not in r.headers.get("content-type", "html"):
                res["gaps"].append(item | {"reason": f"不是网页（{r.headers.get('content-type')}）"})
                continue
            info = _html_info(r.text)
            try:
                text = parse("page.html", r.content)
            except ParseError:
                text = ""
            if len(text) < MIN_TEXT:
                res["gaps"].append(item | {"reason": "页面没有可提取的正文，可能需要浏览器渲染后才显示内容"})
                continue
            name = info.title or urlparse(u).path.strip("/") or u
            item["name"] = name
            try:
                doc = ingest.ingest(name, r.content, src["meta"], source_url=u, parse_name="page.html")
            except ingest.Duplicate:
                res["unchanged"].append(item)
                continue
            except (ingest.IngestError, ParseError, bailian.BailianError) as e:
                res["failed"].append(item | {"reason": str(e)})
                continue
            item |= {"doc_version_id": doc["doc_version_id"], "version": doc["version"]}
            if doc["status"] != "indexed":
                res["failed"].append(item | {"reason": doc.get("error") or "入库失败"})
            elif doc["version"] > 1:
                res["updated"].append(item)
            else:
                res["new"].append(item)
    now = datetime.now().isoformat(timespec="seconds")
    with store.conn() as c:
        c.execute(
            "UPDATE crawl_sources SET last_run_at = ?, last_result = ? WHERE source_id = ?",
            (now, json.dumps(res, ensure_ascii=False), source_id),
        )
    return {**src, "last_run_at": now, "last_result": res}


def list_sources() -> list[dict]:
    with store.conn() as c:
        return [store.row(r) for r in c.execute("SELECT * FROM crawl_sources ORDER BY created_at DESC")]
