"""文件自動判讀 — 視覺化檢視（先看文件，再看數據）。

執行（在專案資料夾）：
    .venv\\Scripts\\streamlit run dashboard.py

只讀取既有的 docs*/、ground_truth*.csv、results_rules_*.csv，不會修改任何結果檔。
標示欄位位置時會另外跑一次 Tesseract 取得文字座標，結果快取在 .dashboard_cache/。
"""
import json
import re
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
CACHE = HERE / ".dashboard_cache"
TESS_EXE = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
FONT_PATH = r"C:\Windows\Fonts\msjh.ttc"

BATCHES = {
    "原始測試集（20 份，用來調整規則）": ("docs", "ground_truth.csv", "results_rules_vendor.csv"),
    "保留測試集（20 份，規則沒看過）": ("docs_holdout", "ground_truth_holdout.csv", "results_rules_holdout_vendor.csv"),
}
# 簡報中的各階段：(名稱, 結果檔, 標準答案)
STAGES = [
    ("基準線", "results_rules_baseline.csv", "ground_truth.csv"),
    ("規則調整＋交叉檢查", "results_rules_after.csv", "ground_truth.csv"),
    ("保留測試集", "results_rules_holdout.csv", "ground_truth_holdout.csv"),
    ("＋主資料比對（原始）", "results_rules_vendor.csv", "ground_truth.csv"),
    ("＋主資料比對（保留）", "results_rules_holdout_vendor.csv", "ground_truth_holdout.csv"),
]

FIELDS = ["doc_no", "date", "vendor", "total"]
FIELD_LABEL = {"doc_no": "單號", "date": "日期", "vendor": "廠商", "total": "總額"}
# 欄位顏色（系列色固定順序）
FIELD_COLOR = {"doc_no": "#2a78d6", "date": "#eb6834", "vendor": "#1baf7a", "total": "#eda100"}
TYPE_LABEL = {"invoice": "發票", "receipt": "進料單", "shipment": "出貨單"}
VARIANT_LABEL = {"native": "原生 PDF", "scan_png": "掃描圖檔", "scan_pdf": "掃描 PDF", "skew": "歪斜", "blur": "模糊"}
GOOD, WARNING, CRITICAL, NEUTRAL = "#0ca30c", "#fab219", "#d03b3b", "#c3c2b7"
INK2, GRID = "#52514e", "#e1e0d9"
PLOT_FONT = 'system-ui, -apple-system, "Segoe UI", "Microsoft JhengHei", sans-serif'

st.set_page_config(page_title="文件自動判讀", page_icon="📄", layout="wide")


# ---------------------------------------------------------------- 資料
@st.cache_data
def load_batch(truth_csv: str, results_csv: str) -> pd.DataFrame:
    truth = pd.read_csv(HERE / truth_csv, encoding="utf-8-sig", dtype=str)
    res = pd.read_csv(HERE / results_csv, encoding="utf-8-sig", dtype=str, keep_default_na=False)
    df = res.merge(truth, on="file", how="left")
    df["doc_correct"] = df["doc_correct"] == "True"
    for f in FIELDS:
        df[f"ok_{f}"] = df[f"ok_{f}"] == "True"
    df["category"] = [
        ("漏網" if not ok else "自動通過") if s == "auto_pass" else ("送人工・確有錯誤" if not ok else "送人工・其實正確")
        for s, ok in zip(df["status"], df["doc_correct"])
    ]
    return df


def status_badge(cat: str) -> str:
    return {"自動通過": ":green-badge[✅ 自動通過]", "漏網": ":red-badge[⛔ 自動通過但有錯]",
            "送人工・確有錯誤": ":orange-badge[⚠️ 送人工複核]", "送人工・其實正確": ":orange-badge[⚠️ 送人工複核]"}[cat]


def fmt_value(f: str, v) -> str:
    if v in (None, "") or (isinstance(v, float) and pd.isna(v)):
        return "（未讀到）"
    if f == "total":
        try:
            return f"{float(v):,.2f}"
        except ValueError:
            return str(v)
    return str(v)


# ---------------------------------------------------------------- 影像
@st.cache_data
def page_image(path: str, scale: float = 2.0) -> Image.Image:
    p = Path(path)
    if p.suffix.lower() == ".pdf":
        import pypdfium2 as pdfium
        return pdfium.PdfDocument(str(p))[0].render(scale=scale).to_pil().convert("RGB")
    return Image.open(p).convert("RGB")


@st.cache_data
def thumbnail(path: str) -> Image.Image:
    """裁掉頁面下方的空白，只留有內容的區域，縮圖才看得清楚。"""
    img = page_image(path)
    box = content_box(img)
    img = (img.crop(box) if box else img).copy()
    img.thumbnail((480, 360))
    canvas = Image.new("RGB", (480, 360), "white")  # 固定比例，卡片才會對齊
    canvas.paste(img, ((480 - img.width) // 2, 0))
    return canvas


def ocr_lines(path: str) -> list[dict]:
    """Tesseract 逐行文字與每個字詞的座標（以 page_image 的像素為準），快取到 .dashboard_cache/。"""
    p = Path(path)
    cache = CACHE / f"{p.parent.name}__{p.name}.v2.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    import pytesseract
    if TESS_EXE.exists():
        pytesseract.pytesseract.tesseract_cmd = str(TESS_EXE)
    d = pytesseract.image_to_data(page_image(path), lang="chi_tra+eng", output_type=pytesseract.Output.DICT)
    lines = {}
    for i, w in enumerate(d["text"]):
        if w.strip():
            k = (d["block_num"][i], d["par_num"][i], d["line_num"][i])
            lines.setdefault(k, []).append({"text": w, "box": [d["left"][i], d["top"][i],
                                                               d["left"][i] + d["width"][i], d["top"][i] + d["height"][i]]})
    out = [{"text": "".join(w["text"] for w in ws), "words": ws} for ws in lines.values()]
    CACHE.mkdir(exist_ok=True)
    cache.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out


def _norm(s: str) -> str:
    return re.sub(r"[\s,，:：$]|NT", "", str(s)).lower()


def _union(words) -> list:
    return [min(w["box"][0] for w in words), min(w["box"][1] for w in words),
            max(w["box"][2] for w in words), max(w["box"][3] for w in words)]


def _span(line: dict, match) -> list | None:
    """在一行裡找出「最短、且串起來符合條件」的連續字詞，回傳它們的外框。"""
    ws = line["words"]
    best = None
    for i in range(len(ws)):
        for j in range(i, len(ws)):
            if match("".join(w["text"] for w in ws[i:j + 1])):
                if best is None or j - i < best[1] - best[0]:
                    best = (i, j)
                break
    return _union(ws[best[0]:best[1] + 1]) if best else None


def _date_match(y: int, m: int, d: int):
    def match(s: str) -> bool:
        nums = [int(n) for n in re.findall(r"\d+", s)]
        return any(nums[i] in (y, y - 1911) and nums[i + 1] == m and nums[i + 2] == d for i in range(len(nums) - 2))
    return match


def locate(field: str, value, lines: list[dict]):
    """找出判讀值是從哪裡讀到的（用判讀結果反查，所以讀錯時也看得到是哪裡讀錯）。"""
    if value in (None, ""):
        return None
    if field == "date":
        match = _date_match(*(int(x) for x in str(value).split("-")))
    elif field == "total":
        v = float(value)
        keys = {f"{v:.2f}", f"{v:.0f}"} if v == int(v) else {f"{v:.2f}"}
        match = lambda s: any(k in _norm(s) for k in keys)
    else:
        nv = _norm(value)
        match = lambda s: nv in _norm(s)
    hits = [ln for ln in lines if match(ln["text"])]
    if field == "total":  # 同一個數字可能同時出現在明細與總計，優先取總計那一行
        hits = [ln for ln in hits if re.search(r"總計|總金額|合計|total", ln["text"], re.I)] or hits[-1:]
    if hits:
        return _span(hits[-1] if field == "total" else hits[0], match)
    if field == "vendor":  # 廠商名稱讀錯時，框出「公司名稱／供應商」標籤後面的文字
        for ln in lines:
            ws = ln["words"]
            for i in range(len(ws)):
                if re.search(r"(公司名稱|供應商|廠商|Vendor)[:：]?$", "".join(w["text"] for w in ws[:i + 1]), re.I):
                    rest = [w for w in ws[i + 1:] if not re.fullmatch(r"[:：]", w["text"])]
                    stop = next((k for k, w in enumerate(rest) if re.match(r"日期|Date", w["text"], re.I)), len(rest))
                    if rest[:stop]:
                        return _union(rest[:stop])
    return None


def content_box(img: Image.Image, margin: int = 30):
    from PIL import ImageOps
    box = ImageOps.invert(img.convert("L")).point(lambda v: 255 if v > 60 else 0).getbbox()
    if not box:
        return None
    return (max(0, box[0] - margin), max(0, box[1] - margin), min(img.width, box[2] + margin), min(img.height, box[3] + margin))


def annotate(path: str, row) -> Image.Image:
    img = page_image(path).copy()
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT_PATH, max(16, img.width // 60))
    lines = ocr_lines(path)
    pad = 5
    for f in FIELDS:
        box = locate(f, row[f"pred_{f}"], lines)
        if not box:
            continue
        x0, y0, x1, y1 = box[0] - pad, box[1] - pad, box[2] + pad, box[3] + pad
        draw.rectangle([x0, y0, x1, y1], outline=FIELD_COLOR[f], width=3)
        tag = FIELD_LABEL[f]
        tw = draw.textlength(tag, font=font)
        draw.rectangle([x1 + 3, y0, x1 + tw + 15, y0 + font.size + 8], fill=FIELD_COLOR[f])
        draw.text((x1 + 9, y0 + 2), tag, font=font, fill="white")
    crop = content_box(page_image(path), margin=60)
    return img.crop(crop) if crop else img


def chip(f: str) -> str:
    return f'<span style="display:inline-block;width:10px;height:10px;border-radius:2px;background:{FIELD_COLOR[f]};margin-right:6px"></span>'


def style(fig, height=300):
    fig.update_layout(height=height, margin=dict(l=10, r=30, t=10, b=10), font=dict(family=PLOT_FONT, color=INK2, size=13),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", bargap=0.35,
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, title=None),
                      hoverlabel=dict(bgcolor="white", font=dict(family=PLOT_FONT)))
    fig.update_xaxes(gridcolor=GRID, zeroline=False)
    fig.update_yaxes(gridcolor=GRID, zeroline=False)
    return fig


# ---------------------------------------------------------------- 導覽
PAGES = ["📂 掃描文件", "🔍 單份檢視", "📊 統計數據"]
# 網址參數可直接開到指定頁面與文件，例如 ?page=detail&doc=d03_blur.png
if "qp_done" not in st.session_state:
    st.session_state["qp_done"] = True
    qp = {"docs": PAGES[0], "detail": PAGES[1], "stats": PAGES[2]}.get(st.query_params.get("page", ""))
    if qp:
        st.session_state["page"] = qp
    if st.query_params.get("doc"):
        st.session_state["doc"] = st.query_params["doc"]
st.sidebar.title("📄 文件自動判讀")
st.sidebar.caption("全本機執行・測試文件皆為虛構資料")
batch_name = st.sidebar.radio("批次", list(BATCHES))
folder, truth_csv, results_csv = BATCHES[batch_name]
df = load_batch(truth_csv, results_csv)
page = st.sidebar.radio("頁面", PAGES, key="page")
st.sidebar.divider()
st.sidebar.markdown("**欄位顏色**<br>" + "<br>".join(chip(f) + FIELD_LABEL[f] for f in FIELDS), unsafe_allow_html=True)

if st.session_state.get("doc") not in set(df["file"]):
    st.session_state["doc"] = df["file"].iloc[0]


def open_doc(file: str):
    st.session_state["doc"] = file
    st.session_state["page"] = PAGES[1]


# ---------------------------------------------------------------- 1. 掃描文件
if page == PAGES[0]:
    n = len(df)
    n_auto = int((df["status"] == "auto_pass").sum())
    st.subheader(f"這一批掃描了 {n} 份文件")
    st.caption(f"自動通過 {n_auto} 份・送人工複核 {n - n_auto} 份・"
               + "、".join(f"{TYPE_LABEL[k]} {v} 份" for k, v in df["doc_type"].value_counts().items()))

    c = st.columns(3)
    f_status = c[0].selectbox("判讀結果", ["全部", "自動通過", "送人工複核", "自動通過但有錯"])
    f_type = c[1].selectbox("文件類型", ["全部"] + [TYPE_LABEL[t] for t in sorted(df["doc_type"].unique())])
    f_var = c[2].selectbox("掃描品質", ["全部"] + [VARIANT_LABEL[v] for v in VARIANT_LABEL if v in set(df["variant"])])
    view = df
    if f_status == "自動通過":
        view = view[view["category"] == "自動通過"]
    elif f_status == "送人工複核":
        view = view[view["status"] == "review"]
    elif f_status == "自動通過但有錯":
        view = view[view["category"] == "漏網"]
    if f_type != "全部":
        view = view[view["doc_type"].map(TYPE_LABEL) == f_type]
    if f_var != "全部":
        view = view[view["variant"].map(VARIANT_LABEL) == f_var]
    if view.empty:
        st.info("沒有符合條件的文件。")

    cols = st.columns(4)
    for i, (_, r) in enumerate(view.iterrows()):
        with cols[i % 4].container(border=True):
            st.image(thumbnail(str(HERE / folder / r["file"])), use_container_width=True)
            st.markdown(f"**{r['file']}**  \n"
                        f":gray-badge[{TYPE_LABEL[r['doc_type']]}] :gray-badge[{VARIANT_LABEL[r['variant']]}]  \n"
                        + status_badge(r["category"]))
            st.markdown("  \n".join(
                f"{'✓' if r[f'ok_{f}'] else '✗'} {FIELD_LABEL[f]}：{fmt_value(f, r[f'pred_{f}'])}" for f in FIELDS))
            st.button("查看判讀細節", key=f"open_{r['file']}", on_click=open_doc, args=(r["file"],),
                      use_container_width=True)

# ---------------------------------------------------------------- 2. 單份檢視
elif page == PAGES[1]:
    files = list(df["file"])
    idx = files.index(st.session_state["doc"])
    nav = st.columns([1, 6, 1])
    if nav[0].button("← 上一份", disabled=idx == 0, use_container_width=True):
        st.session_state["doc"] = files[idx - 1]
        st.rerun()
    if nav[2].button("下一份 →", disabled=idx == len(files) - 1, use_container_width=True):
        st.session_state["doc"] = files[idx + 1]
        st.rerun()
    nav[1].selectbox("文件", files, index=idx, key=f"doc_select_{st.session_state['doc']}", label_visibility="collapsed",
                     format_func=lambda f: f"{f}（{TYPE_LABEL[df.set_index('file').loc[f, 'doc_type']]}・"
                                           f"{VARIANT_LABEL[df.set_index('file').loc[f, 'variant']]}）")
    picked = st.session_state.get(f"doc_select_{st.session_state['doc']}")
    if picked and picked != st.session_state["doc"]:
        st.session_state["doc"] = picked
        st.rerun()
    r = df.set_index("file").loc[st.session_state["doc"]]
    path = str(HERE / folder / st.session_state["doc"])

    left, right = st.columns([5, 6])
    with left:
        if st.toggle("在圖上標示各欄位的讀取位置", value=True):
            with st.spinner("辨識文字位置中（第一次約 2 秒，之後會快取）…"):
                st.image(annotate(path, r), use_container_width=True)
            st.caption("框線是依「判讀結果」反查位置，所以讀錯時也能看到是哪一行被讀錯。")
        else:
            img = page_image(path)
            box = content_box(img, margin=60)
            st.image(img.crop(box) if box else img, use_container_width=True)
    with right:
        cat = r["category"]
        if cat == "自動通過":
            st.success("✅ 自動通過：所有檢查皆通過，判讀結果正確")
        elif cat == "漏網":
            st.error("⛔ 自動通過但有錯：查檢沒有攔下來，這是要優先改善的案例")
        elif cat == "送人工・確有錯誤":
            st.warning("⚠️ 送人工複核：判讀有誤，查檢成功攔下")
        else:
            st.warning("⚠️ 送人工複核：判讀其實正確，但查檢無法確定（多花一點人工，沒有損害）")

        rows = "".join(
            f"<tr><td style='white-space:nowrap'>{chip(f)}{FIELD_LABEL[f]}</td><td>{fmt_value(f, r[f'pred_{f}'])}</td>"
            f"<td>{fmt_value(f, r[f])}</td><td style='white-space:nowrap;color:{'#006300' if r[f'ok_{f}'] else CRITICAL};font-weight:600'>"
            f"{'✓ 正確' if r[f'ok_{f}'] else '✗ 錯誤'}</td></tr>" for f in FIELDS)
        st.markdown(f"""<table style="width:100%;border-collapse:collapse;font-size:15px">
<colgroup><col style="width:16%"><col style="width:35%"><col style="width:35%"><col style="width:14%"></colgroup>
<thead><tr style="border-bottom:2px solid #c3c2b7;text-align:left"><th>欄位</th><th>系統判讀</th><th>正確答案</th><th></th></tr></thead>
<tbody>{rows}</tbody></table>""", unsafe_allow_html=True)

        st.markdown("####")
        issues = [x for x in r["issues"].split("; ") if x]
        st.markdown("**查檢結果**")
        if issues:
            for x in issues:
                st.markdown(f"- ⚠️ {x}")
        else:
            st.markdown("- ✅ 欄位完整、日期合理、金額檢查通過、廠商在主資料中")
        if r["vendor_match"] and r["vendor_match"] != "match":
            st.markdown(f"- 廠商主資料最接近：{r['vendor_candidate']}（相似度 {r['vendor_score']}）")
        with st.expander("OCR 讀到的原始文字"):
            st.text(r["ocr_text"])

# ---------------------------------------------------------------- 3. 統計數據
else:
    n = len(df)
    auto = df[df["status"] == "auto_pass"]
    leaked = int((df["category"] == "漏網").sum())
    st.subheader("統計數據")
    k = st.columns(4)
    kpis = [("自動通過", f"{len(auto)}/{n}", f"占 {len(auto) / n:.0%}"),
            ("自動通過者正確（主指標）", f"{int(auto['doc_correct'].sum())}/{len(auto)}",
             f"{auto['doc_correct'].mean():.1%}" if len(auto) else "—"),
            ("錯誤漏網", f"{leaked} 份", "目標 0 份"),
            ("送人工複核", f"{n - len(auto)} 份", "多花人工，但錯誤不會進系統")]
    for col, (label, value, note) in zip(k, kpis):
        col.metric(label, value)
        col.caption(note)

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**各階段：自動通過者的正確率**")
        names, vals, labels = [], [], []
        for name, res, tr in STAGES:
            d = load_batch(tr, res)
            a = d[d["status"] == "auto_pass"]
            names.append(name)
            vals.append(a["doc_correct"].mean() * 100)
            labels.append(f"{int(a['doc_correct'].sum())}/{len(a)}（{a['doc_correct'].mean():.1%}）")
        fig = go.Figure(go.Bar(y=names, x=vals, orientation="h", marker=dict(color="#2a78d6", cornerradius=4),
                               text=labels, textposition="outside", cliponaxis=False,
                               hovertemplate="%{y}<br>%{text}<extra></extra>"))
        fig.update_yaxes(autorange="reversed")
        fig.update_xaxes(range=[0, 155], ticksuffix="%", tickvals=[0, 25, 50, 75, 100])
        st.plotly_chart(style(fig), use_container_width=True)
        st.caption("樣本小，每個比例都附上份數；保留測試集的規則沒有再調整過。")
    with c2:
        st.markdown("**本批各欄位的判讀正確率**")
        accs = [df[f"ok_{f}"].mean() * 100 for f in FIELDS]
        cnts = [f"{int(df[f'ok_{f}'].sum())}/{n}" for f in FIELDS]
        fig = go.Figure(go.Bar(y=[FIELD_LABEL[f] for f in FIELDS], x=accs, orientation="h",
                               marker=dict(color="#2a78d6", cornerradius=4), text=cnts, textposition="outside",
                               cliponaxis=False, hovertemplate="%{y}：%{x:.0f}%（%{text}）<extra></extra>"))
        fig.update_yaxes(autorange="reversed")
        fig.update_xaxes(range=[0, 115], ticksuffix="%", tickvals=[0, 25, 50, 75, 100])
        st.plotly_chart(style(fig), use_container_width=True)

    st.markdown("**不同掃描品質的判讀結果**")
    order = [v for v in VARIANT_LABEL if v in set(df["variant"])]
    cats = [("自動通過", "✅ 自動通過", GOOD), ("送人工・確有錯誤", "⚠️ 送人工・確有錯誤", WARNING),
            ("送人工・其實正確", "ℹ️ 送人工・其實正確", NEUTRAL), ("漏網", "⛔ 自動通過但有錯", CRITICAL)]
    fig = go.Figure()
    for key, label, color in cats:
        vals = [int(((df["variant"] == v) & (df["category"] == key)).sum()) for v in order]
        fig.add_bar(y=[VARIANT_LABEL[v] for v in order], x=vals, name=label, orientation="h",
                    marker=dict(color=color, line=dict(color="white", width=2)),
                    hovertemplate="%{y}・" + label + "：%{x} 份<extra></extra>")
    fig.update_layout(barmode="stack", legend_traceorder="normal")
    fig.update_yaxes(autorange="reversed")
    fig.update_xaxes(title="份數", dtick=1)
    st.plotly_chart(style(fig, 280), use_container_width=True)

    with st.expander("資料表"):
        st.dataframe(df[["file", "doc_type", "variant", "status", "doc_correct", "issues"]]
                     .rename(columns={"file": "檔案", "doc_type": "類型", "variant": "品質", "status": "狀態",
                                      "doc_correct": "全對", "issues": "查檢問題"}),
                     hide_index=True, use_container_width=True)
