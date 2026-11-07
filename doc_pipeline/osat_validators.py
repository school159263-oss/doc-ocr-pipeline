"""V2：封測客戶訂單的檢查層。每張訂單分三級並附原因：
    通過         — 所有檢查都沒問題，可自動進系統
    需人工確認   — 資料本身合法，但與主檔對不上、需要人判斷（批號待確認、單價與報價不符、客戶名稱近似）
    明顯錯誤     — 缺欄位、格式或列舉值不合法、料號不存在、客戶完全不認得
主檔全部是虛構資料，放在 master_data/。
"""
import csv
from datetime import date
from pathlib import Path

from osat_order import ORDER_FIELDS, PACKAGE_TYPES, PRICE_UNITS, WAFER_SIZES
from validators import vendor_check  # 沿用 V1 的 difflib 模糊比對與 0.85 門檻（唯讀引用）

PASS, REVIEW, ERROR = "通過", "需人工確認", "明顯錯誤"
MASTER_DIR = Path(__file__).resolve().parent / "master_data"


def _rows(name):
    return list(csv.DictReader(open(MASTER_DIR / name, encoding="utf-8-sig")))


def load_masters() -> dict:
    return {
        "customers": [r["customer"] for r in _rows("osat_customers.csv")],
        "part_map": {r["customer_part_no"]: r for r in _rows("osat_part_map.csv")},
        "lots": {r["wafer_lot_id"]: r for r in _rows("osat_wafer_inventory.csv")},
        "prices": {(r["customer_part_no"], r["price_unit"]): float(r["unit_price"]) for r in _rows("osat_price_list.csv")},
    }


def validate_order(rec: dict, masters: dict = None) -> dict:
    """回傳 {grade, errors, reviews, internal_part_no, lot_status, price_diff}。"""
    m = masters or load_masters()
    errors, reviews = [], []

    for k, zh in ORDER_FIELDS.items():
        if rec.get(k) in (None, ""):
            errors.append(f"缺少欄位：{zh}")

    if rec.get("wafer_size") and rec["wafer_size"] not in WAFER_SIZES:
        errors.append(f"晶圓尺寸不合法：{rec['wafer_size']}（只接受 {' / '.join(WAFER_SIZES)}）")
    if rec.get("package_type") and rec["package_type"] not in PACKAGE_TYPES:
        errors.append(f"封裝型式不合法：{rec['package_type']}（只接受 {' / '.join(PACKAGE_TYPES)}）")
    if rec.get("price_unit") and rec["price_unit"] not in PRICE_UNITS:
        errors.append(f"計價單位不合法：{rec['price_unit']}")
    dc = rec.get("die_count")
    if dc not in (None, "") and not (isinstance(dc, int) and dc > 0):
        errors.append(f"晶粒數量必須是正整數：{dc}")
    up = rec.get("unit_price")
    if up is not None and up <= 0:
        errors.append("單價必須大於 0")
    dd = rec.get("delivery_date")
    if dd:
        try:
            date.fromisoformat(dd)
        except ValueError:
            errors.append(f"交期格式不正確：{dd}")

    # 客戶名稱：與客戶主檔模糊比對
    vc = vendor_check(rec.get("customer"), master=m["customers"])
    if vc["status"] == "suspect":
        reviews.append(f"客戶名稱疑似「{vc['candidate']}」（相似度 {vc['score']}），不完全相符")
    elif vc["status"] == "new":
        errors.append(f"客戶不在主檔：{rec.get('customer')}")

    # 客戶料號 → 內部料號
    pn = rec.get("customer_part_no")
    part = m["part_map"].get(pn) if pn else None
    if pn and not part:
        errors.append(f"客戶料號不在對照表：{pn}")

    # 晶圓批號：查不到不判錯，標「待確認」（可能尚未入庫）
    lot = rec.get("wafer_lot_id")
    lot_status = ""
    if lot:
        lot_status = "在庫" if lot in m["lots"] else "待確認"
        if lot_status == "待確認":
            reviews.append(f"晶圓批號 {lot} 不在來料庫存，待確認")

    # 單價與報價表比對（容許 0.005 尾差）
    price_diff = None
    if part and up is not None and rec.get("price_unit") in PRICE_UNITS:
        quote = m["prices"].get((pn, rec["price_unit"]))
        if quote is None:
            reviews.append(f"報價表沒有 {pn}（{rec['price_unit']}）的報價")
        elif abs(up - quote) > 0.005:
            price_diff = round(up - quote, 2)
            reviews.append(f"單價 {up:,.2f} 與報價 {quote:,.2f} 不符（差 {price_diff:+,.2f}）")

    grade = ERROR if errors else (REVIEW if reviews else PASS)
    return {
        "grade": grade, "errors": errors, "reviews": reviews,
        "internal_part_no": part["internal_part_no"] if part else "",
        "lot_status": lot_status, "price_diff": price_diff,
    }


def next_action(result: dict) -> str:
    """給 demo 表格用的一句話處理建議。"""
    if result["grade"] == PASS:
        return "自動建單"
    if result["grade"] == ERROR:
        return "退回客戶／業務更正"
    acts = []
    for r in result["reviews"]:
        if "批號" in r:
            acts.append("向倉庫確認來料")
        elif "單價" in r or "報價" in r:
            acts.append("業務確認價格")
        elif "客戶名稱" in r:
            acts.append("確認客戶名稱")
    return "、".join(dict.fromkeys(acts)) or "人工確認"
