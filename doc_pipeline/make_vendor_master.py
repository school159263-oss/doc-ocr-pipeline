"""產生 vendor_master.csv(模擬廠商主資料)。

來源:
  1. generate_docs.py 產生文件時使用的 12 家虛構廠商(也就是 ground_truth 的廠商名稱來源,不是 OCR 輸出)
  2. 另加 3 家「名稱相近但確實不同」的虛構廠商,用來測試模糊比對會不會把兩家真實廠商混為一談
產生後會驗證:兩批 ground truth 裡出現過的每一家廠商都在主資料裡(若有檔案的話)。
"""
import csv
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from generate_docs import VENDORS_ZH  # noqa: E402

LOOKALIKES = [
    "宏瑞科技股份有限公司",      # 與「宏瑞虛構電子股份有限公司」只差中間幾個字
    "甲辰精密科技有限公司",      # 與「甲辰精密工業股份有限公司」相近
    "星耀測試能源股份有限公司",  # 與「星耀測試光電股份有限公司」相近
]

vendors = list(VENDORS_ZH) + LOOKALIKES
with open(HERE / "vendor_master.csv", "w", newline="", encoding="utf-8-sig") as fh:
    w = csv.writer(fh)
    w.writerow(["vendor"])
    for v in vendors:
        w.writerow([v])
print(f"vendor_master.csv:{len(vendors)} 家(其中 {len(LOOKALIKES)} 家為名稱相近的干擾項)")

for name in ("ground_truth.csv", "ground_truth_holdout.csv"):
    p = HERE / name
    if p.exists():
        gt = {r["vendor"] for r in csv.DictReader(open(p, encoding="utf-8-sig"))}
        missing = gt - set(vendors)
        print(f"{name}: {len(gt)} 家廠商,不在主資料的有 {len(missing)} 家", sorted(missing) if missing else "")
