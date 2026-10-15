"""共用查檢層。回傳問題清單,空清單代表可自動通過,否則送人工複核。"""
import csv
import os
import re
import unicodedata
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path

REQUIRED = ["doc_no", "date", "vendor", "total"]

# ---------- 廠商主資料與模糊比對 ----------
# vendor_master.csv(一欄 vendor)存在才啟用;不存在就維持原本「不檢查廠商」的行為。
# 相似度門檻事先固定為 0.85,不看個別文件調整;敏感度分析用環境變數 VENDOR_SIM_THRESHOLD 或 evaluate.py --thresholds。
VENDOR_MASTER_PATH = os.environ.get("VENDOR_MASTER", str(Path(__file__).resolve().parent / "vendor_master.csv"))
SIM_THRESHOLD = float(os.environ.get("VENDOR_SIM_THRESHOLD", "0.85"))

KNOWN_VENDORS = set()  # 保留給程式碼直接塞主資料用;與 vendor_master.csv 合併


def _load_master():
    names = set(KNOWN_VENDORS)
    p = Path(VENDOR_MASTER_PATH)
    if p.exists():
        names |= {r["vendor"].strip() for r in csv.DictReader(open(p, encoding="utf-8-sig")) if r.get("vendor", "").strip()}
    return sorted(names)


def normalize_vendor(s: str) -> str:
    """只做無害的正規化:全半形統一、去空白、統一「(股)」「(有)」寫法。不做字形歸一,以免把 OCR 錯字藏起來。"""
    s = unicodedata.normalize("NFKC", s or "")
    s = re.sub(r"\s+", "", s)
    s = s.replace("(股)", "股份有限公司").replace("(有)", "有限公司")
    return s.lower()


def vendor_check(vendor, threshold=None, master=None) -> dict:
    """回傳 {status, candidate, score}。
    status: match(完全相符) / suspect(高度相似但不完全相符,附疑似對象) / new(完全不像,視為新廠商) / ""(未檢查)。
    不會自動改寫廠商名稱,只提供線索給人工複核。"""
    th = SIM_THRESHOLD if threshold is None else threshold
    master = _load_master() if master is None else master
    if not master or not vendor:
        return {"status": "", "candidate": "", "score": ""}
    nv = normalize_vendor(vendor)
    best, best_s = "", -1.0
    for m in master:
        nm = normalize_vendor(m)
        if nv == nm:
            return {"status": "match", "candidate": m, "score": 1.0}
        sc = SequenceMatcher(None, nv, nm).ratio()
        if sc > best_s:
            best, best_s = m, sc
    status = "suspect" if best_s >= th else "new"
    return {"status": status, "candidate": best, "score": round(best_s, 3)}


def validate(rec: dict, use_master: bool = True, threshold=None) -> list:
    issues = []

    for k in REQUIRED:
        if rec.get(k) in (None, ""):
            issues.append(f"缺少欄位:{k}")

    d = rec.get("date")
    if d:
        try:
            y, m, dd = (int(x) for x in d.split("-"))
            dt = date(y, m, dd)
            if dt > date.today():
                issues.append("日期晚於今天")
            if dt.year < 2000:
                issues.append("日期過早,疑似 OCR 或民國年轉換錯誤")
        except Exception:
            issues.append("日期格式不正確")

    t = rec.get("total")
    if t is not None:
        if not isinstance(t, (int, float)):
            issues.append("金額不是數字")
        elif t <= 0:
            issues.append("金額必須大於 0")

    # 交叉檢查:有小計和稅額時,總額必須等於兩者相加(容許 1 元尾差)
    st, tx = rec.get("subtotal"), rec.get("tax")
    if None not in (st, tx, t) and isinstance(t, (int, float)) and abs(t - (st + tx)) > 1:
        issues.append("總額與小計加稅額不符")

    if use_master:
        vc = vendor_check(rec.get("vendor"), threshold)
        if vc["status"] == "suspect":
            issues.append(f"廠商疑似為「{vc['candidate']}」(相似度 {vc['score']}),但不完全相符,請人工確認")
        elif vc["status"] == "new":
            issues.append("廠商不在主資料中(新廠商?)")

    return issues
