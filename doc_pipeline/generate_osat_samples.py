"""V2：產生虛構的封測客戶訂單。

    python generate_osat_samples.py --samples   # samples/：4 份 demo 範例，涵蓋通過／需人工確認／明顯錯誤
    python generate_osat_samples.py --eval      # docs_osat/ + ground_truth_osat.csv：24 份評估集（含 4 份模糊樣本）
    python generate_osat_samples.py             # 兩者都產生

客戶、料號、批號全部虛構（ACME Semi、OSAT-CHIP-99xx、LOT-2026-xxx），與 master_data/ 對應。
標準答案直接取自產生時的值，預期分級由同一套檢查規則套用在標準答案上得到。固定亂數種子，可重現。
"""
import argparse
import csv
import io
import random
from datetime import date, timedelta
from pathlib import Path

import cv2
import numpy as np
import pymupdf
from PIL import Image

from generate_docs import DEFAULT_FONT, register_font  # 沿用 V1 的字型載入（唯讀引用）
from osat_order import ORDER_FIELDS, PACKAGE_TYPES
from osat_validators import load_masters, validate_order

HERE = Path(__file__).resolve().parent
SEED = 20261107
SCAN_DPI = 200

# 標籤：中文 + 英文（英文可在中文被 OCR 讀錯時協助定位）
LABEL_TEXT = {
    "po_no": ("客戶PO號", "PO No."),
    "customer": ("客戶名稱", "Customer"),
    "customer_part_no": ("客戶料號", "Customer P/N"),
    "wafer_lot_id": ("晶圓批號", "Wafer Lot"),
    "wafer_size": ("晶圓尺寸", "Wafer Size"),
    "package_type": ("封裝型式", "Package"),
    "die_count": ("晶粒數量", "Die Qty"),
    "unit_price": ("單價", "Unit Price"),
    "price_unit": ("計價單位", "Price Unit"),
    "delivery_date": ("交期", "Delivery"),
}


# ---------- 訂單內容 ----------
def make_order(rng: random.Random, masters: dict, error: str = "") -> dict:
    part = masters["part_map"][rng.choice(sorted(masters["part_map"]))]
    pn, customer = part["customer_part_no"], part["customer"]
    lot = rng.choice(sorted(k for k, v in masters["lots"].items() if v["customer"] == customer))
    price_unit, quote = next((u, p) for (k, u), p in masters["prices"].items() if k == pn)
    rec = {
        "po_no": f"PO-2026-{rng.randint(1000, 9999)}",
        "customer": customer,
        "customer_part_no": pn,
        "wafer_lot_id": lot,
        "wafer_size": masters["lots"][lot]["wafer_size"],
        "package_type": rng.choice(PACKAGE_TYPES),
        "die_count": rng.randint(20, 600) * 50,
        "unit_price": quote,
        "price_unit": price_unit,
        "delivery_date": (date(2026, 12, 1) + timedelta(days=rng.randint(0, 80))).isoformat(),
    }
    if error == "lot_missing":
        rec["wafer_lot_id"] = f"LOT-2026-Z{rng.randint(10, 99)}"
    elif error == "price_mismatch":
        step = 150 if price_unit == "per wafer" else 6.5
        rec["unit_price"] = round(quote + rng.choice([-1, 1]) * step, 2)
    elif error == "part_unknown":
        rec["customer_part_no"] = f"OSAT-CHIP-99{rng.randint(50, 99)}"
    elif error == "customer_typo":
        rec["customer"] = customer[:-1]  # 少打最後一個字母，例如 ACME Sem
    return rec


def fmt_value(k, v):
    if k == "die_count":
        return f"{v:,}"
    if k == "unit_price":
        return f"US$ {v:,.2f}"
    if k == "delivery_date":
        return v.replace("-", "/")
    return str(v)


# ---------- 繪製 ----------
def draw_order_pdf(rec: dict, font: str) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    W, H = A4
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setFont(font, 20)
    c.drawString(60, H - 70, "封測客戶訂單  OSAT Customer Order")
    c.setFont(font, 12)
    y = H - 120
    for k in ORDER_FIELDS:
        zh, en = LABEL_TEXT[k]
        c.drawString(60, y, f"{zh} {en}：{fmt_value(k, rec[k])}")  # 標籤與值放同一行，文字層與 OCR 都不會拆開
        y -= 28
    c.setFont(font, 9)
    c.drawString(60, 60, "本文件為虛構測試資料 Fictional test data")
    c.showPage()
    c.save()
    return buf.getvalue()


def scan_from_pdf(pdf_bytes: bytes, angle: float, noise: float, nrng, blur_k: int = 3) -> Image.Image:
    """電子 PDF → 灰階圖片 → 旋轉 angle 度（逆時針為正）→ 高斯模糊（核大小 blur_k）+ 高斯雜訊。"""
    pix = pymupdf.open(stream=pdf_bytes, filetype="pdf")[0].get_pixmap(dpi=SCAN_DPI, colorspace=pymupdf.csGRAY)
    a = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
    h, w = a.shape
    M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    a = cv2.warpAffine(a, M, (w, h), flags=cv2.INTER_LINEAR, borderValue=255)
    a = cv2.GaussianBlur(a, (blur_k, blur_k), 0)
    a = np.clip(a.astype("int16") + nrng.normal(0, noise, a.shape), 0, 255).astype("uint8")
    return Image.fromarray(a)


def save_image_pdf(img: Image.Image, path: Path):
    img.save(path, "PDF", resolution=SCAN_DPI)  # 只有影像，沒有文字層


# ---------- 產生 ----------
def make_samples(out_dir=HERE / "samples", font_path=DEFAULT_FONT):
    """demo 用，涵蓋三種分級：
    - order_acme_*：同一張訂單的電子版與掃描版，故意放兩個錯誤（批號不存在、單價不符）→ 需人工確認
    - order_globex_pass_scan：所有檢查都通過的掃描檔 → 通過
    - order_initech_error_electronic：料號不在對照表 → 明顯錯誤"""
    font = register_font(font_path)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rec = {
        "po_no": "PO-2026-0412", "customer": "ACME Semi", "customer_part_no": "OSAT-CHIP-9901",
        "wafer_lot_id": "LOT-2026-X89",  # 錯誤 1：庫存只有 LOT-2026-X88
        "wafer_size": "12-inch", "package_type": "BGA", "die_count": 12500,
        "unit_price": 3400.00,           # 錯誤 2：報價 3,250.00
        "price_unit": "per wafer", "delivery_date": "2026-12-18",
    }
    pdf = draw_order_pdf(rec, font)
    (out / "order_acme_electronic.pdf").write_bytes(pdf)
    save_image_pdf(scan_from_pdf(pdf, 3.5, 10, np.random.default_rng(SEED)), out / "order_acme_scan.pdf")

    ok = {
        "po_no": "PO-2026-0518", "customer": "Globex Microdevices", "customer_part_no": "OSAT-CHIP-9903",
        "wafer_lot_id": "LOT-2026-C41", "wafer_size": "12-inch", "package_type": "QFN", "die_count": 8400,
        "unit_price": 2180.00, "price_unit": "per wafer", "delivery_date": "2027-01-15",
    }
    save_image_pdf(scan_from_pdf(draw_order_pdf(ok, font), -2.0, 10, np.random.default_rng(SEED + 1)),
                   out / "order_globex_pass_scan.pdf")

    bad = {
        "po_no": "PO-2026-0603", "customer": "Initech Silicon",
        "customer_part_no": "OSAT-CHIP-9977",  # 錯誤：對照表沒有這個料號
        "wafer_lot_id": "LOT-2026-D52", "wafer_size": "8-inch", "package_type": "CSP", "die_count": 36000,
        "unit_price": 118.75, "price_unit": "per 1k units", "delivery_date": "2026-12-28",
    }
    (out / "order_initech_error_electronic.pdf").write_bytes(draw_order_pdf(bad, font))
    print(f"已產生 4 份範例 -> {out}（掃描版分別旋轉 +3.5° 與 -2.0°、雜訊 σ=10）")


# 評估集：4 份電子 + 16 份掃描；掃描檔中 12 份傾斜 ≥ 1°（佔全部 60%）
EVAL_PLAN = (
    [("electronic", None)] * 4
    + [("scan", (0.2, 0.9))] * 4
    + [("scan", (1.0, 3.0))] * 4
    + [("scan", (3.0, 6.0))] * 4
    + [("scan", (6.0, 10.0))] * 4
)
EVAL_ERRORS = [""] * 10 + ["lot_missing"] * 3 + ["price_mismatch"] * 3 + ["part_unknown"] * 2 + ["customer_typo"] * 2
# 模糊樣本另外附加在後面（o21～o24），不影響前 20 份的亂數序列：(高斯模糊核大小, 刻意放的錯誤)
BLUR_PLAN = [(5, ""), (9, "price_mismatch"), (13, ""), (17, "lot_missing")]


def make_eval_set(out_dir=HERE / "docs_osat", truth=HERE / "ground_truth_osat.csv", font_path=DEFAULT_FONT):
    font = register_font(font_path)
    masters = load_masters()
    rng = random.Random(SEED)
    nrng = np.random.default_rng(SEED)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("o[0-9][0-9]_*.pdf"):
        old.unlink()
    errors = EVAL_ERRORS[:]
    rng.shuffle(errors)

    rows = []
    for i, ((variant, rng_range), err) in enumerate(zip(EVAL_PLAN, errors), 1):
        rec = make_order(rng, masters, err)
        pdf = draw_order_pdf(rec, font)
        angle = 0.0
        if variant == "electronic":
            name = f"o{i:02d}_electronic.pdf"
            (out / name).write_bytes(pdf)
        else:
            angle = round(rng.choice([-1, 1]) * rng.uniform(*rng_range), 2)
            noise = round(rng.uniform(6, 14), 1)
            name = f"o{i:02d}_scan.pdf"
            save_image_pdf(scan_from_pdf(pdf, angle, noise, nrng), out / name)
        rows.append({"file": name, **rec, "variant": variant, "angle": angle, "blur_k": 3 if variant == "scan" else 0,
                     "injected_error": err, "expected_grade": validate_order(rec, masters)["grade"]})

    for j, (k, err) in enumerate(BLUR_PLAN, len(rows) + 1):
        rec = make_order(rng, masters, err)
        angle = round(rng.uniform(-1.0, 1.0), 2)  # 與 V1 的 blur 類相同：輕微傾斜 + 明顯模糊
        name = f"o{j:02d}_blur.pdf"
        save_image_pdf(scan_from_pdf(draw_order_pdf(rec, font), angle, 8, nrng, blur_k=k), out / name)
        rows.append({"file": name, **rec, "variant": "blur", "angle": angle, "blur_k": k,
                     "injected_error": err, "expected_grade": validate_order(rec, masters)["grade"]})

    with open(truth, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"已產生 {len(rows)} 份評估訂單 -> {out}\n標準答案 -> {truth}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", action="store_true")
    ap.add_argument("--eval", action="store_true")
    ap.add_argument("--font", default=DEFAULT_FONT)
    a = ap.parse_args()
    both = not (a.samples or a.eval)
    if a.samples or both:
        make_samples(font_path=a.font)
    if a.eval or both:
        make_eval_set(font_path=a.font)
