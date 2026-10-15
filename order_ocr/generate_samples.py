"""產生模擬的「掃描採購單」影像與正確答案，供 OCR 流程測試與準確率評估使用。

輸出：
  data/master_customers.csv  客戶主檔
  data/master_items.csv      料號主檔
  samples/order_XXX.png      模擬掃描的採購單
  samples/ground_truth.json  每張單據的正確欄位（評估用）

所有公司、料號、金額皆為虛構資料。
"""
import csv
import json
import random
from datetime import date, timedelta
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).parent
DATA = ROOT / "data"
SAMPLES = ROOT / "samples"
FONT_PATH = "C:/Windows/Fonts/msjh.ttc"

CUSTOMERS = [
    ("C1001", "宏晶半導體股份有限公司"),
    ("C1002", "聯創微電子股份有限公司"),
    ("C1003", "台芯科技股份有限公司"),
    ("C1004", "晶元通訊有限公司"),
    ("C1005", "鼎峰電子股份有限公司"),
    ("C1006", "旭光積體電路股份有限公司"),
]

# 料號刻意包含 0/O、1/I、8/B、5/S 等容易誤讀的字元
ITEMS = [
    ("FCBGA-3535-A01", "覆晶球柵陣列封裝 35x35mm", 182.0),
    ("FCBGA-4545-B08", "覆晶球柵陣列封裝 45x45mm", 265.0),
    ("QFN-0505-C10", "四方平面無引腳封裝 5x5mm", 3.6),
    ("QFN-0808-C18", "四方平面無引腳封裝 8x8mm", 5.2),
    ("WB-AU08-S05", "金線打線封裝 0.8mil", 12.5),
    ("WB-CU10-S01", "銅線打線封裝 1.0mil", 8.8),
    ("SIP-1210-M02", "系統級封裝模組 12x10mm", 96.0),
    ("CP-WT12-T01", "晶圓針測 12吋", 1450.0),
    ("FT-LG-T08", "成品最終測試 邏輯IC", 1.85),
    ("BMP-CU-P15", "銅柱凸塊製程", 38.0),
]

DATE_STYLES = ["iso", "slash", "roc", "zh"]


def fmt_date(d: date, style: str) -> str:
    if style == "iso":
        return d.isoformat()
    if style == "slash":
        return f"{d.year}/{d.month}/{d.day}"
    if style == "roc":
        return f"{d.year - 1911}/{d.month:02d}/{d.day:02d}"
    return f"{d.year}年{d.month}月{d.day}日"


def fmt_money(x: float) -> str:
    return f"{x:,.2f}"


def make_order(i: int, rng: random.Random) -> dict:
    cust_code, cust_name = rng.choice(CUSTOMERS)
    order_date = date(2026, 1, 5) + timedelta(days=rng.randint(0, 250))
    delivery = order_date + timedelta(days=rng.randint(7, 45))
    lines = []
    for code, desc, std_price in rng.sample(ITEMS, rng.randint(1, 5)):
        qty = rng.choice([500, 1000, 2000, 2500, 5000, 10000, 12000, 20000]) if std_price < 50 else rng.choice([50, 100, 120, 200, 300, 500])
        price = round(std_price * rng.uniform(0.92, 1.08), 2)
        lines.append({"item_code": code, "description": desc, "quantity": qty,
                      "unit_price": price, "amount": round(qty * price, 2)})
    return {
        "file": f"order_{i:03d}.png",
        "customer_code": cust_code,
        "customer_name": cust_name,
        "po_number": f"PO{order_date.strftime('%y%m')}{rng.randint(1000, 9999)}",
        "order_date": order_date.isoformat(),
        "delivery_date": delivery.isoformat(),
        "lines": lines,
        "total_amount": round(sum(l["amount"] for l in lines), 2),
        "_date_style": rng.choice(DATE_STYLES),
    }


def render(order: dict, rng: random.Random, difficulty: str) -> Image.Image:
    W, H = 1240, 1754  # A4 @150dpi
    img = Image.new("L", (W, H), 255)
    d = ImageDraw.Draw(img)
    f = lambda s: ImageFont.truetype(FONT_PATH, s)
    style = order["_date_style"]

    d.text((W // 2, 90), "採 購 單", font=f(56), fill=0, anchor="mm")
    d.text((W // 2, 150), "PURCHASE ORDER", font=f(26), fill=60, anchor="mm")
    y = 220
    d.text((80, y), f"買方：{order['customer_name']}", font=f(28), fill=0)
    d.text((780, y), f"採購單號：{order['po_number']}", font=f(26), fill=0)
    y += 55
    d.text((80, y), "供應商：XX精密工業股份有限公司 台中廠", font=f(24), fill=40)
    d.text((780, y), f"訂購日期：{fmt_date(date.fromisoformat(order['order_date']), style)}", font=f(26), fill=0)
    y += 50
    d.text((780, y), f"需求交期：{fmt_date(date.fromisoformat(order['delivery_date']), style)}", font=f(26), fill=0)
    y += 80

    cols = [80, 140, 420, 760, 900, 1040, 1180]
    heads = ["項", "料號", "品名規格", "數量", "單價", "金額"]
    d.rectangle([cols[0], y, cols[-1], y + 50], outline=0, width=2)
    for c, h in zip(cols, heads):
        d.text((c + 10, y + 10), h, font=f(24), fill=0)
    y += 50
    for n, l in enumerate(order["lines"], 1):
        d.rectangle([cols[0], y, cols[-1], y + 56], outline=0, width=1)
        cells = [str(n), l["item_code"], l["description"], f"{l['quantity']:,}", fmt_money(l["unit_price"]), fmt_money(l["amount"])]
        for c, v in zip(cols, cells):
            d.text((c + 8, y + 14), v, font=f(20 if c == 420 else 22), fill=0)
        y += 56
    for c in cols:
        d.line([c, y - 56 * len(order["lines"]) - 50, c, y], fill=0, width=1)
    y += 30
    d.text((760, y), f"合計（未稅）：NT$ {fmt_money(order['total_amount'])}", font=f(28), fill=0)
    y += 90
    d.text((80, y), "備註：請依交期分批出貨，出貨時請附出貨單與檢驗報告。", font=f(22), fill=50)
    d.text((80, y + 40), "採購承辦：＿＿＿＿＿　主管核准：＿＿＿＿＿", font=f(22), fill=50)

    img = img.convert("RGB")
    if difficulty != "clean":
        # 紅色印章壓在合計附近
        stamp = Image.new("RGBA", (220, 220), (0, 0, 0, 0))
        sd = ImageDraw.Draw(stamp)
        sd.ellipse([10, 10, 210, 210], outline=(200, 30, 30, 170), width=8)
        sd.text((110, 110), "採購專用章", font=f(30), fill=(200, 30, 30, 170), anchor="mm")
        img.paste(stamp, (900 + rng.randint(-60, 20), y - 200 + rng.randint(-30, 30)), stamp)

    if difficulty in ("noisy", "hard"):
        img = img.rotate(rng.uniform(-1.5, 1.5), expand=False, fillcolor=(250, 250, 250))
        img = img.filter(ImageFilter.GaussianBlur(0.6 if difficulty == "noisy" else 0.8))
        px = img.load()
        for _ in range(3000 if difficulty == "noisy" else 6000):
            x, yy = rng.randrange(W), rng.randrange(H)
            v = rng.randint(0, 120)
            px[x, yy] = (v, v, v)
    if difficulty == "hard":
        img = img.resize((int(W * 0.7), int(H * 0.7))).resize((W, H))  # 模擬低解析度傳真
    return img


def main(n: int = 20, seed: int = 42, out: Path = SAMPLES):
    rng = random.Random(seed)
    DATA.mkdir(exist_ok=True)
    out.mkdir(exist_ok=True)
    with open(DATA / "master_customers.csv", "w", newline="", encoding="utf-8-sig") as fp:
        w = csv.writer(fp)
        w.writerow(["customer_code", "customer_name"])
        w.writerows(CUSTOMERS)
    with open(DATA / "master_items.csv", "w", newline="", encoding="utf-8-sig") as fp:
        w = csv.writer(fp)
        w.writerow(["item_code", "description", "std_price"])
        w.writerows(ITEMS)

    truth = []
    for i in range(1, n + 1):
        order = make_order(i, rng)
        difficulty = ["clean", "stamp", "noisy", "hard"][(i - 1) % 4]
        render(order, rng, difficulty).save(out / order["file"], quality=80)
        order["difficulty"] = difficulty
        order.pop("_date_style")
        truth.append(order)
    (out / "ground_truth.json").write_text(json.dumps(truth, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已產生 {n} 張模擬採購單 → {out}")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", type=Path, default=SAMPLES)
    a = ap.parse_args()
    main(a.n, a.seed, a.out)
