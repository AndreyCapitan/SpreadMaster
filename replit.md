# SpreadMaster - Cryptocurrency Spread Dashboard

## Overview
SpreadMaster is a mobile-friendly real-time cryptocurrency spread monitoring dashboard that tracks price differences between exchanges to identify arbitrage opportunities. Features compact smartphone-optimized interface with color-coded spread indicators and secure exchange account management.

## Project Structure
```
├── app.py                 # Main Flask application with API endpoints + auth
├── models.py              # SQLAlchemy models (User, ExchangeAccount)
├── exchanges.py           # Exchange API integrations (9 exchanges)
├── spread_calculator.py   # Spread calculation and Stochastic indicator logic
├── config.json            # Configuration (exchanges, pairs, thresholds)
├── templates/
│   ├── index.html         # Main dashboard (requires login)
│   └── login.html         # Login/Register/Password recovery
├── static/
│   ├── style.css          # Mobile-first styling
│   └── app.js             # Frontend JavaScript
└── replit.md              # This file
```

## Features
- **User Authentication**: Login/Register with email for password recovery
- **Per-user Settings**: Each user has own exchanges, pairs preferences
- **Mobile-first UI**: Ultra-compact panels optimized for smartphones
- **9 Exchanges**: Binance, Bybit, OKX, HTX, KuCoin, Gate.io, MEXC, Kraken, Bitget
- **25 Popular Pairs**: BTC, ETH, SOL, XRP, DOGE, ADA, AVAX, LINK, etc.
- **Settings Panel**: Profile (email), exchange toggles, API accounts
- **Encrypted Storage**: API keys encrypted with Fernet (PBKDF2-SHA256)
- **Dynamic Filtering**: Toggle exchanges/pairs - spreads update instantly
- **Spread Calculation**: Arbitrage formula (Sell_Bid - Buy_Ask) / Buy_Ask
- **Color Indicators**: Green >1%, Yellow 0.5-1%, Gray <0.5%
- **Charts Panel**: Candlestick + Stochastic Oscillator (5m/15m/1h)
- **Adjustable Interval**: 500ms - 10000ms update rate

## Configuration
Edit `config.json` to modify:
- Exchange settings and API endpoints
- Trading pairs list
- Spread thresholds and colors
- Stochastic indicator settings

## Technical Stack
- Python 3.11
- Flask + Flask-Login (authentication)
- Gunicorn (production server)
- PostgreSQL + SQLAlchemy (database)
- Werkzeug (password hashing)
- Cryptography/Fernet (API key encryption)
- Pandas/NumPy (data processing)
- Plotly (charting)
- REST APIs for exchange data

## Future Development
- **Phase 1 (Current)**: Testing mode with real price data, virtual contracts
- **Phase 2 (Next)**: Connect to exchange APIs for real trade execution
  - Register on exchanges (Binance, Bybit, OKX, etc.)
  - Obtain API keys with trading permissions
  - Implement real order placement (short on high exchange, long on low)
  - Auto-close positions when spread converges
- Real-time WebSocket connections
- Position monitoring and P&L tracking

## Recent Changes
- January 2026: Added AI Assistant and Trading Modes
  - Three trading modes: Demo (virtual), Real (requires API keys), ML (AI-assisted)
  - AI Assistant panel with chat and strategy button (ML mode only)
  - AI analyzes spreads and suggests optimal settings
  - Spread growth monitoring with automatic AI warnings
  - Removed number input spinners for cleaner mobile UI
  - OpenAI integration for intelligent trading assistance
- January 2026: Added autonomous 24/7 trading mode
  - Background worker (auto_trader.py) runs independently of browser
  - Per-user settings: open/close thresholds, max contracts
  - Toggle in UI header to enable/disable
  - Auto-opens contracts when spread >= open_threshold
  - Auto-closes when spread <= close_threshold
- January 2026: Added Bitget exchange (9th exchange)
- January 2026: Color-coded exchanges in spread list
  - Green = account connected (API keys added)
  - Gray = not connected
  - Per-user exchange accounts with user_id
- January 2026: Contract persistence across sessions
  - Contracts saved to database
  - Timer shows real duration from open time
  - History shows duration of closed contracts
- January 2026: Added user authentication system
  - Login/Register with email for password recovery
  - Per-user preferences (exchanges, pairs stored in DB)
  - Password recovery via email token
  - Profile section in settings to update email
  - Logout button in header
- January 2026: Added settings modal with account management
- Encrypted API key storage with Fernet
- 9 exchanges with public APIs
- Dynamic show/hide spreads based on toggle state
- Backend/frontend sync for proper filtering
