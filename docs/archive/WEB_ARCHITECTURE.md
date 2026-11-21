# Axon Trading Web Application - Architecture & System Design

## 🏗️ System Architecture

```
╔════════════════════════════════════════════════════════════════════════╗
║                     AXON TRADING WEB APPLICATION                  ║
╚════════════════════════════════════════════════════════════════════════╝

┌─────────────────────────────────────────────────────────────────────────┐
│                         CLIENT TIER (Browser)                           │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                           │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │                    Trading Interface (HTML)                      │   │
│  ├───────────────┬───────────────┬───────────────┬──────────────────┤   │
│  │  Trading      │   Orders      │   Positions   │   Portfolio      │   │
│  │  Terminal     │   Management  │   Dashboard   │   Summary        │   │
│  └───────────────┴───────────────┴───────────────┴──────────────────┘   │
│                                                                           │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │              JavaScript Client Logic (client.js)                 │   │
│  │  • WebSocket Connection Management                              │   │
│  │  • Real-time UI Updates                                         │   │
│  │  • API Call Handling                                            │   │
│  │  • Form Validation                                              │   │
│  │  • Event Listeners                                              │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                                                                           │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │                    Styling (style.css)                           │   │
│  │  • Responsive Grid Layout                                       │   │
│  │  • Dark Trading Theme                                           │   │
│  │  • Mobile Optimization                                          │   │
│  └──────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
                              ↓ HTTP/WebSocket ↓
┌─────────────────────────────────────────────────────────────────────────┐
│                      API TIER (Flask Server)                            │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                           │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │          REST API Endpoints (Flask Routes)                     │    │
│  ├──────────────┬──────────────┬──────────────┬──────────────────┤    │
│  │  Trading     │  Portfolio   │  Orders      │  Market          │    │
│  │  • /api/     │  • /api/     │  • /api/     │  • /api/         │    │
│  │    trade     │    portfolio │    orders    │    market-       │    │
│  │  • /api/     │  • /api/     │  • /api/     │    status        │    │
│  │    stats     │    positions │    <id>      │  • /api/health   │    │
│  └──────────────┴──────────────┴──────────────┴──────────────────┘    │
│                                                                           │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │         WebSocket Events (Socket.IO)                           │    │
│  ├──────────────────────────────────────────────────────────────────    │
│  │  • order_update      → Real-time order status                  │    │
│  │  • position_update   → Position changes                        │    │
│  │  • portfolio_update  → Balance and P&L changes                 │    │
│  │  • market_status     → Market open/close                       │    │
│  │  • sync_orders       → Initial state sync                      │    │
│  └──────────────────────────────────────────────────────────────────    │
│                                                                           │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │         Business Logic & State Management                      │    │
│  ├──────────────────────────────────────────────────────────────────    │
│  │  • Order validation & processing (via capital engine           │    │
│  │    execution layer)                                            │    │
│  │  • Portfolio calculations & equity tracking                    │    │
│  │  • Position tracking                                           │    │
│  │  • Market status checking                                      │    │
│  │  • Real-time state broadcasting via Socket.IO                  │    │
│  └──────────────────────────────────────────────────────────────────    │
│                                                                           │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │         State & Persistence Layer                              │    │
│  ├──────────────────────────────────────────────────────────────────    │
│  │  In-memory store (current session):                            │    │
│  │  ├─ orders: [list of order objects]                           │    │
│  │  ├─ positions: [list of position objects]                     │    │
│  │  └─ portfolio: {capital, value, pnl, cash}                    │    │
│  │                                                              │    │
│  │  PostgreSQL via SQLAlchemy (persistent history):               │    │
│  │  ├─ trades & portfolio snapshots                              │    │
│  │  ├─ regime history & kill-switch log                          │    │
│  │  └─ correlation matrices & engine config                      │    │
│  └──────────────────────────────────────────────────────────────────    │
└─────────────────────────────────────────────────────────────────────────┘
                         ↓ Function Calls ↓
┌─────────────────────────────────────────────────────────────────────────┐
│               EXECUTION TIER (Capital Engine)                           │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                           │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐      │
│  │  Sandbox Engine  │  │ ExecutionEngine │  │  Risk Engine &   │      │
│  ├──────────────────┤  ├──────────────────┤  ├──────────────────┤      │
│  │ • Simulates      │  │ • Routes orders  │  │  Kill-Switch     │      │
│  │   orders (mock   │  │   to Angel One   │  │ • Per-trade risk │      │
│  │   mode) with     │  │   Smart API or   │  │   checks, daily  │      │
│  │   slippage       │  │   sandbox        │  │   loss / weekly  │      │
│  │ • Returns order  │  │ • Normalises     │  │   drawdown /     │      │
│  │   result with    │  │   broker status  │  │   portfolio heat │      │
│  │   fill price &   │  │                  │  │ • Global         │      │
│  │   notional       │  │                  │  │   kill-switch    │      │
│  └──────────────────┘  └──────────────────┘  └──────────────────┘      │
│                                                                           │
│  ┌──────────────────┐  ┌──────────────────┐                            │
│  │  Market Data     │  │  Strategy Engine │                            │
│  │  Feed            │  │  (Optional)      │                            │
│  └──────────────────┘  └──────────────────┘                            │
└─────────────────────────────────────────────────────────────────────────┘
                         ↓ API Calls ↓
┌─────────────────────────────────────────────────────────────────────────┐
│              BROKER TIER (Angel One Smart API)                          │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                           │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │              Angel One Smart API Interface                       │   │
│  │  • Authentication                                               │   │
│  │  • Order Placement                                              │   │
│  │  • Position Retrieval                                           │   │
│  │  • Order Status Tracking                                        │   │
│  │  • Account Information                                          │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                                                                           │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │              Market Data Providers                               │   │
│  │  • Real-time quotes                                             │   │
│  │  • Historical data                                              │   │
│  │  • Market status                                                │   │
│  └──────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘

```

---

## 🔄 Request/Response Flow

### Trade Placement Flow

```
┌──────────────┐
│   User       │
│   (Browser)  │
└────────┬─────┘
         │ 1. Click "Place Trade"
         │    Submit form with:
         │    - Symbol, Quantity, Side
         │    - Order Type, Mode
         ▼
┌──────────────────────┐
│   JavaScript Client  │
│   (client.js)        │
│   • Validate form    │
│   • Show loading UI  │
└────────┬─────────────┘
         │ 2. POST /api/trade
         │    (JSON data)
         ▼
┌──────────────────────┐
│   Flask API Server   │
│   (web_server.py)    │
│   • Parse request    │
│   • Create order obj │
│   • Add to store     │
└────────┬─────────────┘
         │ 3. Execute async
         │    (background thread)
         ▼
┌──────────────────────┐
│   Execute Trade      │
│   Module             │
│   • Mock or Angel One│
└────────┬─────────────┘
         │ 4. Get result
         │    (filled/rejected)
         ▼
┌──────────────────────┐
│   Update Store       │
│   • Change status    │
│   • Update portfolio │
└────────┬─────────────┘
         │ 5. Broadcast
         │    (WebSocket)
         ▼
┌──────────────────────┐
│   All Connected      │
│   Clients receive    │
│   order_update event │
└────────┬─────────────┘
         │ 6. Update UI
         │    (no refresh)
         ▼
┌──────────────┐
│   User sees  │
│   order in   │
│   real-time  │
└──────────────┘
```

---

## 📊 Data Flow Diagram

```
                    ┌─────────────────────────────┐
                    │    User Interaction         │
                    └────────────┬────────────────┘
                                 │
                  ┌──────────────┴──────────────┐
                  │                             │
        ┌─────────▼──────┐         ┌────────────▼─────┐
        │  Place Trade   │         │  View Orders,    │
        │  Form Submit   │         │  Positions, etc  │
        └────────┬───────┘         └────────┬─────────┘
                 │                          │
         ┌───────▼────────┐         ┌───────▼────────┐
         │ API Call       │         │ API Call       │
         │ POST /api/trade│         │ GET /api/*     │
         └────────┬───────┘         └────────┬───────┘
                  │                          │
                  └──────────────┬───────────┘
                                 │
                         ┌───────▼────────┐
                         │  Flask Server  │
                         │  (web_server.py)
                         └────────┬────────┘
                                  │
                    ┌─────────────┼─────────────┐
                    │             │             │
            ┌───────▼────┐   ┌────▼──────┐  ┌──▼──────────┐
            │  Validate  │   │ Execute   │  │  Update     │
            │  & Store   │   │  Trade    │  │  Portfolio  │
            └────────────┘   └────┬──────┘  └─────────────┘
                                  │
                        ┌─────────▼─────────┐
                        │  Update Store     │
                        │  & Emit WebSocket │
                        └─────────┬─────────┘
                                  │
                    ┌─────────────┼─────────────┐
                    │             │             │
            ┌───────▼───┐  ┌──────▼────┐  ┌───▼──────────┐
            │ Browser 1 │  │ Browser 2 │  │ Browser N    │
            │ (WebSocket│  │(WebSocket)│  │ (WebSocket)  │
            │ Update)   │  │ Update)   │  │ Update)      │
            └───────────┘  └───────────┘  └──────────────┘
```

---

## 🔌 WebSocket Event Flow

```
                         ┌────────────────┐
                         │  Flask Server  │
                         │ (SocketIO)     │
                         └────────┬───────┘
                                  │
                    ┌─────────────┼─────────────┐
                    │             │             │
            ┌───────▼───┐  ┌──────▼────┐  ┌───▼──────────┐
            │            │   │          │   │              │
Enable      │ Register   │   │ Broadcast│   │ Sync State  │
Connection  │ Handlers   │   │ Updates  │   │ on Connect  │
            │            │   │          │   │              │
            └────┬───────┘   └────┬─────┘   └───┬──────────┘
                 │                │             │
        ┌────────▼────────┐       │             │
        │ subscribe_      │       │             │
        │ updates event   │       │             │
        └────────┬────────┘       │             │
                 │                │             │
        ┌────────▼────────┐       │             │
        │ Acknowledge     ├───────┼─────────────┼────┐
        │ subscription    │       │             │    │
        └────────────────┘       │             │    │
                                 │             │    │
                    ┌────────────▼┐     ┌──────▼──┐ │
                    │ order_update│     │ sync_   │ │
                    │ position_   │     │ orders  │ │
                    │ update      │     │ sync_   │ │
                    │ portfolio_  │     │ posit.  │ │
                    │ update      │     │ sync_   │ │
                    │             │     │ portfolio
                    └────────┬────┘     └────┬────┘ │
                             │                │      │
                    ┌────────▼────────────────▼────┐ │
                    │   All Clients Receive        │ │
                    │   Event Data & Update UI     │ │
                    └─────────────────────────────┘ │
                                                    │
                    ┌───────────────────────────────┘
                    │
            ┌───────▼──────────┐
            │ display_update   │
            │ without refresh  │
            └──────────────────┘
```

---

## 🌑 State Management

```
┌─────────────────────────────────────────────────────┐
│            Server-Side State                        │
├─────────────────────────────────────────────────────┤
│                                                      │
│  orders_store = {                                   │
│    "orders": [                                      │
│      {                                              │
│        "id": "ORD_...",                            │
│        "symbol": "RELIANCE",                       │
│        "quantity": 100,                            │
│        "side": "BUY",                              │
│        "status": "FILLED",                         │
│        "timestamp": "...",                         │
│        "broker_response": {...}                    │
│      },                                             │
│      ...more orders                                │
│    ],                                              │
│                                                     │
│    "positions": [                                  │
│      {                                              │
│        "symbol": "RELIANCE",                       │
│        "quantity": 100,                            │
│        "pnl": 450.00,                             │
│        "pnl_percent": 0.158                       │
│      },                                             │
│      ...more positions                             │
│    ],                                              │
│                                                     │
│    "portfolio": {                                  │
│      "total_capital": 100000,                     │
│      "current_value": 100450,                     │
│      "daily_pnl": 450,                            │
│      "cash_available": 71550                      │
│    }                                               │
│  }                                                 │
│                                                     │
└─────────────────────────────────────────────────────┘
         │ WebSocket Broadcast │
         ▼
┌─────────────────────────────────────────────────────┐
│            Client-Side State (JavaScript)           │
├─────────────────────────────────────────────────────┤
│                                                      │
│  appState = {                                       │
│    orders: [],        │ Synced from server         │
│    positions: [],     │ Real-time updates          │
│    portfolio: {},     │ Auto-refreshed             │
│    marketStatus: "",  │ Market hours tracking      │
│    stats: {}          │ Trading statistics         │
│  }                                                  │
│                                                     │
└─────────────────────────────────────────────────────┘
         │ UI Rendering │
         ▼
┌─────────────────────────────────────────────────────┐
│         DOM Updates (Real-time Display)             │
├─────────────────────────────────────────────────────┤
│  • Orders Table                                     │
│  • Positions Table                                  │
│  • Portfolio Cards                                  │
│  • Market Status Indicator                         │
│  • Statistics Display                              │
└─────────────────────────────────────────────────────┘
```

---

## 🔐 Security Layers

```
┌──────────────────────────────────────────┐
│         Input Validation                 │
│  - Symbol check                          │
│  - Quantity validation                   │
│  - Side validation                       │
│  - Mode validation                       │
└────────────────┬─────────────────────────┘
                 │
┌────────────────▼─────────────────────────┐
│         Authorization                    │
│  - API key validation                    │
│  - Mode restrictions                     │
│  - Capital limits                        │
└────────────────┬─────────────────────────┘
                 │
┌────────────────▼─────────────────────────┐
│         Rate Limiting                    │
│  - Per-user limits                       │
│  - Per-endpoint limits                   │
│  - DDoS protection                       │
└────────────────┬─────────────────────────┘
                 │
┌────────────────▼─────────────────────────┐
│         Execution                        │
│  - Risk checks                           │
│  - Broker validation                     │
│  - Order logging                         │
└────────────────┬─────────────────────────┘
                 │
┌────────────────▼─────────────────────────┐
│         Audit Trail                      │
│  - All trades logged                     │
│  - State changes recorded                │
│  - Error tracking                        │
└──────────────────────────────────────────┘
```

---

## 📈 Performance Considerations

```
┌─────────────────────────────────────────┐
│         Optimization Targets             │
├─────────────────────────────────────────┤
│                                          │
│  Page Load Time: < 1 second             │
│  • Minified CSS/JS                      │
│  • Lazy loading                         │
│  • Browser caching                      │
│                                          │
│  API Response: < 100ms                  │
│  • Non-blocking execution               │
│  • Async task handling                  │
│  • Connection pooling                   │
│                                          │
│  WebSocket Latency: < 50ms              │
│  • Binary frames (not JSON)             │
│  • Compression enabled                  │
│  • Connection reuse                     │
│                                          │
│  Scalability: 100+ concurrent users     │
│  • Event-driven architecture            │
│  • Non-blocking I/O                     │
│  • Horizontal scaling ready             │
│                                          │
└─────────────────────────────────────────┘
```

---

## 🚀 Deployment Architecture

```
        ┌────────────────────────────────┐
        │      Internet / Users          │
        └────────────────┬───────────────┘
                         │
        ┌────────────────▼───────────────┐
        │    Load Balancer (Optional)    │
        │  - Traffic distribution        │
        │  - SSL termination             │
        └────────────────┬───────────────┘
                         │
        ┌────────────────▼───────────────┐
        │    Web Server Instances        │
        │  (Multiple Axon servers)   │
        │  ┌──────────┬──────────┐       │
        │  │Instance 1│Instance 2│       │
        │  └──────────┴──────────┘       │
        └────────────────┬───────────────┘
                         │
        ┌────────────────▼───────────────┐
        │    Shared State Service        │
        │  (Redis Cache - Optional)      │
        └────────────────┬───────────────┘
                         │
        ┌────────────────▼───────────────┐
        │    Database Layer (Optional)   │
        │  - PostgreSQL for persistence  │
        └────────────────┬───────────────┘
                         │
        ┌────────────────▼───────────────┐
        │    External APIs               │
        │  - Angel One Smart API         │
        │  - Market Data Providers       │
        └────────────────────────────────┘
```

---

## 🔗 Integration Points

```
Axon Web ←→ Angel One Smart API
     │              │
     │              ├─ place_order()
     │              ├─ get_positions()
     │              ├─ get_orders()
     │              └─ cancel_order()
     │
     ├─ Market Data Feed
     │   ├─ Fetch prices
     │   ├─ Get quotes
     │   └─ Market status
     │
     ├─ Trading Logic
     │   ├─ Signal generation
     │   ├─ Risk management
     │   └─ Portfolio tracking
     │
     └─ User Interface
         ├─ REST API
         ├─ WebSocket
         └─ HTML/CSS/JS
```

---

## 📊 Component Interaction Matrix

| Component 1 | Component 2 | Interaction | Protocol |
|------------|------------|---|---|
| Browser | Flask Server | HTTP Request/Response | HTTP/HTTPS |
| Browser | Flask Server | Real-time updates | WebSocket |
| Flask Server | Broker API | Trade execution | HTTPS |
| Flask Server | Market Data | Feed fetch | HTTPS |
| Flask Server | Database | State persistence | SQL |
| Multiple Browsers | WebSocket | Sync updates | WebSocket |

---

**Architecture Version**: 1.0  
**Last Updated**: February 2024  
**Status**: Production Ready ✓

For implementation details, see: [WEB_IMPLEMENTATION_SUMMARY.md](WEB_IMPLEMENTATION_SUMMARY.md)
