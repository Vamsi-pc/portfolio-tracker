# Daily portfolio agent

Sends a Telegram update on your Indian stock portfolio every trading day at about 4:15 PM IST:
P&L, top movers, a table of all holdings, and a news headline for each stock that moved more
than 2%.

## How it works

| Step | What | How |
|---|---|---|
| 1 | Read holdings | `portfolio.csv` |
| 2 | Prices and P&L | Yahoo Finance via `yfinance`, plain Python arithmetic |
| 3 | Headlines | Google News RSS for each stock that moved more than 2% |
| 4 | Deliver | Telegram Bot API |

No LLM and no API key are involved, so it costs nothing to run.

## Setup (about 15 minutes)

### 1. Create the Telegram bot
1. In Telegram, message **@BotFather**, send `/newbot`, and follow the prompts. Copy the **token**.
2. Open your new bot and send it any message (bots cannot message you first).
3. Open `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser and copy `"chat":{"id": ...}`.
   That number is your **chat ID**.

### 2. Put the code on GitHub
1. Create a **private** repository (your holdings are in it) and push these files.
2. In the repo: Settings → Secrets and variables → Actions → New repository secret. Add
   `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.
3. Edit `portfolio.csv` with your real holdings.

### 3. Test it
Actions tab → Daily portfolio update → **Run workflow**. A message should arrive within a minute.
Manual runs always send; scheduled runs skip weekends and market holidays automatically.

## portfolio.csv

```
symbol,name,quantity,avg_price,exchange
RELIANCE,Reliance Industries,10,1250.00,NSE
```

- `symbol`: the NSE symbol (or the BSE scrip code with `exchange` set to `BSE`)
- `name`: used for news searches
- `exchange`: `NSE` or `BSE`; blank means NSE

Update the file whenever you buy or sell.

## Run locally

```bash
pip install -r requirements.txt
DRY_RUN=true FORCE_SEND=true python agent.py      # prints the message instead of sending
```

## Good to know

- GitHub's scheduler can start a job 5 to 30 minutes late.
- GitHub disables scheduled workflows after 60 days with no repo activity; any commit re-enables it.
- Yahoo Finance is an unofficial data source and occasionally fails. A stock with no price is
  listed at the bottom of the message rather than breaking the run.

## Ideas for version 2

- Weekly summary on Fridays with the week's change
- Alerts when a holding crosses a price or drops more than X% intraday
- Pull holdings from your broker's API instead of the CSV
- Compare the portfolio's day against Nifty 50 (`^NSEI`)
