# Stock Compass

Stock health and commercial performance for MAF Carrefour Pakistan: a Windows desktop app that works fully
offline. It reads the reports you already get (GIMA, BO, BC workbook, DP workbook, leaflet workbook), works
out what each file is, and turns it into clear numbers in PKR, with the items behind every number.

## Install (Windows)

1. Open the latest build: GitHub → **Actions** → **Build Windows app** → the newest green run → **Artifacts**.
   Tagged versions also appear under **Releases**.
2. Download `StockCompass-Setup-<version>.exe` and run it. No administrator rights are needed; it installs
   for your user only.
   - Prefer no installer? Download `StockCompass-Portable-<version>.zip`, unzip it anywhere, and run
     `StockCompass.exe`.
3. Windows SmartScreen may say "Windows protected your PC" because the app is not code-signed yet. Click
   **More info → Run anyway**, or ask IT to allow it.

Your data stays on your PC in `%LOCALAPPDATA%\StockCompass`. Uninstalling keeps it.

## Use

1. **Add reports.** Drag any report files (or a whole folder) onto the Add reports screen, or paste cells
   copied from Excel. Stock Compass shows what it recognised and how sure it is. Hidden sheets and pivot
   table data are included. Fix anything once (store, date, report type) and it remembers. Then **Import**.
2. **Home.** Key numbers (click any card to open the detail, or ⓘ to see how it is calculated), things
   you should know, the zero stock trend, and the store ranking.
3. **Stock health.** Zero stock, out-of-stock items (with GIMA's reason and whether they are on order),
   negative stock (with cause), aged / DP stock (with the best next step), blocked 007 and leaflet items.
4. **Orders.** Late orders, purge % by store, all orders.
5. **BC scorecard.** Every indicator per store, green or red against its target. Click a cell for the
   explanation.
6. **Data checks.** Everything Stock Compass noticed while reading your files.
7. Use **Where / Department / Section** at the top to focus. **اردو** switches the whole app to Urdu.
8. Every table can be searched, sorted and exported to Excel. Double-click an item to see it in every store.

## Agent (AI analyst)

The **Agent** tab is a chat assistant that reads everything you imported and answers in plain words, with charts and
reports ("What's the status of item 207227 at Emporium?", "How far behind budget are we?", "Make a weekly head office
report"). It can also log promotion periods and change targets or thresholds — it asks before any change.

- **Choose a model** in *Agent → Models & keys*. Free tiers: OpenRouter, Groq, Google Gemini, GitHub Models, NVIDIA,
  Mistral, Cerebras, Hugging Face, Cohere, SambaNova, Cloudflare, Zhipu, ModelScope, SiliconFlow, Ollama Cloud, OVH, LLM7.
  Paid: OpenAI, Anthropic, DeepSeek, xAI, Together, Fireworks, Qwen, Kimi, Perplexity. Any OpenAI-compatible endpoint can
  be added. Press **Test** after pasting a key.
- **Privacy:** with a cloud provider, your question and the data the agent reads are sent to that company. For full
  privacy use *Agent → Offline models*: install the offline runtime once, download a model (Qwen 2.5 3B is a good start),
  click **Load**. Nothing then leaves the PC. Ollama, LM Studio and Jan are detected automatically.
- Keys are stored encrypted with your Windows account. Memory, chats and the change log stay in the local database.
- **Reporting line:** pick who you are in *View as* (commercial director, district manager, head office category team,
  store manager, department head, section manager). The agent gives actions you can take yourself, says what to
  delegate and to whom, and escalates one level up your own line.
- **It learns:** when it meets a header or term it does not know it asks you once and saves the meaning in the
  glossary (*Agent → Memory*); the importer uses the glossary too. It can also import attached files for you.

## Analyse

The **Analyse** page shows any measure (sales, budget, growth, margin, zero stock %, out of stock, lost sales, negative,
aged/DP stock and provision, late orders, leaflet, not selling…) by store, format, region, department, section, family,
supplier, item or day. Add a second dimension for a matrix with row and column totals, filter on anything, pick a
ready-made view, click a row to go one level deeper, and export to Excel. Totals and percentages are recomputed from
the base values.

## For developers

```
pip install -r requirements-dev.txt
python -m pytest            # tests run on synthetic data only
python -m stockcompass      # run from source (src on PYTHONPATH, or pip install -e .)
pyinstaller packaging/stockcompass.spec   # build the app folder
```

- `docs/DATA_SOURCES.md` is the importer specification.
- `CLAUDE.md` holds the project scope and rules.
- Never commit real report files: `.gitignore` blocks Excel, CSV, text and database files.
