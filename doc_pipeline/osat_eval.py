"""V2 評估：由 `python evaluate.py --doctype osat` 呼叫。

每份文件只做一次 OCR，同時用「正規化後」與「OCR 原始輸出」各抽取一次，
用來比較正規化對不同 tessdata 版本的影響。電子 PDF 不經 OCR，兩者相同。
"""
import csv
import os
from pathlib import Path

from osat_order import ORDER_FIELDS, extract_order
from osat_validators import PASS, load_masters, validate_order
from pdf_router import read_pdf

BINS = [("電子 PDF", None), ("|θ| < 1°", (0, 1)), ("1° ≤ |θ| < 3°", (1, 3)),
        ("3° ≤ |θ| < 6°", (3, 6)), ("6° ≤ |θ| ≤ 10°", (6, 10.01)), ("模糊 blur", None)]


def _same(k, pred, truth):
    if pred in (None, ""):
        return truth in (None, "")
    if k == "unit_price":
        try:
            return abs(float(pred) - float(truth)) < 0.005
        except (TypeError, ValueError):
            return False
    if k == "die_count":
        return str(pred) == str(int(truth))
    return str(pred).strip() == str(truth).strip()


def _bin(row):
    if row["variant"] == "electronic":
        return BINS[0][0]
    if row["variant"] == "blur":  # 模糊樣本單獨一組，不混入傾斜角區間
        return BINS[-1][0]
    a = abs(float(row["angle"]))
    return next(name for name, r in BINS[1:-1] if r[0] <= a < r[1])


def run(docs: str, truth: str, out: str):
    rows = list(csv.DictReader(open(truth, encoding="utf-8-sig")))
    masters = load_masters()
    res = []
    for row in rows:
        r = read_pdf(str(Path(docs) / row["file"]))
        rec = {"file": row["file"], "variant": row["variant"], "route": r["route"], "bin": _bin(row),
               "blur_k": row.get("blur_k", ""), "angle_true": float(row["angle"]),
               "angle_measured": r["skew_angles"][0] if r["skew_angles"] else "",
               "expected_grade": row["expected_grade"], "injected_error": row["injected_error"]}
        rec["angle_err"] = abs(rec["angle_measured"] - rec["angle_true"]) if r["skew_angles"] else ""
        for tag, text in [("norm", r["text"]), ("raw", r["raw_text"])]:
            pred = extract_order(text)
            v = validate_order(pred, masters)
            ok = {k: _same(k, pred[k], row[k]) for k in ORDER_FIELDS}
            rec.update({f"{tag}_pred_{k}": pred[k] for k in ORDER_FIELDS})
            rec.update({f"{tag}_ok_{k}": ok[k] for k in ORDER_FIELDS})
            rec[f"{tag}_doc_correct"] = all(ok.values())
            rec[f"{tag}_grade"] = v["grade"]
            rec[f"{tag}_grade_ok"] = v["grade"] == row["expected_grade"]
            rec[f"{tag}_reasons"] = "; ".join(v["errors"] + v["reviews"])
        rec["ocr_text"] = r["raw_text"][:600]
        res.append(rec)

    with open(out, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(res[0].keys()))
        w.writeheader()
        w.writerows(res)

    n = len(res)
    frac = lambda k, m: f"{k}/{m} ({k / m:.0%})" if m else "n/a"
    print(f"\n=== V2 封測客戶訂單  共 {n} 份  tessdata={os.environ.get('TESSDATA_PREFIX', '(預設)')} ===")
    for v in ("electronic", "scan", "blur"):
        want = "electronic" if v == "electronic" else "scan"
        sub = [x for x in res if x["variant"] == v]
        if sub:
            print(f"分流正確 {v:10s}: {frac(sum(x['route'] == want for x in sub), len(sub))}")
    errs = [x["angle_err"] for x in res if x["angle_err"] != ""]
    if errs:
        print(f"傾斜角量測誤差（掃描檔 {len(errs)} 份）: 平均 {sum(errs) / len(errs):.2f}°，最大 {max(errs):.2f}°")

    print(f"\n{'':22s}{'正規化後':>14s}{'未正規化':>14s}")
    for k, zh in ORDER_FIELDS.items():
        print(f"欄位正確率 {k:16s}" + "".join(f"{frac(sum(x[f'{t}_ok_{k}'] for x in res), n):>16s}" for t in ("norm", "raw")))
    for label, key in [("整份全對率", "doc_correct"), ("分級正確率", "grade_ok")]:
        print(f"{label:18s}" + "".join(f"{frac(sum(x[f'{t}_{key}'] for x in res), n):>16s}" for t in ("norm", "raw")))
    for t, name in (("norm", "正規化後"), ("raw", "未正規化")):
        passed = [x for x in res if x[f"{t}_grade"] == PASS]
        leak = [x["file"] for x in res if x[f"{t}_grade"] == PASS and x["expected_grade"] != PASS]
        print(f"[{name}] 自動通過 {len(passed)} 份，其中整份全對 {sum(x[f'{t}_doc_correct'] for x in passed)} 份；"
              f"應攔未攔 {len(leak)} 份 {leak if leak else ''}")

    print("\n--- 依傾斜角區間（正規化後）---")
    print(f"{'區間':16s}{'份數':>4s}{'角度誤差平均':>12s}{'整份全對':>12s}{'分級正確':>12s}")
    for name, _ in BINS:
        sub = [x for x in res if x["bin"] == name]
        e = [x["angle_err"] for x in sub if x["angle_err"] != ""]
        es = f"{sum(e) / len(e):.2f}°" if e else "-"
        print(f"{name:16s}{len(sub):>4d}{es:>14s}{frac(sum(x['norm_doc_correct'] for x in sub), len(sub)):>14s}"
              f"{frac(sum(x['norm_grade_ok'] for x in sub), len(sub)):>14s}")

    blur = [x for x in res if x["variant"] == "blur"]
    if blur:
        print("\n--- 模糊樣本逐份（正規化後）---")
        for x in blur:
            n_ok = sum(x[f"norm_ok_{k}"] for k in ORDER_FIELDS)
            wrong = [k for k in ORDER_FIELDS if not x[f"norm_ok_{k}"]]
            print(f"{x['file']}  模糊核 {x['blur_k']:>2}  欄位 {n_ok}/10  分級 {x['norm_grade']}（應為 {x['expected_grade']}）"
                  + (f"  讀錯：{', '.join(wrong)}" if wrong else ""))
    print(f"明細已寫入 {out}")
