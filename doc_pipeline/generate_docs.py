"""產生虛構測試文件(進料單 / 出貨單 / 發票)並同步寫出 ground_truth.csv。

標準答案直接取自產生文件時使用的值,不經過 OCR。全部資料皆為虛構。
固定亂數種子,重複執行會得到完全相同的結果。

用法:
    python generate_docs.py                 # 繁中版,讀 C:\\Windows\\Fonts\\msjh.ttc(微軟正黑體)
    python generate_docs.py --font 路徑      # 明確指定另一個中文字型檔(.ttc/.ttf)
    python generate_docs.py --lang en       # 英文版面,不需要中文字型(僅供無中文環境的冒煙測試)

找不到中文字型時會印出提示並退出,不會悄悄換成沒有中文的字型。
"""
import argparse
import csv
import io
import random
import sys
from pathlib import Path

DEFAULT_FONT = r"C:\Windows\Fonts\msjh.ttc"
SEED = 20261003
HERE = Path(__file__).resolve().parent

# ---------- 虛構資料 ----------
VENDORS_ZH = [
    "甲辰精密工業股份有限公司", "宏瑞虛構電子股份有限公司", "乙森科技有限公司",
    "新曜塑膠製品有限公司", "大川假想五金行", "旭昇示範材料股份有限公司",
    "丙禾包裝企業社", "星耀測試光電股份有限公司", "華穗模擬化工有限公司",
    "久安範例機械股份有限公司", "三橋虛構物流有限公司", "維晨樣本電子零件行",
]
VENDORS_EN = [
    "Alpha Materials Co.", "Brightline Components Ltd.", "Cedar Precision Inc.",
    "Delta Packaging Co.", "Evergreen Plastics Ltd.", "Falcon Metalworks Inc.",
    "Granite Logistics Co.", "Horizon Electronics Ltd.",
]
ITEMS_ZH = ["銅線 2.0mm", "鋁合金板", "包裝紙箱", "電阻 10K", "螺絲 M4", "塑膠粒 ABS",
            "電容 100uF", "散熱片", "鋼珠 6mm", "封裝膠帶"]
ITEMS_EN = ["Copper wire 2.0mm", "Aluminium plate", "Carton box", "Resistor 10K",
            "Screw M4", "ABS pellets", "Capacitor 100uF", "Heat sink", "Steel ball 6mm", "Sealing tape"]

# 文件種類 -> (中文標題, 英文標題, 單號前綴)
DOC_TYPES = {
    "receipt": ("進料單", "GOODS RECEIPT", "GR"),
    "shipment": ("出貨單", "SHIPPING NOTE", "SH"),
    "invoice": ("發票", "INVOICE", "INV"),
}

# 版本分配:(variant, 份數, 副檔名)。共 20 份
PLAN = [
    ("native", 10, "pdf"),       # 乾淨原生 PDF
    ("scan_png", 2, "png"),      # 輕微掃描效果,PNG
    ("scan_pdf", 2, "pdf"),      # 輕微掃描效果,影像型 PDF(無文字層)
    ("skew", 3, "jpg"),          # 明顯歪斜
    ("blur", 3, "png"),          # 明顯模糊 + 雜訊
]


# ---------- 欄位格式化 ----------
def fmt_amount(cents: int, style: int) -> str:
    v = cents / 100
    if cents % 100 == 0:
        body = f"{int(v):,}"
    else:
        body = f"{v:,.2f}"
    return [body, f"NT$ {body}", f"NT${body}", f"${body}"][style % 4]


def truth_amount(cents: int) -> str:
    if cents % 100 == 0:
        return str(cents // 100)
    return f"{cents / 100:.2f}".rstrip("0").rstrip(".")


def fmt_date(y: int, m: int, d: int, style: str, lang: str) -> str:
    roc = y - 1911
    return {
        "slash": f"{y}/{m:02d}/{d:02d}",
        "dash": f"{y}-{m:02d}-{d:02d}",
        "dot": f"{y}.{m:02d}.{d:02d}",
        "cjk": f"{y}年{m}月{d}日",
        "roc_slash": f"{roc}/{m:02d}/{d:02d}",
        "roc_cjk": f"民國{roc}年{m}月{d}日",
        "roc_dot": f"{roc}.{m:02d}.{d:02d}",
        "slash_nopad": f"{y}/{m}/{d}",
    }[style]


DATE_STYLES_ZH = ["slash", "dash", "cjk", "roc_slash", "roc_cjk", "dot"]
DATE_STYLES_EN = ["slash", "dash", "dot", "roc_slash"]
# 保留測試集:額外加入規則作者沒看過的寫法
DATE_STYLES_ZH_HOLDOUT = DATE_STYLES_ZH + ["roc_dot", "slash_nopad"]
DATE_STYLES_EN_HOLDOUT = DATE_STYLES_EN + ["roc_dot", "slash_nopad"]
HOLDOUT_SEED = 20261101


# ---------- 單筆文件內容(含標準答案) ----------
def make_record(rng: random.Random, idx: int, lang: str) -> dict:
    dtype = rng.choice(list(DOC_TYPES))
    zh_title, en_title, prefix = DOC_TYPES[dtype]
    y, m, d = 2026, rng.randint(6, 10), rng.randint(1, 28)
    if m == 10:
        d = rng.randint(1, 2)
    if dtype == "invoice":
        doc_no = f"{rng.choice(['AB', 'CD', 'EF', 'GH'])}-{rng.randint(10000000, 99999999)}"
    else:
        doc_no = f"{prefix}-{y}{m:02d}{d:02d}{rng.randint(1, 99):02d}"
    vendor = rng.choice(VENDORS_ZH if lang == "zh" else VENDORS_EN)
    items_pool = ITEMS_ZH if lang == "zh" else ITEMS_EN
    n_items = rng.randint(2, 4)
    items = []
    for name in rng.sample(items_pool, n_items):
        qty = rng.randint(1, 200)
        price_cents = rng.choice([rng.randint(5, 900) * 100, rng.randint(50, 9000) * 10 + rng.randint(0, 9)])
        items.append((name, qty, price_cents))
    subtotal = sum(q * p for _, q, p in items)
    return {
        "dtype": dtype, "title": zh_title if lang == "zh" else en_title,
        "doc_no": doc_no, "ymd": (y, m, d), "vendor": vendor,
        "items": items, "subtotal": subtotal, "tax": round(subtotal * 0.05),
    }


# ---------- 版面繪製 ----------
def draw_pdf(rec: dict, layout: str, lang: str, date_style: str, amt_style: int, font: str) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    W, H = A4
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    zh = lang == "zh"
    dtype = rec["dtype"]
    date_txt = fmt_date(*rec["ymd"], date_style, lang)

    # 標籤(依文件種類與版面變化,用到規則涵蓋的各種寫法)
    if zh:
        no_label = "發票號碼" if dtype == "invoice" else ("編號" if layout == "table" else "單號")
        date_label = "日期"
        vendor_label = {"receipt": "供應商", "shipment": "廠商", "invoice": "公司名稱"}[dtype]
        total_label = {"simple": "合計", "table": "總計", "box": "總金額", "summary": "應付金額", "stacked": "總計"}.get(layout, "總計")
        sub_label, tax_label = "合計" if dtype == "invoice" else "小計", "營業稅(5%)"
        hdr = ["品名", "數量", "單價", "金額"]
    else:
        no_label = "Invoice No." if dtype == "invoice" else "No."
        date_label = "Date"
        vendor_label = "Vendor"
        total_label = "Amount Due" if layout == "summary" else "Total"
        sub_label, tax_label = "Subtotal", "Tax (5%)"
        hdr = ["Item", "Qty", "Unit", "Amount"]

    c.setFont(font, 20)
    c.drawString(60, H - 70, rec["title"])
    c.setFont(font, 11)

    def money(cents):
        return fmt_amount(cents, amt_style)

    items = rec["items"]
    if layout == "simple":
        y = H - 120
        for lab, val in [(no_label, rec["doc_no"]), (date_label, date_txt), (vendor_label, rec["vendor"])]:
            c.drawString(60, y, f"{lab}:{' ' if not zh else ''}{val}" if not zh else f"{lab}：{val}")
            y -= 24
        y -= 16
        for name, q, p in items:
            c.drawString(60, y, f"{name}   x{q}   @{p / 100:,.2f}")
            y -= 20
        y -= 20
        c.drawString(60, y, f"{total_label}：{money(rec['subtotal'])}" if zh else f"{total_label}: {money(rec['subtotal'])}")
        rec["_total"] = rec["subtotal"]

    elif layout == "table":
        y = H - 110
        sep = "：" if zh else ": "
        for lab, val in [(vendor_label, rec["vendor"]), (date_label, date_txt), (no_label, rec["doc_no"])]:
            c.drawString(60, y, f"{lab}{sep}{val}")
            y -= 22
        y -= 14
        xs = [60, 300, 370, 450]
        for x, h in zip(xs, hdr):
            c.drawString(x, y, h)
        c.line(55, y - 5, W - 55, y - 5)
        y -= 24
        for name, q, p in items:
            c.drawString(xs[0], y, name)
            c.drawString(xs[1], y, str(q))
            c.drawString(xs[2], y, f"{p / 100:,.2f}")
            c.drawString(xs[3], y, f"{q * p / 100:,.2f}")
            y -= 20
        c.line(55, y + 8, W - 55, y + 8)
        y -= 14
        total = rec["subtotal"] + rec["tax"]
        for lab, val in [(sub_label, rec["subtotal"]), (tax_label, rec["tax"]), (total_label, total)]:
            c.drawString(330, y, lab)
            c.drawRightString(W - 60, y, money(val))
            y -= 22
        rec["_total"] = total

    elif layout == "summary":  # 保留測試集:總額在最上方的摘要區,標籤為「應付金額」;下方明細只有小計與稅額
        y = H - 105
        total = rec["subtotal"] + rec["tax"]
        c.drawString(60, y, f"{total_label}")
        c.drawRightString(W - 60, y, money(total))
        y -= 34
        sep = "：" if zh else ": "
        for lab, val in [(vendor_label, rec["vendor"]), (date_label, date_txt), (no_label, rec["doc_no"])]:
            c.drawString(60, y, f"{lab}{sep}{val}")
            y -= 22
        y -= 12
        for name, q, p in items:
            c.drawString(60, y, name)
            c.drawRightString(W - 60, y, f"{q} x {p / 100:,.2f}")
            y -= 20
        y -= 14
        for lab, val in [(sub_label, rec["subtotal"]), (tax_label, rec["tax"])]:
            c.drawString(330, y, lab)
            c.drawRightString(W - 60, y, money(val))
            y -= 22
        rec["_total"] = total

    elif layout == "stacked":  # 保留測試集:標籤在上、值在下一行,沒有冒號
        y = H - 110
        for lab, val in [(no_label, rec["doc_no"]), (date_label, date_txt), (vendor_label, rec["vendor"])]:
            c.drawString(60, y, lab)
            c.drawString(60, y - 16, val)
            y -= 44
        y -= 8
        for name, q, p in items:
            c.drawString(60, y, f"{name}  {q} x {p / 100:,.2f}")
            y -= 20
        y -= 16
        c.drawString(60, y, total_label)
        c.drawString(60, y - 16, money(rec["subtotal"]))
        rec["_total"] = rec["subtotal"]

    else:  # box:兩欄標頭(廠商與日期同一行)+ 右下角方框總金額
        y = H - 110
        c.drawString(60, y, f"{vendor_label}：{rec['vendor']}" if zh else f"{vendor_label}: {rec['vendor']}")
        c.drawString(360, y, f"{date_label}：{date_txt}" if zh else f"{date_label}: {date_txt}")
        y -= 24
        c.drawString(60, y, f"{no_label}：{rec['doc_no']}" if zh else f"{no_label}: {rec['doc_no']}")
        y -= 40
        for name, q, p in items:
            c.drawString(60, y, f"{name}")
            c.drawRightString(W - 60, y, f"{q} x {p / 100:,.2f}")
            y -= 20
        y -= 30
        c.rect(300, y - 12, W - 360, 36)
        lab = f"{total_label}  {money(rec['subtotal'])}"
        c.drawString(310, y, lab)
        rec["_total"] = rec["subtotal"]

    c.showPage()
    c.save()
    return buf.getvalue()


# ---------- 掃描效果 ----------
def render_page(pdf_bytes: bytes, scale: float = 2.0):
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(pdf_bytes)
    return pdf[0].render(scale=scale).to_pil().convert("RGB")


def degrade(img, variant: str, rng: random.Random, nrng):
    import cv2
    import numpy as np
    a = np.array(img)
    h, w = a.shape[:2]
    if variant == "skew":
        angle = rng.choice([-1, 1]) * rng.uniform(2.5, 4.0)
        blur_k, noise = 3, 6
    elif variant == "blur":
        angle = rng.uniform(-1.0, 1.0)
        blur_k, noise = 7, 14
    else:  # scan_png / scan_pdf:輕微
        angle = rng.uniform(-0.8, 0.8)
        blur_k, noise = 3, 4
    M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    a = cv2.warpAffine(a, M, (w, h), flags=cv2.INTER_LINEAR, borderValue=(255, 255, 255))
    a = cv2.GaussianBlur(a, (blur_k, blur_k), 0)
    a = np.clip(a.astype("int16") + nrng.normal(0, noise, a.shape), 0, 255).astype("uint8")
    from PIL import Image
    return Image.fromarray(a)


# ---------- 字型 ----------
def register_font(path: str) -> str:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    p = Path(path)
    if not p.exists():
        print(f"[錯誤] 找不到中文字型檔:{path}\n"
              f"  - 在 Windows 請確認 C:\\Windows\\Fonts\\msjh.ttc(微軟正黑體)存在\n"
              f"  - 或用 --font 明確指定另一個含繁體中文的 .ttc/.ttf\n"
              f"  - 只想先測試版面可改用 --lang en\n"
              f"為避免產生缺字的文件,程式不會自動改用其他字型,已結束。", file=sys.stderr)
        sys.exit(1)
    try:
        pdfmetrics.registerFont(TTFont("CJK", str(p), subfontIndex=0))
    except Exception as e:  # .ttf 不需要 subfontIndex 時的退路:仍是同一個檔案,不是換字型
        try:
            pdfmetrics.registerFont(TTFont("CJK", str(p)))
        except Exception:
            print(f"[錯誤] 字型檔無法載入:{path}\n  {e}", file=sys.stderr)
            sys.exit(1)
    return "CJK"


# ---------- 主流程 ----------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", choices=["zh", "en"], default="zh")
    ap.add_argument("--font", default=DEFAULT_FONT, help="中文字型檔路徑(預設微軟正黑體)")
    ap.add_argument("--out", default=None)
    ap.add_argument("--truth", default=None)
    ap.add_argument("--holdout", action="store_true",
                    help="產生保留測試集:換亂數種子、加入新版面與新日期寫法,輸出到 docs_holdout/ 與 ground_truth_holdout.csv")
    args = ap.parse_args()
    if args.out is None:
        args.out = str(HERE / ("docs_holdout" if args.holdout else "docs"))
    if args.truth is None:
        args.truth = str(HERE / ("ground_truth_holdout.csv" if args.holdout else "ground_truth.csv"))

    font = register_font(args.font) if args.lang == "zh" else "Helvetica"

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("d[0-9][0-9]_*"):  # 只清掉本腳本產生過的檔案
        old.unlink()

    seed = HOLDOUT_SEED if args.holdout else SEED
    rng = random.Random(seed)
    nrng = __import__("numpy").random.default_rng(seed)
    variants = [v for v, n, _ in PLAN for _ in range(n)]
    exts = {v: e for v, _, e in PLAN}
    rng.shuffle(variants)
    layouts = ["simple", "table", "box", "summary", "stacked"] if args.holdout else ["simple", "table", "box"]
    if args.holdout:
        date_styles = DATE_STYLES_ZH_HOLDOUT if args.lang == "zh" else DATE_STYLES_EN_HOLDOUT
    else:
        date_styles = DATE_STYLES_ZH if args.lang == "zh" else DATE_STYLES_EN

    rows = []
    for i, variant in enumerate(variants, 1):
        rec = make_record(rng, i, args.lang)
        layout = layouts[(i - 1) % len(layouts)]  # 版面輪流,確保各版面都有
        date_style = date_styles[(i - 1) % len(date_styles)]
        amt_style = rng.randint(0, 3)
        pdf_bytes = draw_pdf(rec, layout, args.lang, date_style, amt_style, font)
        name = f"d{i:02d}_{variant}.{exts[variant]}"
        path = out / name

        if variant == "native":
            path.write_bytes(pdf_bytes)
        else:
            img = degrade(render_page(pdf_bytes), variant, rng, nrng)
            if exts[variant] == "pdf":
                img.save(path, "PDF", resolution=144)
            elif exts[variant] == "jpg":
                img.save(path, "JPEG", quality=70)
            else:
                img.save(path, "PNG")

        y, m, d = rec["ymd"]
        rows.append({
            "file": name, "doc_no": rec["doc_no"], "date": f"{y:04d}-{m:02d}-{d:02d}",
            "vendor": rec["vendor"], "total": truth_amount(rec["_total"]),
            "doc_type": rec["dtype"], "layout": layout, "variant": variant,
            "date_style": date_style, "amount_style": amt_style,
        })

    with open(args.truth, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"已產生 {len(rows)} 份文件 -> {out}\n標準答案 -> {args.truth}(由產生時的值直接寫出)")


if __name__ == "__main__":
    main()
