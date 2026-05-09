# trade-compass
## System Design Document

---

## 1. Overview

trade-compass is a personal US stock investment decision assistant. It connects to the user's Futu brokerage account, fetches real-time holdings, and uses a LangGraph multi-agent AI system to deliver clear, actionable verdicts: **Buy, Hold, or Sell** — with full reasoning.

Users interact exclusively through **Telegram**.

---

## 2. Infrastructure Architecture

```mermaid
flowchart TD
    User([📱 User\nTelegram])

    subgraph GCP Cloud Run
        APP["☁️ Container 1\ntrade-compass-app\n─────────────────\nLangGraph Agents\nTelegram Bot Handler\n(Webhook mode)"]
        API["☁️ Container 2\ntrade-compass-api\n─────────────────\nFastAPI REST API\nMongoDB client"]
    end

    subgraph GCP Compute Engine e2-micro FREE
        VM["🖥️ VM\ntrade-compass-vm\n─────────────────\nFutu OpenD\nSync Script (every 5min)\nDaily Brief Cron"]
    end

    subgraph MongoDB Atlas FREE
        DB[(M0 Cluster\nholdings\ndecisions\npreferences)]
    end

    User <-->|Webhook| APP
    APP <-->|REST| API
    API <-->|Driver| DB
    VM -->|POST /holdings| API
    VM -->|POST Cloud Run URL\n9:25 AM ET daily| APP
```

**Summary:**
- **2 Cloud Run containers** — app (AI + Telegram) and api (data layer)
- **1 Compute Engine VM** — Futu sync + cron (free tier, us-west1)
- **1 MongoDB Atlas cluster** — free tier M0

---

## 3. AI Agent Architecture

```mermaid
flowchart TD
    START([User Command\n/decide /choose\n/portfolio /review]) --> ROUTE{Intent\nRouter}

    ROUTE -->|single stock| DA
    ROUTE -->|portfolio| PA

    DA["📡 data_agent\n─────────────\nFetch Yahoo Finance\nFetch holdings API\nPopulate shared state"]

    DA --> FA & SA

    FA["📊 fundamental_agent\n─────────────────\nValuation P/E vs peers\nGrowth revenue·EPS\nQuality FCF·margins"]

    SA["📰 sentiment_agent\n─────────────────\nNews search Brave\nAnalyst ratings\nPrice targets"]

    FA --> DCA
    SA --> DCA

    DCA["🎯 decision_agent\n─────────────────\nSynthesize 5-dim score\nWeight by user prefs\nOutput BUY·HOLD·SELL\nSave to MongoDB"]

    PA["📁 portfolio_agent\n─────────────────\nRead all holdings\nLoop → decision_agent\nConcentration risk"]

    PA --> DCA
    DCA --> END([Telegram Response])
```

**5 nodes total:**

| Node | Runs | Parallel |
|------|------|----------|
| `data_agent` | Fetch market data + holdings | — |
| `fundamental_agent` | Valuation / Growth / Quality | ✅ with sentiment |
| `sentiment_agent` | News / Analyst ratings | ✅ with fundamental |
| `decision_agent` | Synthesize → BUY/HOLD/SELL | — |
| `portfolio_agent` | Loop holdings → decision_agent | — |

Routing logic lives in **conditional edges**, not a separate node.

---

## 4. Data Flow

```mermaid
sequenceDiagram
    participant U as User (Telegram)
    participant APP as Cloud Run: app
    participant API as Cloud Run: api
    participant DB as MongoDB Atlas
    participant YF as Yahoo Finance
    participant VM as Compute Engine

    U->>APP: /decide NVDA
    APP->>API: GET /preferences
    API->>DB: query
    DB-->>API: {style, horizon, risk}
    API-->>APP: preferences

    APP->>YF: fetch quote + financials + news
    YF-->>APP: raw market data

    Note over APP: fundamental_agent ║ sentiment_agent (parallel)

    APP->>APP: decision_agent synthesizes
    APP->>API: POST /decisions
    API->>DB: insert decision record
    APP-->>U: BUY/HOLD/SELL + thesis

    VM->>API: POST /holdings (every 5min)
    API->>DB: upsert holdings snapshot
```

---

## 5. Five-Dimension Scorecard

Every analysis runs through the same framework. Weights adjust based on user preferences.

| Dimension | Agent | Data Source |
|-----------|-------|-------------|
| Valuation | fundamental_agent | Yahoo Finance (P/E, EV/EBITDA) |
| Growth | fundamental_agent | Yahoo Finance Financials |
| Quality | fundamental_agent | Yahoo Finance / SEC EDGAR |
| Sentiment | sentiment_agent | Brave Search / Yahoo Finance |
| Timing | sentiment_agent | Yahoo Finance (52w range, trend) |

---

## 6. REST API Endpoints

| Method | Endpoint | Caller | Purpose |
|--------|----------|--------|---------|
| GET | `/holdings` | data_agent | Current Futu positions |
| POST | `/holdings` | Sync script | Push holdings snapshot |
| GET | `/decisions` | decision_agent | History for thesis tracking |
| POST | `/decisions` | decision_agent | Persist verdict |
| GET | `/preferences` | Orchestrator edge | User preferences |
| PUT | `/preferences` | One-time setup | Write preferences |

---

## 7. Data Models

### `holdings`
```json
{
  "synced_at": "2026-05-08T09:25:00Z",
  "positions": [
    {
      "ticker": "NVDA",
      "qty": 100,
      "cost_price": 650.00,
      "market_price": 892.00,
      "unrealized_pl": 24200.00,
      "unrealized_pl_ratio": 0.372
    }
  ]
}
```

### `decisions`
```json
{
  "ticker": "NVDA",
  "date": "2026-05-08",
  "verdict": "BUY",
  "confidence": "medium-high",
  "thesis": "Blackwell supply ramp + cloud capex upcycle",
  "key_assumptions": [
    "Blackwell shipments on track",
    "China export restrictions stabilize"
  ],
  "stop_loss": 820.00,
  "target_price": 1024.00
}
```

### `preferences`
```json
{
  "style": "growth",
  "horizon": "medium",
  "risk": "moderate"
}
```

---

## 8. Repository Structure

```
trade-compass/
  ├── app/                        # Cloud Run: LangGraph + Telegram bot
  │   ├── agents/
  │   │   ├── data.py
  │   │   ├── fundamental.py
  │   │   ├── sentiment.py
  │   │   ├── decision.py
  │   │   └── portfolio.py
  │   ├── graph/
  │   │   └── workflow.py         # LangGraph topology + conditional edges
  │   ├── tools/
  │   │   ├── market_data.py      # Yahoo Finance fetch tools
  │   │   └── portfolio_api.py    # REST API client
  │   ├── telegram/
  │   │   └── bot.py              # Webhook handler
  │   ├── Dockerfile
  │   └── main.py
  ├── api/                        # Cloud Run: FastAPI REST API
  │   ├── routes/
  │   ├── models/
  │   ├── Dockerfile
  │   └── main.py
  ├── sync/                       # Compute Engine: Futu sync script
  │   └── sync.py
  └── terraform/
      ├── bootstrap/              # GCS bucket for tfstate
      ├── compute_engine/         # e2-micro VM
      ├── atlas/                  # MongoDB Atlas M0
      └── cloud_run/              # Both Cloud Run services
```

---

## 9. Technology Stack

| Layer | Technology |
|-------|-----------|
| Agent orchestration | LangGraph |
| LLM connectors | LangChain (`langchain-anthropic`) |
| LLM | Claude Sonnet via OpenRouter |
| Telegram bot | python-telegram-bot (webhook mode) |
| REST API | FastAPI + Motor (async MongoDB driver) |
| Brokerage sync | futu-api (Python) |
| Database | MongoDB Atlas M0 (free) |
| Infrastructure | Terraform + GCP |

---

## 10. Cost Estimate

| Component | Cost |
|-----------|------|
| Cloud Run (app + api) | $0 — scale to zero, personal usage within free tier |
| Compute Engine e2-micro (us-west1) | $0 — GCP always-free tier |
| MongoDB Atlas M0 | $0 — free tier |
| GCS tfstate bucket | < $0.01/month |
| **Total** | **~$0/month** |
