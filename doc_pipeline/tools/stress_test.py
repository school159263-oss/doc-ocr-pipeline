"""傾斜校正壓力測試：同一張虛構訂單，在不同傾斜角與雜訊下比較「有／無傾斜校正」的欄位正確數。

    cd doc_pipeline
    python tools/stress_test.py            # 結果印在終端機，並寫入 baselines/stress_test_deskew.txt

使用與 pdf_router 相同的前處理、傾斜量測與文字正規化；語言模型由 TESSDATA_PREFIX 決定。
固定亂數種子，可重現。暫存的影像 PDF 寫在系統暫存資料夾，結束後刪除。
"""
import os
import random
import sys
import tempfile
from pathlib import Path

import numpy as np
import pymupdf
import pytesseract

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pdf_router as R  # noqa: E402
from generate_docs import DEFAULT_FONT, register_font  # noqa: E402
from generate_osat_samples import draw_order_pdf, make_order, save_image_pdf, scan_from_pdf  # noqa: E402
from osat_order import ORDER_FIELDS, extract_order  # noqa: E402
from osat_validators import load_masters  # noqa: E402

ANGLES = (2, 5, 8, 10, 12, 14, 16, 20)
NOISES = (10, 25, 40)
NO_DESKEW_NOISE = 10  # 「不做傾斜校正」的對照只在這個雜訊等級跑


def fields_ok(pred, rec):
    n = 0
    for k in ORDER_FIELDS:
        if k == "unit_price":
            n += pred[k] is not None and abs(pred[k] - rec[k]) < 0.005
        else:
            n += str(pred[k]) == str(rec[k])
    return n


def ocr_once(pdf_path, rec, deskew=True):
    pg = pymupdf.open(pdf_path)[0]
    pix = pg.get_pixmap(dpi=R.RENDER_DPI, colorspace=pymupdf.csGRAY)
    gray = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width).copy()
    skew = R.measure_skew(R._binarize(gray)) if deskew else 0.0
    raw = pytesseract.image_to_string(R._binarize(R.deskew(gray, skew)), lang=R.TESS_LANG)
    return skew, fields_ok(extract_order(R.normalize_ocr_text(raw)), rec)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    font = register_font(DEFAULT_FONT)
    rec = make_order(random.Random(7), load_masters())
    pdf = draw_order_pdf(rec, font)
    lines = [f"# 傾斜校正壓力測試  tesseract {pytesseract.get_tesseract_version()}  "
             f"tessdata={os.environ.get('TESSDATA_PREFIX', '(預設)')}",
             f"# 搜尋範圍 ±{R.MAX_SKEW}°，欄位共 {len(ORDER_FIELDS)} 個",
             "實際角度  雜訊σ | 量測角度  欄位正確(有校正) | 欄位正確(不校正)"]
    print("\n".join(lines))
    with tempfile.TemporaryDirectory() as tmp:
        for noise in NOISES:
            for a in ANGLES:
                p = Path(tmp) / f"s_{a}_{noise}.pdf"
                save_image_pdf(scan_from_pdf(pdf, a, noise, np.random.default_rng(a)), p)
                skew, ok = ocr_once(p, rec)
                ok0 = ocr_once(p, rec, deskew=False)[1] if noise == NO_DESKEW_NOISE else "-"
                line = f"{a:>7}°  {noise:>5} | {skew:+7.2f}°  {ok:>8}/10        | {ok0}{'/10' if ok0 != '-' else ''}"
                print(line)
                lines.append(line)
    out = ROOT / "baselines" / "stress_test_deskew.txt"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"結果已寫入 {out}")


if __name__ == "__main__":
    main()
