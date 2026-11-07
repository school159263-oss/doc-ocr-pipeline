# 文件自動判讀 demo(全本機)

流程:文件 → 抽取(rules / 本機 LLM / 分流) → 共用查檢 → 通過或送人工複核 → 結果檔可回查

## 開始
1. pip install -r requirements.txt(OCR 擇一即可:PaddleOCR 或 Tesseract+繁中語言包)
2. 把測試文件放進 docs/,在 ground_truth.csv 填人工標準答案(目前的 .txt 範例請刪掉)
3. python evaluate.py --extractor rules
4. 要試本機大模型:先裝 Ollama 並下載模型,改 extractors.py 的 OLLAMA_MODEL,再跑 --extractor llm 或 routed

## 看哪個數字
「自動通過者的正確率」最重要:它代表沒被攔下來、直接進系統的資料有多可靠。
results_*.csv 裡有每筆的判讀、問題原因與 OCR 文字,拿來分析錯誤類型再調規則。

## 換成實際表單
改 extractors.py 的 FIELDS 與 extract_by_rules 的規則,以及 validators.py 的檢查項目,其餘不用動。

## 視覺化檢視（先看文件，再看數據）
.venv\Scripts\pip install -r requirements-dashboard.txt
.venv\Scripts\streamlit run dashboard.py

- 掃描文件:每份文件一張卡片(縮圖、文件類型、掃描品質、自動通過/送人工、四個欄位的判讀結果),可依結果、類型、品質篩選
- 單份檢視:原圖上用顏色框出每個欄位是從哪裡讀到的,旁邊對照系統判讀與正確答案,並列出查檢問題與 OCR 原文
- 統計數據:各階段自動通過者正確率、各欄位正確率、不同掃描品質的結果
只讀取既有的 results_rules_*.csv,不改動任何結果檔;標示欄位位置用的 Tesseract 座標快取在 .dashboard_cache/。

---

# V2：封測客戶訂單 + PDF 分流

在 V1（供應商單據）之外，新增一種**獨立的文件類型「封測客戶訂單」**。V1 的程式、測試檔與評估結果都沒有改變（見下方對照）。
客戶、料號、批號、價格全部是虛構資料（ACME Semi、OSAT-CHIP-99xx、LOT-2026-xxx）。

## 流程

```
PDF ─┬─ 文字層 ≥ 50 字/頁 → 電子 PDF：PyMuPDF 直接讀文字（不經 OCR）
     └─ 否則 → 掃描檔：轉圖 300 dpi → OpenCV 中值濾波 + Otsu 二值化 → 量測傾斜角並校正
                      → Tesseract（chi_tra+eng）→ 文字正規化
   → 規則抽取 10 個欄位 → 與虛構主檔比對 → 通過／需人工確認／明顯錯誤（附原因）
```

日誌會印出每份文件走哪條路、文字層字數，以及**實際量測到的傾斜角**（例如 `量測傾斜角 +3.45°`）。

### 只使用 Tesseract（企業資安考量）
`pdf_router.py` 只呼叫 Tesseract，不依賴 PaddleOCR。這是考量企業資安規範的設計：
- Tesseract 是單一離線安裝的執行檔加語言模型檔，版本和雜湊值都能固定，容易送資安審查與白名單管理
- PaddleOCR 需要安裝 PaddlePaddle 深度學習框架與大量相依套件，預設還會在第一次執行時連網下載模型，在限制對外連線的工廠內網較難通過審查
- 全程本機執行，文件內容不離開電腦

### OCR 文字正規化
Tesseract 的語言模型版本會影響輸出格式。預設 `tessdata` 會在中文字之間插入空白，並輸出小型全形標點（`﹕﹣﹒﹩`），V1 的規則因此失效（見根目錄 README 的環境需求）。
V2 在 OCR 之後做兩件事，不改動字本身：
1. Unicode NFKC 正規化：小型全形標點、全形英數轉為一般字元
2. 移除中文字之間的空白（英文、數字之間的空白保留，例如 `ACME Semi`、`per wafer`）

## 訂單 schema（`osat_order.py`）

| 欄位 | 說明 | 規則 |
|---|---|---|
| po_no | 客戶 PO 號 | 必填 |
| customer | 客戶名稱 | 與客戶主檔模糊比對（沿用 V1 的 difflib，門檻 0.85） |
| customer_part_no | 客戶料號 | 必須在「客戶料號 → 內部料號」對照表 |
| wafer_lot_id | 晶圓批號 | 查不到晶圓來料庫存就標「待確認」 |
| wafer_size | 晶圓尺寸 | 8-inch / 12-inch |
| package_type | 封裝型式 | BGA / QFN / CSP |
| die_count | 晶粒數量 | 正整數 |
| unit_price | 單價 | 與報價表比對，不一致就列出差額 |
| price_unit | 計價單位 | per wafer / per 1k units |
| delivery_date | 交期 | 日期格式（沿用 V1 的日期正規化） |

文件上的標籤是中英並列（例如 `晶圓批號 Wafer Lot：`），中文標籤被 OCR 讀錯時可用英文標籤定位。

## 三級判定（`osat_validators.py`）

| 等級 | 條件 | 建議處理 |
|---|---|---|
| 明顯錯誤 | 缺欄位、列舉值不合法、晶粒數量不是正整數、料號不在對照表、客戶完全不在主檔 | 退回客戶／業務更正 |
| 需人工確認 | 批號不在庫存（待確認）、單價與報價不符、客戶名稱相似但不完全相同 | 向倉庫確認來料、業務確認價格、確認客戶名稱 |
| 通過 | 以上都沒有 | 自動建單 |

主檔在 `master_data/`：`osat_customers.csv`、`osat_part_map.csv`、`osat_wafer_inventory.csv`、`osat_price_list.csv`。

## 執行

需要 Tesseract 5.5.3，並在 `TESSDATA_PREFIX` 放 `chi_tra`、`eng` 語言模型（建議用 tessdata_fast，與 V1 相同）。

```bat
.venv\Scripts\pip install -r requirements-v2.txt
.venv\Scripts\python demo_run.py                    :: 處理 samples/，印出對照表；samples/ 不存在時自動產生
.venv\Scripts\python generate_osat_samples.py       :: 重新產生 samples/ 與 docs_osat/ 評估集
.venv\Scripts\python evaluate.py --doctype osat     :: V2 評估；不加 --doctype 時就是原本的 V1 評估
.venv\Scripts\python tools\stress_test.py           :: 傾斜校正壓力測試，結果寫入 baselines\stress_test_deskew.txt
```

- `samples/`：4 份 demo 範例，涵蓋三種分級
  - `order_acme_electronic.pdf` 與 `order_acme_scan.pdf`：同一張訂單的電子版，以及由它轉圖、旋轉 +3.5°、加雜訊後存成的純影像 PDF。故意放了兩個錯誤：批號 `LOT-2026-X89` 不在庫存、單價 3,400 與報價 3,250 不符 → 需人工確認
  - `order_globex_pass_scan.pdf`：掃描檔（旋轉 -2.0°），所有檢查都通過 → 通過
  - `order_initech_error_electronic.pdf`：料號 `OSAT-CHIP-9977` 不在對照表 → 明顯錯誤
- `docs_osat/`（不進 repo，可重新產生）：24 份評估訂單
  - o01～o20：4 份電子 PDF、16 份掃描檔，傾斜 ≥ 1° 的有 12 份；10 份刻意放錯（批號不存在 3、單價不符 3、料號不存在 2、客戶名稱打錯 2）
  - o21～o24：4 份模糊掃描檔，高斯模糊核大小 5／9／13／17（由輕到重），輕微傾斜 ±1° 以內；其中 2 份刻意放錯（單價不符、批號不存在）

## 結果

### V1 沒有退步
加入 V2 後重跑 V1 評估，兩批的 `results` 檔與 `baselines/` 裡的 V1 基準逐位元組相同。

| 資料集 | 整份全對 | 自動通過 | 自動通過者正確率 |
|---|---|---|---|
| V1 原始批 docs/（20 份） | 15/20（75%） | 15/20 | 15/15（100%） |
| V1 保留批 docs_holdout/（20 份） | 11/20（55%） | 11/20 | 11/11（100%） |
| V2 封測訂單 docs_osat/（24 份，含 4 份模糊） | 22/24（92%） | 11/24 | 11/11（100%），應攔未攔 0 份 |

### 正規化讓結果較不受語言模型版本影響（V2，24 份）

| 語言模型 | 正規化後：全對／分級正確 | 未正規化：全對／分級正確 |
|---|---|---|
| tessdata_fast | 22/24 ／ 22/24 | 22/24 ／ 22/24 |
| tessdata（預設） | 21/24 ／ 21/24 | 4/24 ／ 6/24 |

- 未正規化 + 預設模型時，只有 4 份電子 PDF（不經 OCR）全對；正規化後兩種模型在 20 份清晰文件上都全對
- 差距只剩模糊樣本：tessdata_fast 模糊類全對 2/4，預設模型 1/4。正規化只能統一輸出格式，救不了模型本身讀錯的字
- 完整輸出在 `baselines/v2_osat_eval_tessdata_fast.txt`、`baselines/v2_osat_eval_tessdata_main.txt`

### 依傾斜角區間與模糊類（tessdata_fast，正規化後）

| 區間 | 份數 | 角度量測誤差平均 | 整份全對 | 分級正確 |
|---|---|---|---|---|
| 電子 PDF | 4 | - | 4/4 | 4/4 |
| \|θ\| < 1° | 4 | 0.04° | 4/4 | 4/4 |
| 1° ≤ \|θ\| < 3° | 4 | 0.01° | 4/4 | 4/4 |
| 3° ≤ \|θ\| < 6° | 4 | 0.02° | 4/4 | 4/4 |
| 6° ≤ \|θ\| ≤ 10° | 4 | 0.02° | 4/4 | 4/4 |
| **模糊 blur** | 4 | 0.04° | **2/4** | **2/4** |

### 模糊樣本逐份

| 檔案 | 模糊核 | tessdata_fast：欄位正確／分級（應為） | 預設 tessdata：欄位正確／分級 |
|---|---|---|---|
| o21 | 5 | 10/10 ／ 通過（通過） | 9/10 ／ 明顯錯誤（晶圓尺寸讀錯） |
| o22 | 9 | 10/10 ／ 需人工確認（需人工確認） | 10/10 ／ 需人工確認 |
| o23 | 13 | 7/10 ／ 明顯錯誤（通過） | 6/10 ／ 明顯錯誤 |
| o24 | 17 | 2/10 ／ 明顯錯誤（需人工確認） | 5/10 ／ 明顯錯誤 |

模糊核 9 以內兩種模型大致讀得出來；13 以上欄位大量讀錯。讀錯的文件**全部被判為「明顯錯誤」，沒有任何一份誤判為「通過」**，所以錯誤不會悄悄進系統；代價是本來正確的訂單會被退回或要人工重看。

## V2 的限制

- **評估集仍偏容易**：同一種版面、電腦字型、中英並列標籤。清晰掃描檔全對，只代表規則與流程在這個情境下是通的，不代表真實訂單的準確率
- **模糊是目前最弱的一環**：模糊類全對只有 2/4（tessdata_fast）、1/4（預設模型），和 V1 的 blur 類（全對 0%）一樣是主要弱點。讀錯的訂單會被判成「明顯錯誤」，建議動作是「退回客戶／業務更正」，但原因其實是掃描品質，實務上應改成「請重新掃描」，目前規則還分不出這兩種情況
- **傾斜角搜尋範圍 ±15°**：超過的掃描檔（例如 20°）量測角度會卡在約 15°，欄位大量讀錯；也無法處理 90°／180° 的整頁轉向
- 壓力測試（`tools/stress_test.py`，結果在 `baselines/stress_test_deskew.txt`；同一張訂單、tessdata_fast、雜訊 σ=10／25／40）：2°～10° 的 12 組中只有 1 組（2°、σ=40）錯 1 個欄位；12°～16° 的 9 組中有 5 組錯 1 個欄位；20° 只對 5～6 個欄位。不做傾斜校正時，5° 只對 2 個欄位，8° 以上幾乎全錯（0～1 個）
- 傾斜量測假設頁面以橫向文字行為主，表格線很多或直書的文件可能不準
- 只支援 PDF；PNG／JPG 掃描檔尚未接上 `pdf_router`
