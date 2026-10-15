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
