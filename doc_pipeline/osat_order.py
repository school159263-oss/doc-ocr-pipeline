"""V2：封測客戶訂單（OSAT customer order）的 schema 與規則抽取。

獨立於 V1 的單據 schema（extractors.FIELDS），不共用欄位。
輸入是文字（電子 PDF 文字層，或掃描檔經 pdf_router 的 OCR + 正規化），輸出固定欄位的 dict。
"""
import re

from extractors import normalize_date  # 沿用 V1 的日期正規化（唯讀引用，不修改 V1）

# 欄位順序即 schema；中文名稱供報表與 README 使用
ORDER_FIELDS = {
    "po_no": "客戶 PO 號",
    "customer": "客戶名稱",
    "customer_part_no": "客戶料號",
    "wafer_lot_id": "晶圓批號",
    "wafer_size": "晶圓尺寸",
    "package_type": "封裝型式",
    "die_count": "晶粒數量",
    "unit_price": "單價",
    "price_unit": "計價單位",
    "delivery_date": "交期",
}
WAFER_SIZES = ("8-inch", "12-inch")
PACKAGE_TYPES = ("BGA", "QFN", "CSP")
PRICE_UNITS = ("per wafer", "per 1k units")

# 文件上的標籤：中文 + 英文，任一被正確辨識就能定位。英文標籤對 OCR 錯字較不敏感。
# 中文標籤容許 OCR 讀錯一個字（與 V1「發.號碼」同樣做法）
LABELS = {
    "po_no": r"客戶\s*PO\s*.|PO\s*No",
    "customer": r"客戶名.|Customer(?!\s*P\s*/?\s*N)",
    "customer_part_no": r"客戶料.|Customer\s*P\s*/?\s*N",
    "wafer_lot_id": r"晶圓批.|Wafer\s*Lot",
    "wafer_size": r"晶圓尺.|Wafer\s*Size",
    "package_type": r"封裝型.|Package",
    "die_count": r"晶粒數.|Die\s*Qty",
    "unit_price": r"(?<![計])單價|Unit\s*Price",
    "price_unit": r"計價單.|Price\s*Unit",
    "delivery_date": r"交期|Delivery",
}
_SEP = r"[^:：;\n]*[:：;]\s*"  # 標籤到冒號之間可夾英文標籤或雜訊
_TOKEN = r"([A-Z0-9][A-Z0-9\-]{3,})"


def _after_label(text: str, field: str, value_pat: str = r"(.+)"):
    m = re.search(rf"(?:{LABELS[field]}){_SEP}{value_pat}", text, re.I)
    return m.group(1).strip() if m else None


def extract_order(text: str) -> dict:
    out = {k: None for k in ORDER_FIELDS}

    out["po_no"] = _after_label(text, "po_no", _TOKEN)
    out["customer"] = _after_label(text, "customer")

    # 料號與批號格式明確，標籤沒讀到時退而在全文找符合格式的字串
    out["customer_part_no"] = _after_label(text, "customer_part_no", _TOKEN)
    if not out["customer_part_no"]:
        m = re.search(r"\bOSAT-[A-Z]+-\d{3,}\b", text)
        out["customer_part_no"] = m.group(0) if m else None
    out["wafer_lot_id"] = _after_label(text, "wafer_lot_id", _TOKEN)
    if not out["wafer_lot_id"]:
        m = re.search(r"\bLOT-\d{4}-[A-Z0-9]+\b", text)
        out["wafer_lot_id"] = m.group(0) if m else None

    v = _after_label(text, "wafer_size")
    if v:
        m = re.search(r"(\d+)\s*-?\s*inch", v, re.I)
        out["wafer_size"] = f"{m.group(1)}-inch" if m else v  # 認不出就保留原值，交給檢查層判定不合法

    v = _after_label(text, "package_type", r"([A-Za-z]{2,5})")
    out["package_type"] = v.upper() if v else None

    v = _after_label(text, "die_count", r"([\d,\.]+)")
    if v:
        digits = v.replace(",", "")
        out["die_count"] = int(digits) if digits.isdigit() else v  # 非整數保留原字串，檢查層會標為錯誤

    v = _after_label(text, "unit_price", r"(?:NT\$|US\$|\$)?\s*([\d,]+(?:\.\d+)?)")
    if v:
        out["unit_price"] = float(v.replace(",", ""))

    v = _after_label(text, "price_unit")
    if v:
        m = re.search(r"per\s*(wafer|1\s*k\s*units?)", v, re.I)
        if m:
            out["price_unit"] = "per wafer" if m.group(1).lower() == "wafer" else "per 1k units"
        else:
            out["price_unit"] = v

    v = _after_label(text, "delivery_date")
    out["delivery_date"] = normalize_date(v) if v else None
    return out
