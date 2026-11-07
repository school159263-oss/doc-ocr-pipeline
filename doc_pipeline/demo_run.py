"""V2 demo：處理 samples/ 裡的封測客戶訂單，在終端機印出對照表。

    python demo_run.py

samples/ 不存在時才自動產生範例檔（generate_osat_samples.make_samples）。
"""
import logging
import sys
import unicodedata
from pathlib import Path

from osat_order import extract_order
from osat_validators import load_masters, next_action, validate_order
from pdf_router import read_pdf

HERE = Path(__file__).resolve().parent
SAMPLES = HERE / "samples"


def _w(s: str) -> int:
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def _pad(s: str, width: int) -> str:
    return s + " " * (width - _w(s))


def print_table(header, rows):
    widths = [max(_w(str(r[i])) for r in [header] + rows) for i in range(len(header))]
    line = lambda r: "｜".join(_pad(str(c), w) for c, w in zip(r, widths))
    print(line(header))
    print("-" * (sum(widths) + 2 * (len(widths) - 1)))
    for r in rows:
        print(line(r))


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s", stream=sys.stdout)
    if not SAMPLES.exists():
        print("samples/ 不存在，自動產生範例檔……")
        from generate_osat_samples import make_samples
        make_samples(SAMPLES)

    masters = load_masters()
    rows, details = [], []
    for pdf in sorted(SAMPLES.glob("*.pdf")):
        r = read_pdf(str(pdf))
        rec = extract_order(r["text"])
        v = validate_order(rec, masters)
        route = "電子 PDF（直接讀文字）" if r["route"] == "electronic" else \
            "掃描檔 OCR（傾斜 " + "、".join(f"{a:+.2f}°" for a in r["skew_angles"]) + "）"
        part = rec["customer_part_no"] or "（未讀到）"
        if v["internal_part_no"]:
            part += f" → {v['internal_part_no']}"
        lot = rec["wafer_lot_id"] or "（未讀到）"
        if v["lot_status"]:
            lot += f"（{v['lot_status']}）"
        rows.append([pdf.name, route, part, lot, v["grade"], next_action(v)])
        details.append((pdf.name, v["errors"] + v["reviews"]))

    print()
    print_table(["檔名", "處理路徑", "料號", "批號", "檢查結果", "需要的處理"], rows)
    print("\n原因：")
    for name, reasons in details:
        print(f"  {name}")
        for x in reasons or ["全部檢查通過"]:
            print(f"    - {x}")


if __name__ == "__main__":
    main()
