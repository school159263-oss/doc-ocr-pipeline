"""用法:
    python evaluate.py --extractor rules
    python evaluate.py --extractor llm
    python evaluate.py --extractor routed

準備:
    docs/                放文件(pdf/png/jpg)
    ground_truth.csv     欄位:file,doc_no,date,vendor,total  (file 是 docs/ 內的檔名,答案請人工填)
輸出:
    results_<extractor>.csv   每筆的判讀結果、檢查問題、狀態、原始文字,方便回查
"""
import argparse
import csv
from pathlib import Path

from extractors import EXTRACTORS, FIELDS
from validators import validate, vendor_check, SIM_THRESHOLD, _load_master


def same(field, pred, truth):
    if pred in (None, "") or truth in (None, ""):
        return pred in (None, "") and truth in (None, "")
    if field == "total":
        try:
            return abs(float(pred) - float(truth)) < 0.01
        except ValueError:
            return False
    return str(pred).strip() == str(truth).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--extractor", default="rules", choices=EXTRACTORS.keys())
    ap.add_argument("--docs", default="docs")
    ap.add_argument("--truth", default="ground_truth.csv")
    ap.add_argument("--thresholds", default="0.80,0.85,0.90",
                    help="廠商相似度門檻的敏感度分析(逗號分隔)。主結果固定使用 validators.SIM_THRESHOLD")
    ap.add_argument("--out", default=None, help="結果檔路徑,預設 results_<extractor>.csv")
    args = ap.parse_args()

    extract = EXTRACTORS[args.extractor]
    truth_rows = list(csv.DictReader(open(args.truth, encoding="utf-8-sig")))

    field_ok = {f: 0 for f in FIELDS}
    n = len(truth_rows)
    passed = passed_correct = all_correct = 0
    out_rows = []
    master = _load_master()
    ths = [float(x) for x in args.thresholds.split(",") if x.strip()]
    sens = {t: {"auto": 0, "auto_ok": 0, "caught": 0, "false_block": 0} for t in ths}
    nomaster = {"auto": 0, "auto_ok": 0}

    for row in truth_rows:
        path = str(Path(args.docs) / row["file"])
        try:
            pred = extract(path)
            err = ""
        except Exception as e:  # 單筆失敗不中斷,直接進人工複核
            pred, err = {k: None for k in FIELDS}, f"處理失敗:{e}"

        issues = ([err] if err else []) + validate(pred)
        status = "review" if issues else "auto_pass"
        vc = vendor_check(pred.get("vendor"), master=master)
        # 不含廠商主資料比對時的狀態,用來算「多攔下幾份、誤攔幾份」
        base_status = "review" if (([err] if err else []) + validate(pred, use_master=False)) else "auto_pass"
        ok = {f: same(f, pred.get(f), row.get(f)) for f in FIELDS}
        doc_correct = all(ok.values())

        for f in FIELDS:
            field_ok[f] += ok[f]
        all_correct += doc_correct
        if status == "auto_pass":
            passed += 1
            passed_correct += doc_correct
        if base_status == "auto_pass":
            nomaster["auto"] += 1
            nomaster["auto_ok"] += doc_correct
        for t in ths:
            st_t = "review" if (([err] if err else []) + validate(pred, threshold=t)) else "auto_pass"
            if st_t == "auto_pass":
                sens[t]["auto"] += 1
                sens[t]["auto_ok"] += doc_correct
            if base_status == "auto_pass" and st_t == "review":
                sens[t]["caught" if not doc_correct else "false_block"] += 1

        out_rows.append({
            "file": row["file"], "route": pred.get("_route", args.extractor),
            **{f"pred_{f}": pred.get(f) for f in FIELDS},
            **{f"ok_{f}": ok[f] for f in FIELDS},
            "doc_correct": doc_correct, "status": status, "status_no_master": base_status,
            "vendor_match": vc["status"], "vendor_candidate": vc["candidate"], "vendor_score": vc["score"],
            "issues": "; ".join(issues), "ocr_text": (pred.get("_text") or "")[:500],
        })

    out_path = args.out or f"results_{args.extractor}.csv"
    with open(out_path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out_rows[0].keys()))
        w.writeheader()
        w.writerows(out_rows)

    print(f"\n=== {args.extractor}  共 {n} 份 ===")
    for f in FIELDS:
        print(f"欄位正確率 {f:8s}: {field_ok[f] / n:.1%}")
    print(f"整份全對率           : {all_correct / n:.1%}")
    print(f"自動通過率           : {passed / n:.1%}  (其餘 {n - passed} 份送人工複核)")
    if passed:
        print(f"自動通過者的正確率   : {passed_correct / passed:.1%}  <- 最重要,漏網的錯誤有 {passed - passed_correct} 份")
    if master:
        print(f"\n--- 廠商主資料比對(主資料 {len(master)} 家;主門檻 {SIM_THRESHOLD})---")
        if nomaster["auto"]:
            print(f"不含主資料比對:自動通過 {nomaster['auto']} 份,其中正確 {nomaster['auto_ok']} 份 "
                  f"({nomaster['auto_ok'] / nomaster['auto']:.1%})")
        print("門檻  自動通過  通過者正確率  多攔下的錯誤  誤攔的正確文件")
        for t in ths:
            s = sens[t]
            acc = f"{s['auto_ok'] / s['auto']:.1%}" if s["auto"] else "n/a"
            print(f"{t:.2f}  {s['auto']:>6}   {acc:>10}   {s['caught']:>10}   {s['false_block']:>12}")
    print(f"明細已寫入 {out_path}")


if __name__ == "__main__":
    main()
