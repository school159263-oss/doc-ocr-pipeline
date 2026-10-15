"""逐步評估每個流程步驟對準確率的貢獻，結果供 dashboard.py 視覺化。

用法：
  py evaluate.py                  # 零成本：Windows 內建 OCR（預設）
  py evaluate.py --engine claude  # 使用 Claude API（需金鑰，會產生費用）
  py evaluate.py --engine mock    # 模擬模式，只測試程式能否運作
"""
import argparse
import json
import time
from pathlib import Path

from ocr_pipeline import ROOT, MockExtractor, load_master, process

HEADER_FIELDS = ["customer_name", "po_number", "order_date", "delivery_date", "total_amount"]
LINE_FIELDS = ["item_code", "quantity", "unit_price", "amount"]


def same(a, b) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) < 0.01
    return str(a).strip() == str(b).strip()


def score(order: dict, truth: dict) -> tuple[int, int, list[str]]:
    """回傳（正確欄位數, 總欄位數, 錯誤清單）。品項依順序比對，缺漏或多出的品項全部欄位算錯。"""
    ok, total, wrong = 0, 0, []
    for f in HEADER_FIELDS:
        total += 1
        if same(order.get(f), truth[f]):
            ok += 1
        else:
            wrong.append(f"{f}: {order.get(f)} ≠ {truth[f]}")
    for i in range(max(len(order["lines"]), len(truth["lines"]))):
        got = order["lines"][i] if i < len(order["lines"]) else {}
        exp = truth["lines"][i] if i < len(truth["lines"]) else {}
        for f in LINE_FIELDS:
            total += 1
            if got and exp and same(got.get(f), exp.get(f)):
                ok += 1
            else:
                wrong.append(f"lines[{i}].{f}: {got.get(f)} ≠ {exp.get(f)}")
    return ok, total, wrong


def stages_for(engine: str, folder: Path):
    """回傳 [(階段名稱, 擷取器, 模式)]，每個階段比前一個多加一個步驟。"""
    if engine == "local":
        from local_ocr import LocalExtractor
        return [
            ("① 原始 OCR", LocalExtractor(preprocess=False, deskew=False), "baseline"),
            ("② ＋影像前處理", LocalExtractor(preprocess=True, deskew=True), "baseline"),
            ("③ ＋主檔比對與交叉驗證", LocalExtractor(preprocess=True, deskew=True), "pipeline"),
        ]
    if engine == "claude":
        from ocr_pipeline import ClaudeExtractor
        return [("① AI 單次擷取", ClaudeExtractor(), "baseline"),
                ("② ＋主檔、驗證與重新判讀", ClaudeExtractor(), "pipeline")]
    gt = folder / "ground_truth.json"
    return [("① 單次擷取（模擬）", MockExtractor(gt), "baseline"),
            ("② 完整流程（模擬）", MockExtractor(gt), "pipeline")]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--folder", type=Path, default=ROOT / "samples")
    ap.add_argument("--engine", default="local", choices=["local", "claude", "mock"])
    args = ap.parse_args()

    truth = json.loads((args.folder / "ground_truth.json").read_text(encoding="utf-8"))
    master = load_master()
    report = {"engine": args.engine, "folder": args.folder.name, "samples": len(truth), "stages": []}

    for name, extractor, mode in stages_for(args.engine, args.folder):
        t0 = time.time()
        docs = []
        for t in truth:
            r = process(args.folder / t["file"], extractor, master, mode)
            ok, total, wrong = score(r["order"], t)
            docs.append({"file": t["file"], "difficulty": t["difficulty"], "ok": ok, "total": total,
                         "errors": wrong, "status": r["status"], "fixes": r["fixes"],
                         "issues": r["issues"], "order": r["order"]})
        ok = sum(d["ok"] for d in docs)
        total = sum(d["total"] for d in docs)
        auto = [d for d in docs if d["status"] == "自動放行"]
        stage = {
            "name": name, "mode": mode, "field_accuracy": ok / total,
            "doc_accuracy": sum(not d["errors"] for d in docs) / len(docs),
            "auto_release": len(auto), "auto_release_correct": sum(not d["errors"] for d in auto),
            "api_calls": extractor.calls, "seconds": round(time.time() - t0, 1), "docs": docs,
        }
        report["stages"].append(stage)
        print(f"{name:<22} 欄位準確率 {stage['field_accuracy']:6.1%}　整張全對 {stage['doc_accuracy']:6.1%}"
              + (f"　自動放行 {len(auto)} 張（全對 {stage['auto_release_correct']} 張）" if mode == "pipeline" else ""))

    out = ROOT / "output"
    out.mkdir(exist_ok=True)
    (out / f"evaluation_{args.engine}_{args.folder.name}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n結果 → output/evaluation_{args.engine}_{args.folder.name}.json（執行 streamlit run dashboard.py 檢視）")


if __name__ == "__main__":
    main()
