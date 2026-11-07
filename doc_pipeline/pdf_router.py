"""V2：PDF 分流。

    電子 PDF（文字層字數夠多）→ PyMuPDF 直接讀文字，不經 OCR
    掃描檔                   → 轉圖片 → OpenCV 去雜訊、二值化、量測傾斜角並校正 → Tesseract（chi_tra+eng）→ 文字正規化

只使用 Tesseract，不依賴 PaddleOCR：Tesseract 是單一可離線安裝的執行檔加語言模型檔，
不需下載深度學習框架或在執行時連網抓模型，較容易通過企業資安審查（詳見 README）。
語言模型目錄由環境變數 TESSDATA_PREFIX 決定，日誌會印出實際使用的目錄。
"""
import logging
import os
import re
import unicodedata
from pathlib import Path

import cv2
import numpy as np
import pymupdf
import pytesseract

log = logging.getLogger("pdf_router")

MIN_CHARS_PER_PAGE = 50   # 每頁非空白字元數達此門檻才視為電子 PDF；純影像 PDF 為 0，少量浮水印或頁碼不會超過
RENDER_DPI = 300
TESS_LANG = "chi_tra+eng"
MAX_SKEW = 15.0           # 傾斜角搜尋範圍 ±15°，超出範圍的掃描檔無法正確校正


# ---------- 文字正規化（只用在 OCR 輸出） ----------
_CJK = r"㐀-䶿一-鿿豈-﫿"
_CJK_PUNCT = r"　-〿！-／：-＠"


def normalize_ocr_text(s: str) -> str:
    """消除不同 tessdata 版本之間的輸出差異，不改動字本身：
    1. NFKC：小型全形標點（﹕﹣﹒﹩…）與全形英數轉為一般字元
    2. 移除中文字之間、中文字與中文標點之間的空白（「發 票 號 碼」→「發票號碼」）
    英文、數字之間的空白保留（例如 ACME Semi、per wafer）。"""
    s = unicodedata.normalize("NFKC", s)
    s = re.sub(rf"(?<=[{_CJK}{_CJK_PUNCT}])[ \t]+(?=[{_CJK}{_CJK_PUNCT}])", "", s)
    s = re.sub(rf"(?<=[{_CJK}])[ \t]+(?=[:;,.])", "", s)  # 「號碼 :」→「號碼:」
    return s


# ---------- 影像前處理 ----------
def _binarize(gray: np.ndarray) -> np.ndarray:
    """中值濾波去椒鹽雜訊後用 Otsu 二值化。回傳白底黑字。"""
    den = cv2.medianBlur(gray, 3)
    _, bw = cv2.threshold(den, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return bw


def measure_skew(bw: np.ndarray) -> float:
    """以水平投影輪廓量測傾斜角：把影像轉不同角度，文字行最水平時，逐列像素和的起伏最大。
    回傳文件相對水平的傾斜角（度，逆時針為正，與 cv2.getRotationMatrix2D 同方向）。"""
    ink = (bw < 128).astype(np.uint8) * 255
    scale = 1000 / ink.shape[1]
    small = cv2.resize(ink, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    h, w = small.shape
    center = (w / 2, h / 2)

    def sharpness(a):
        M = cv2.getRotationMatrix2D(center, a, 1.0)
        rot = cv2.warpAffine(small, M, (w, h), flags=cv2.INTER_NEAREST, borderValue=0)
        rows = rot.sum(axis=1, dtype=np.float64)
        return float(np.sum(np.diff(rows) ** 2))

    best = max(np.arange(-MAX_SKEW, MAX_SKEW + 1e-9, 0.5), key=sharpness)
    best = max(np.arange(best - 0.5, best + 0.5 + 1e-9, 0.05), key=sharpness)
    return round(-float(best), 2)  # 轉正需要旋轉 best 度，文件本身的傾斜就是 -best


def deskew(gray: np.ndarray, skew: float) -> np.ndarray:
    h, w = gray.shape
    M = cv2.getRotationMatrix2D((w / 2, h / 2), -skew, 1.0)
    return cv2.warpAffine(gray, M, (w, h), flags=cv2.INTER_CUBIC, borderValue=255)


# ---------- 主流程 ----------
def _tessdata_dir() -> str:
    return os.environ.get("TESSDATA_PREFIX", "(Tesseract 預設目錄)")


def read_pdf(path: str) -> dict:
    """回傳 {route, text, raw_text, chars_per_page, skew_angles}。
    route: "electronic" 或 "scan"；text 是給抽取層用的文字（掃描檔為正規化後），raw_text 是 OCR 原始輸出。"""
    name = Path(path).name
    doc = pymupdf.open(path)
    page_texts = [pg.get_text("text", sort=True) for pg in doc]
    chars = [len(re.sub(r"\s", "", t)) for t in page_texts]
    avg = sum(chars) / max(len(chars), 1)

    if avg >= MIN_CHARS_PER_PAGE:
        log.info("%s：文字層平均每頁 %.0f 字 ≥ 門檻 %d → 電子 PDF，直接讀取文字（不經 OCR）",
                 name, avg, MIN_CHARS_PER_PAGE)
        text = "\n".join(page_texts)
        return {"route": "electronic", "text": text, "raw_text": text, "chars_per_page": avg, "skew_angles": []}

    log.info("%s：文字層平均每頁 %.0f 字 < 門檻 %d → 掃描檔，走 OCR", name, avg, MIN_CHARS_PER_PAGE)
    raw_pages, angles = [], []
    for i, pg in enumerate(doc, 1):
        pix = pg.get_pixmap(dpi=RENDER_DPI, colorspace=pymupdf.csGRAY)
        gray = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width).copy()
        skew = measure_skew(_binarize(gray))
        bw = _binarize(deskew(gray, skew))
        angles.append(skew)
        log.info("%s 第 %d 頁：轉圖 %d dpi → 二值化 → 量測傾斜角 %+.2f° → 校正 → Tesseract（%s，tessdata=%s）",
                 name, i, RENDER_DPI, skew, TESS_LANG, _tessdata_dir())
        raw_pages.append(pytesseract.image_to_string(bw, lang=TESS_LANG))
    raw = "\n".join(raw_pages)
    return {"route": "scan", "text": normalize_ocr_text(raw), "raw_text": raw,
            "chars_per_page": avg, "skew_angles": angles}
