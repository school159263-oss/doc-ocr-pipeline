"""零成本版：用 Windows 內建 OCR（離線、免費）辨識採購單，再以版面位置解析欄位。

每個步驟都可以單獨開關，方便評估「哪一步讓準確率提升多少」：
  preprocess   影像前處理（去除紅色印章）
  deskew       以文字座標估算傾斜角度並校正
"""
import asyncio
import re
import statistics
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from PIL import Image

# 欄位錨點：以 150dpi A4 版面為準（x 座標起點）。實務上每種客戶表單各設一組範本。
COLUMNS = {"no": 70, "item_code": 135, "description": 410, "quantity": 750, "unit_price": 890, "amount": 1030}
SPLIT_X = 760  # 抬頭區：左半是買方，右半是單號／日期


@dataclass
class Word:
    text: str
    x: float
    y: float
    w: float
    h: float

    @property
    def cy(self):
        return self.y + self.h / 2


# ---------------------------------------------------------------- 影像前處理
def remove_red_stamp(img: Image.Image) -> Image.Image:
    """取紅色通道：紅色印章在紅色通道中接近白色，黑色文字仍是黑色。"""
    r = img.convert("RGB").split()[0]
    return Image.merge("RGB", (r, r, r))


# ---------------------------------------------------------------- OCR
def ocr_words(img: Image.Image) -> list[Word]:
    import winocr
    result = asyncio.run(winocr.recognize_pil(img.convert("RGB"), "zh-Hant-TW"))
    words = []
    for line in result.lines:
        for w in line.words:
            b = w.bounding_rect
            words.append(Word(w.text, b.x, b.y, b.width, b.height))
    return words


def estimate_skew(words: list[Word]) -> float:
    """用同一列文字的 y 座標隨 x 變化的斜率估算傾斜（弧度近似）。"""
    rows = group_rows(words, tol=10)
    slopes = []
    for row in rows:
        if len(row) < 4 or row[-1].x - row[0].x < 150:
            continue
        xs, ys = [w.x for w in row], [w.cy for w in row]
        mx, my = statistics.mean(xs), statistics.mean(ys)
        den = sum((x - mx) ** 2 for x in xs)
        if den:
            slopes.append(sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den)
    return statistics.median(slopes) if slopes else 0.0


def deskew_words(words: list[Word], slope: float) -> list[Word]:
    return [Word(w.text, w.x, w.y - slope * w.x, w.w, w.h) for w in words]


def group_rows(words: list[Word], tol: float = 18) -> list[list[Word]]:
    rows = []
    for w in sorted(words, key=lambda w: w.cy):
        if rows and abs(rows[-1][-1].cy - w.cy) <= tol:
            rows[-1].append(w)
        else:
            rows.append([w])
    return [sorted(r, key=lambda w: w.x) for r in rows]


def join(words) -> str:
    return "".join(w.text for w in words)


# ---------------------------------------------------------------- 欄位轉換
NUM_FIX = str.maketrans({"O": "0", "o": "0", "D": "0", "I": "1", "l": "1", "|": "1", "i": "1", "S": "5", "s": "5", "B": "8", "Z": "2"})


def parse_num(s: str) -> float:
    s = s.translate(NUM_FIX)
    s = re.sub(r"[^\d.,]", "", s)
    if not re.search(r"\d", s):
        return 0.0
    m = re.search(r"[.,](\d{1,2})$", s)  # 最後一個分隔符號後只有 1～2 碼 → 視為小數點
    if m:
        whole = re.sub(r"[.,]", "", s[: m.start()])
        return float(f"{whole or 0}.{m.group(1)}")
    return float(re.sub(r"[.,]", "", s))


def parse_date(s: str) -> str:
    nums = re.findall(r"\d+", s.translate(NUM_FIX))
    if len(nums) < 3:
        return s
    y, m, d = (int(n) for n in nums[:3])
    if y < 1000:
        y += 1911  # 民國年
    try:
        return date(y, m, d).isoformat()
    except ValueError:
        return s


def after_label(text: str, *labels) -> str | None:
    for lb in labels:
        i = text.find(lb)
        if i >= 0:
            return re.sub(r"^[:：.·、,\s]+", "", text[i + len(lb):])
    return None


# ---------------------------------------------------------------- 版面解析
def parse_layout(words: list[Word]) -> dict:
    rows = group_rows(words)
    order = {"customer_name": "", "po_number": "", "order_date": "", "delivery_date": "",
             "lines": [], "total_amount": 0.0, "uncertain_fields": []}

    header_y = next((r[0].cy for r in rows if "料號" in join(r) or "品名" in join(r)), None)
    total_row = next((r for r in rows if "合計" in join(r) or "NT" in join(r)), None)
    total_y = total_row[0].cy if total_row else 1e9

    for r in rows:
        if header_y is not None and r[0].cy >= header_y - 10:
            break
        left = join([w for w in r if w.x < SPLIT_X])
        right = join([w for w in r if w.x >= SPLIT_X])
        if "公司" in left and not any(k in left for k in ("供應", "精密", "工業")):
            name = re.sub(r"^.*?[方:：]", "", left) if re.search(r"[方:：]", left[:4]) else left
            order["customer_name"] = re.sub(r"[^一-鿿]", "", name)
        if (v := after_label(right, "單號", "號")) is not None and not order["po_number"]:
            order["po_number"] = re.sub(r"[^A-Za-z0-9]", "", v)
        if (v := after_label(right, "購日期", "日期", "購日")) is not None and "交" not in right:
            order["order_date"] = parse_date(v)
        if (v := after_label(right, "交期", "求交")) is not None:
            order["delivery_date"] = parse_date(v)

    if header_y is not None:
        names = list(COLUMNS)
        starts = [COLUMNS[n] for n in names]
        for r in rows:
            if not (header_y + 15 < r[0].cy < total_y - 10):
                continue
            cells = {n: [] for n in names}
            for w in r:
                idx = max([i for i, s in enumerate(starts) if w.x >= s - 25] or [0])
                cells[names[idx]].append(w)
            line = {
                "item_code": re.sub(r"[^A-Za-z0-9\-]", "-", join(cells["item_code"])).strip("-"),
                "description": join(cells["description"]),
                "quantity": parse_num(join(cells["quantity"])),
                "unit_price": parse_num(join(cells["unit_price"])),
                "amount": parse_num(join(cells["amount"])),
            }
            filled = sum(line[k] > 0 for k in ("quantity", "unit_price", "amount"))
            if len(line["item_code"]) >= 4 or filled >= 2:  # 過濾雜訊造成的空白列
                order["lines"].append(line)

    if total_row:
        txt = join(total_row)
        m = re.search(r"(?:NT|N7|AT|\$)\$?(.+)$", txt)
        order["total_amount"] = parse_num(m.group(1) if m else txt)
    return order


class LocalExtractor:
    """與 ClaudeExtractor 相同介面，可直接放進 ocr_pipeline.process()。"""

    def __init__(self, preprocess: bool = True, deskew: bool = True):
        self.preprocess, self.deskew = preprocess, deskew
        self.calls = 0  # 本機 OCR，不產生 API 費用
        self.supports_recheck = False  # 同一張圖重跑結果相同，不需重新判讀
        self.last_words: list[Word] = []

    def words(self, image_path: Path) -> list[Word]:
        img = Image.open(image_path)
        if self.preprocess:
            img = remove_red_stamp(img)
        words = ocr_words(img)
        if self.deskew:
            words = deskew_words(words, estimate_skew(words))
        return words

    def extract(self, image_path: Path, extra_context: str = "", previous=None, issues=None) -> dict:
        self.last_words = self.words(image_path)
        return parse_layout(self.last_words)
