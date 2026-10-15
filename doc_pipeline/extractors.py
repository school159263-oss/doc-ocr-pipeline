"""抽取層:輸入檔案,輸出固定欄位的 dict。
每個抽取器都是 (path) -> dict,可在 EXTRACTORS 裡自由替換,後面的檢查與評估不用改。
全部在本機執行,不呼叫外部服務。
"""
import json
import re
from pathlib import Path

# 想抽的欄位,之後換成實際表單時改這裡
FIELDS = ["doc_no", "date", "vendor", "total"]


# ---------- 1. 取得文字(原生 PDF 優先,否則 OCR) ----------
def get_text(path: str) -> str:
    p = Path(path)
    if p.suffix.lower() == ".txt":  # 測試用:直接讀文字,跳過 OCR
        return p.read_text(encoding="utf-8")
    if p.suffix.lower() == ".pdf":
        text = _pdf_native_text(p)
        if len(text.strip()) > 20:  # 有文字層,不必 OCR
            return text
        return _ocr_image_pages(_pdf_to_images(p))
    return _ocr_image_pages([str(p)])


def _pdf_native_text(p: Path) -> str:
    try:
        import pdfplumber
        with pdfplumber.open(p) as pdf:
            return "\n".join((pg.extract_text() or "") for pg in pdf.pages)
    except Exception:
        return ""


def _pdf_to_images(p: Path):
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(str(p))
    return [pg.render(scale=2).to_pil() for pg in pdf]


_paddle = None


def _ocr_image_pages(images) -> str:
    """優先 PaddleOCR(繁中表現較好),沒裝就退回 Tesseract。"""
    global _paddle
    lines = []
    try:
        from paddleocr import PaddleOCR
        import numpy as np
        from PIL import Image
        if _paddle is None:
            _paddle = PaddleOCR(use_angle_cls=True, lang="chinese_cht")
        for im in images:
            img = Image.open(im) if isinstance(im, str) else im
            res = _paddle.ocr(np.array(img.convert("RGB")))
            for page in res or []:
                for item in page or []:
                    lines.append(item[1][0])
    except ImportError:
        import pytesseract
        from PIL import Image
        for im in images:
            img = Image.open(im) if isinstance(im, str) else im
            lines.append(pytesseract.image_to_string(img, lang="chi_tra+eng"))
    return "\n".join(lines)


# ---------- 2. 規則抽取(固定格式用) ----------
def normalize_date(s: str):
    """支援 2026/10/02、2026-10-02、2026年10月2日、民國 115/10/02。回傳 YYYY-MM-DD 或 None。"""
    m = re.search(r"(\d{2,4})\s*[/\-.年]\s*(\d{1,2})\s*[/\-.月]\s*(\d{1,2})", s)
    if not m:
        return None
    y, mo, d = (int(x) for x in m.groups())
    if y < 1911:  # 視為民國年
        y += 1911
    if not (1 <= mo <= 12 and 1 <= d <= 31):
        return None
    return f"{y:04d}-{mo:02d}-{d:02d}"


_NUM = r"(?:NT\$?|\$)?\s*([\d,]+(?:\.\d+)?)"


def _to_num(x: str):
    return float(x.replace(",", ""))


def _find_amounts(text: str, labels: str):
    """找出「標籤 + 金額」。標籤前不可緊接英文字母(避免 Subtotal 被當成 Total),也不可緊接「小」(小計/小合計)。"""
    pat = rf"(?<![A-Za-z小])(?:{labels})\s*[:：]?\s*{_NUM}"
    return [_to_num(m) for m in re.findall(pat, text, re.I)]


def extract_by_rules(path: str, text: str = None) -> dict:
    text = text if text is not None else get_text(path)
    out = {k: None for k in FIELDS}
    out["subtotal"] = None  # 供查檢層做「總額 = 小計 + 稅額」交叉檢查;文件上沒有就維持 None
    out["tax"] = None
    out["_text"] = text

    # 單號:標籤容許 OCR 把「發票號碼」的「票」讀錯一個字
    m = re.search(r"(?:單號|編號|發.號碼|Invoice\s*(?:No\.?|#)|No\.?)\s*[:：]?\s*([A-Z0-9][A-Z0-9\-]{5,})", text, re.I)
    if m:
        out["doc_no"] = m.group(1).strip()

    m = re.search(r"(?:日期|Date)\s*[:：]?\s*([^\n]+)", text, re.I)
    if m:
        out["date"] = normalize_date(m.group(1))

    # 廠商:遇到兩個以上空白(版面分欄),或後面接「日期/Date」就停,避免把同一行的日期一起吃進來
    m = re.search(
        r"(?:廠商|供應商|公司名稱|Vendor)\s*[:：]?\s*(.+?)(?=\s{2,}|\s+(?:日期|Date)\s*[:：]|\n|$)",
        text, re.I)
    if m:
        out["vendor"] = m.group(1).strip()

    # 總額:優先用「總計/總金額/Total」(取最後一個);都沒有才退而用「合計」
    grand = _find_amounts(text, "總計|總金額|Total")
    fallback = _find_amounts(text, "合計")
    if grand:
        out["total"] = grand[-1]
        # 同時有「總計」和「合計」時,「合計」是稅前小計(發票常見寫法)
        subs = _find_amounts(text, "小計|Subtotal") or fallback
        out["subtotal"] = subs[-1] if subs else None
    elif fallback:
        out["total"] = fallback[-1]
    else:
        subs = _find_amounts(text, "小計|Subtotal")
        out["subtotal"] = subs[-1] if subs else None

    taxes = re.findall(
        rf"(?:營業稅|稅額|Tax|VAT)\s*(?:\(\s*\d+(?:\.\d+)?\s*%\s*\))?\s*[:：]?\s*{_NUM}", text, re.I)
    if taxes:
        out["tax"] = _to_num(taxes[-1])
    return out


# ---------- 3. 本機大模型抽取(不固定格式用,預設走 Ollama) ----------
OLLAMA_URL = "http://localhost:11434/api/chat"
OLLAMA_MODEL = "qwen2.5:7b"  # 依你機器能跑的模型調整

PROMPT = """以下是文件經 OCR 後的文字。請只輸出 JSON,欄位為:
doc_no(單號,字串)、date(日期,格式 YYYY-MM-DD,民國年請轉西元)、vendor(廠商名稱)、total(總金額,數字)。
找不到的欄位填 null,不要猜測、不要補值。

文件文字:
{text}
"""


def extract_by_local_llm(path: str, text: str = None) -> dict:
    import requests
    text = text if text is not None else get_text(path)
    r = requests.post(OLLAMA_URL, json={
        "model": OLLAMA_MODEL,
        "messages": [{"role": "user", "content": PROMPT.format(text=text)}],
        "format": "json",
        "stream": False,
    }, timeout=120)
    r.raise_for_status()
    data = json.loads(r.json()["message"]["content"])
    out = {k: data.get(k) for k in FIELDS}
    if isinstance(out["total"], str):
        try:
            out["total"] = float(out["total"].replace(",", ""))
        except ValueError:
            out["total"] = None
    out["_text"] = text
    return out


# ---------- 4. 分流:認得的格式走規則,否則走大模型 ----------
def looks_like_known_form(text: str) -> bool:
    """先用簡單判斷:四個關鍵欄位規則都抓得到,就視為固定格式。之後可換成標題或版面特徵。"""
    probe = extract_by_rules("", text)
    return all(probe[k] is not None for k in FIELDS)


def extract_routed(path: str) -> dict:
    text = get_text(path)
    if looks_like_known_form(text):
        res = extract_by_rules(path, text)
        res["_route"] = "rules"
    else:
        res = extract_by_local_llm(path, text)
        res["_route"] = "llm"
    return res


# 評估時可以指定用哪一種,方便比較
EXTRACTORS = {
    "rules": extract_by_rules,
    "llm": extract_by_local_llm,
    "routed": extract_routed,
}
