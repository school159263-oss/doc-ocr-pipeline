"""訂單 OCR 成果儀表板。

執行：streamlit run dashboard.py
需先執行 py evaluate.py（以及 py evaluate.py --folder samples_test）產生評估結果。
"""
import json
import re
import tempfile
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from PIL import Image, ImageDraw

from evaluate import HEADER_FIELDS, LINE_FIELDS
from local_ocr import LocalExtractor, remove_red_stamp
from ocr_pipeline import load_master, process

ROOT = Path(__file__).parent
OUT = ROOT / "output"

# 色彩：依用途分配（系列色固定順序；狀態色只用於放行／人工確認）
BLUE, ORANGE = "#2a78d6", "#eb6834"
STAGE_RAMP = ["#86b6ef", "#3987e5", "#184f95"]  # 階段是有順序的 → 同一色相由淺到深
GOOD, WARNING, CRITICAL, NEUTRAL = "#0ca30c", "#fab219", "#d03b3b", "#c3c2b7"
INK, INK2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e1e0d9", "#fcfcfb"
FONT = 'system-ui, -apple-system, "Segoe UI", "Microsoft JhengHei", sans-serif'

DIFF_LABEL = {"clean": "乾淨", "stamp": "蓋章", "noisy": "雜訊", "hard": "低解析傳真"}
FIELD_LABEL = {"customer_name": "客戶名稱", "po_number": "採購單號", "order_date": "訂購日期",
               "delivery_date": "需求交期", "total_amount": "合計金額", "item_code": "料號",
               "quantity": "數量", "unit_price": "單價", "amount": "金額"}

st.set_page_config(page_title="訂單 OCR 準確度優化", page_icon="📄", layout="wide")


def style(fig, height=320):
    fig.update_layout(
        height=height, margin=dict(l=10, r=20, t=10, b=10), font=dict(family=FONT, color=INK2, size=13),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", bargap=0.35, bargroupgap=0.08,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, title=None),
        hoverlabel=dict(bgcolor="white", font=dict(family=FONT, color=INK)),
    )
    fig.update_xaxes(gridcolor=GRID, linecolor=NEUTRAL, zeroline=False)
    fig.update_yaxes(gridcolor=GRID, linecolor=NEUTRAL, zeroline=False)
    return fig


@st.cache_data
def load_report(name: str):
    p = OUT / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


@st.cache_data
def ocr_boxes(path: str, preprocess: bool):
    ex = LocalExtractor(preprocess=preprocess, deskew=False)
    return [(w.text, w.x, w.y, w.w, w.h) for w in ex.words(Path(path))]


def fix_type(note: str) -> str:
    m = re.search(r"（(.+?)[，）]", note)
    reason = m.group(1) if m else "其他"
    for key, label in [("易混淆", "易混淆字元校正"), ("模糊", "料號模糊比對"), ("客戶主檔", "客戶名稱比對"),
                       ("回推", "數量／單價回推"), ("重算", "金額重算"), ("加總", "合計以明細為準")]:
        if key in reason:
            return label
    return reason


# ---------------------------------------------------------------- 側邊欄
st.sidebar.title("📄 訂單 OCR")
st.sidebar.caption("零成本版：Windows 內建 OCR＋規則驗證")
datasets = {"開發樣本（20 張，用來設計規則）": "evaluation_local_samples.json",
            "測試樣本（40 張，規則從沒看過）": "evaluation_local_samples_test.json"}
choice = st.sidebar.radio("資料集", list(datasets))
report = load_report(datasets[choice])
folder = ROOT / ("samples" if "開發" in choice else "samples_test")
if report is None:
    st.error("找不到評估結果，請先執行 `py evaluate.py` 與 `py evaluate.py --folder samples_test`。")
    st.stop()
stages = report["stages"]
final = stages[-1]
n = report["samples"]

tab1, tab2, tab3 = st.tabs(["📊 成果總覽", "🔍 單張檢視", "⬆️ 上傳試試"])

# ---------------------------------------------------------------- 成果總覽
with tab1:
    st.subheader("每加一個步驟，準確率提升多少？")
    auto = final["auto_release"]
    k = st.columns(4)
    k[0].metric("欄位準確率", f"{final['field_accuracy']:.1%}",
                f"原始 OCR {stages[0]['field_accuracy']:.1%} → {(final['field_accuracy'] - stages[0]['field_accuracy']) * 100:+.1f} pt")
    k[1].metric("自動放行", f"{auto} / {n} 張", f"占 {auto / n:.0%}", delta_color="off")
    k[2].metric("自動放行中完全正確", f"{final['auto_release_correct']} / {auto} 張",
                "錯誤單據沒有被放行" if final["auto_release_correct"] == auto else "有錯誤單據被放行",
                delta_color="normal" if final["auto_release_correct"] == auto else "inverse")
    k[3].metric("每月 API 費用", "NT$ 0", "本機離線辨識", delta_color="off")

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**各階段準確率**")
        names = [s["name"] for s in stages]
        fig = go.Figure()
        for key, label, color in [("field_accuracy", "欄位準確率", BLUE), ("doc_accuracy", "整張完全正確率", ORANGE)]:
            vals = [s[key] * 100 for s in stages]
            fig.add_bar(y=names, x=vals, name=label, orientation="h", marker=dict(color=color, cornerradius=4),
                        text=[f"{v:.1f}%" for v in vals], textposition="outside", cliponaxis=False,
                        textfont=dict(color=INK2), hovertemplate="%{y}<br>" + label + "：%{x:.1f}%<extra></extra>")
        fig.update_yaxes(autorange="reversed")
        fig.update_xaxes(range=[0, 108], ticksuffix="%")
        st.plotly_chart(style(fig), use_container_width=True)
    with c2:
        st.markdown("**不同掃描品質的欄位準確率**")
        fig = go.Figure()
        for s, color in zip(stages, STAGE_RAMP):
            by = {}
            for d in s["docs"]:
                a = by.setdefault(d["difficulty"], [0, 0])
                a[0] += d["ok"]
                a[1] += d["total"]
            keys = [k for k in DIFF_LABEL if k in by]
            vals = [by[k][0] / by[k][1] * 100 for k in keys]
            fig.add_bar(x=[DIFF_LABEL[k] for k in keys], y=vals, name=s["name"], marker=dict(color=color, cornerradius=4),
                        hovertemplate="%{x}<br>" + s["name"] + "：%{y:.1f}%<extra></extra>")
        fig.update_yaxes(range=[0, 100], ticksuffix="%")
        st.plotly_chart(style(fig), use_container_width=True)

    c3, c4 = st.columns(2)
    with c3:
        st.markdown("**最終分流結果**")
        docs = final["docs"]
        groups = [
            ("✅ 自動放行・正確", sum(d["status"] == "自動放行" and not d["errors"] for d in docs), GOOD),
            ("⛔ 自動放行・有錯", sum(d["status"] == "自動放行" and bool(d["errors"]) for d in docs), CRITICAL),
            ("⚠️ 人工確認・確有錯誤", sum(d["status"] != "自動放行" and bool(d["errors"]) for d in docs), WARNING),
            ("ℹ️ 人工確認・其實正確", sum(d["status"] != "自動放行" and not d["errors"] for d in docs), NEUTRAL),
        ]
        fig = go.Figure()
        for label, v, color in groups:
            fig.add_bar(y=[label], x=[v], orientation="h", marker=dict(color=color, cornerradius=4), showlegend=False,
                        text=[f"{v} 張"], textposition="outside", cliponaxis=False, textfont=dict(color=INK2),
                        hovertemplate=f"{label}：{v} 張<extra></extra>")
        fig.update_yaxes(autorange="reversed")
        fig.update_xaxes(range=[0, n * 1.12], title="單據張數")
        st.plotly_chart(style(fig, 260), use_container_width=True)
        st.caption("「自動放行・有錯」是最危險的情況（錯誤資料直接進系統），目標是 0 張。")
    with c4:
        st.markdown("**自動修正了哪些錯誤**")
        counts = pd.Series([fix_type(f) for d in final["docs"] for f in d["fixes"]]).value_counts()
        fig = go.Figure(go.Bar(y=counts.index, x=counts.values, orientation="h", marker=dict(color=BLUE, cornerradius=4),
                               text=counts.values, textposition="outside", cliponaxis=False, textfont=dict(color=INK2),
                               hovertemplate="%{y}：%{x} 處<extra></extra>"))
        fig.update_yaxes(autorange="reversed")
        fig.update_xaxes(title="修正次數", range=[0, counts.max() * 1.15 if len(counts) else 1])
        st.plotly_chart(style(fig, 260), use_container_width=True)

    with st.expander("流程說明"):
        st.markdown("""
1. **原始 OCR**：Windows 內建繁體中文 OCR，依版面位置把文字分配到各欄位。
2. **影像前處理**：取紅色通道去除紅色印章；以文字座標估算傾斜並校正。
3. **主檔比對與交叉驗證**：
   - 料號、客戶比對主檔（處理 0/O、1/I、5/S、8/B 等易混淆字元）
   - 「數量 × 單價 = 金額」不成立時，推算是哪一欄讀錯，並用標準價與單據合計佐證
   - 只修正有唯一答案、且有其他欄位佐證的錯誤
4. **分流**：全部檢查通過 → 自動放行；仍有疑慮 → 人工確認清單。
""")
    with st.expander("資料表"):
        st.dataframe(pd.DataFrame([{"階段": s["name"], "欄位準確率": f"{s['field_accuracy']:.1%}",
                                    "整張完全正確率": f"{s['doc_accuracy']:.1%}", "處理秒數": s["seconds"]} for s in stages]),
                     hide_index=True, use_container_width=True)

# ---------------------------------------------------------------- 單張檢視
with tab2:
    files = [d["file"] for d in final["docs"]]
    labels = {d["file"]: f"{d['file']}（{DIFF_LABEL[d['difficulty']]}・{d['status']}）" for d in final["docs"]}
    f = st.selectbox("選擇單據", files, format_func=labels.get)
    doc = {s["name"]: next(d for d in s["docs"] if d["file"] == f) for s in stages}
    fd = doc[final["name"]]
    truth = next(t for t in json.loads((folder / "ground_truth.json").read_text(encoding="utf-8")) if t["file"] == f)

    left, right = st.columns([4, 7])
    with left:
        pre = st.toggle("顯示前處理後影像（去除紅色印章）", value=False)
        img = Image.open(folder / f).convert("RGB")
        if pre:
            img = remove_red_stamp(img)
        if st.toggle("標示 OCR 辨識到的文字框", value=True):
            draw = ImageDraw.Draw(img)
            for _, x, y, w, h in ocr_boxes(str(folder / f), pre):
                draw.rectangle([x, y, x + w, y + h], outline=BLUE, width=2)
        st.image(img, use_container_width=True)
    with right:
        if fd["status"] == "自動放行":
            st.success("✅ 自動放行：所有檢查皆通過")
        else:
            st.warning("⚠️ 待人工確認：仍有欄位無法確定")
        rows = []
        for fld in HEADER_FIELDS:
            rows.append((FIELD_LABEL[fld], fld, None))
        for i in range(len(truth["lines"])):
            for fld in LINE_FIELDS:
                rows.append((f"第{i + 1}項 {FIELD_LABEL[fld]}", fld, i))
        short = {s["name"]: lb for s, lb in zip(stages, ["① 原始", "② 前處理", "③ 最終"])}
        fmt = lambda v: f"{v:,.0f}" if isinstance(v, float) and v == int(v) and v >= 100 else (f"{v:g}" if isinstance(v, float) else str(v))
        table = []
        for label, fld, i in rows:
            exp = truth[fld] if i is None else truth["lines"][i][fld]
            r = {"欄位": label, "正確答案": fmt(exp)}
            for s in stages:
                o = doc[s["name"]]["order"]
                got = o.get(fld) if i is None else (o["lines"][i][fld] if i < len(o["lines"]) else "")
                ok = (abs(got - exp) < 0.01) if isinstance(got, (int, float)) and isinstance(exp, (int, float)) else str(got) == str(exp)
                r[short[s["name"]]] = ("✓ " if ok else "✗ ") + fmt(got)
            table.append(r)
        df = pd.DataFrame(table)
        st.dataframe(df.style.map(lambda v: "color:#006300" if str(v).startswith("✓") else ("color:#d03b3b;font-weight:600" if str(v).startswith("✗") else ""),
                                  subset=list(short.values())),
                     hide_index=True, use_container_width=True, height=min(600, 38 + 35 * len(df)))
        if fd["fixes"]:
            st.markdown("**自動修正紀錄**")
            for x in fd["fixes"]:
                st.markdown(f"- {x}")
        errs = [i for i in fd["issues"] if i["level"] == "error"]
        if errs:
            st.markdown("**送人工確認的原因**")
            for i in errs:
                st.markdown(f"- `{i['field']}` {i['message']}")

# ---------------------------------------------------------------- 上傳
with tab3:
    st.markdown("上傳一張採購單影像（PNG／JPG），用同一套流程即時辨識。版面需與範例採購單相同。")
    up = st.file_uploader("採購單影像", type=["png", "jpg", "jpeg"])
    if up:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "upload.png"
            Image.open(up).convert("RGB").save(p)
            r = process(p, LocalExtractor(), load_master(), "pipeline")
            a, b = st.columns([5, 6])
            a.image(Image.open(p), use_container_width=True)
        with b:
            (st.success if r["status"] == "自動放行" else st.warning)(r["status"])
            o = r["order"]
            st.dataframe(pd.DataFrame([{"欄位": FIELD_LABEL[k], "辨識結果": str(o[k])} for k in HEADER_FIELDS]),
                         hide_index=True, use_container_width=True)
            st.dataframe(pd.DataFrame(o["lines"]).rename(columns={**FIELD_LABEL, "description": "品名"}),
                         hide_index=True, use_container_width=True)
            for x in r["fixes"]:
                st.markdown(f"- 🔧 {x}")
            for i in r["issues"]:
                st.markdown(f"- ⚠️ `{i['field']}` {i['message']}")
