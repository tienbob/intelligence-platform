# Stock and finance terms in plain English

This guide explains the language used in this app. You do not need a finance background. Examples use imaginary companies and numbers; they explain the terms rather than recommend investments.

## 1. Start here: what does this app do?

The app collects company information, prices, financial reports, news and events. It calculates measurements, ranks companies, and uses AI to explain the information.

Think of it as a research notebook with a calculator and an assistant:

1. **Data collection:** bring information from data providers into our database.
2. **Calculations:** measure company finances, price patterns and risk.
3. **Screening:** compare companies using calculated scores.
4. **Deep dive:** generate a fuller explanation using stored data and relevant documents.
5. **Review:** read the explanation, inspect its evidence, and check what information is missing.

A completed analysis means the job finished. It does not mean every financial field was available or every AI statement is correct. A deep dive reads stored information; starting one does not automatically fetch fresh prices from vendors.

### What the main pages mean

| Page | Plain meaning |
| --- | --- |
| Dashboard | A summary of activity and available information. |
| Companies / Company detail | The businesses we track and their stored information. |
| Market | Price and market information. Check the data date. |
| Opportunities | Companies ranked for further investigation. The score uses your latest visible completed deep dive when available; otherwise it uses screening results. |
| AI Analysis / Deep dive | A saved research explanation with scores, supporting sources and limitations. |
| News | Articles associated with companies. |
| Events | Things that happened or may happen and could affect a company. |
| Alerts | Notifications when configured conditions are met. |
| Backtest | A simulation of how a strategy would have behaved using historical information. |
| Search | Find companies or relevant stored information. |

## 2. The three numbers people easily confuse

| Number | What question does it answer? | How to read it |
| --- | --- | --- |
| Investment score | How attractive does the company's combination of inputs look under our scoring rules? | 0–100. Higher means stronger under this model. |
| Risk score | How concerning are the measured risks? | 0–100. Higher means more risk. |
| Confidence | How much support does the scoring result have from the available inputs? | Often displayed as a percentage; internally usually 0–1. Higher means more input support. |

**Example:** investment score **49**, risk **48**, confidence **70%** means the model assigned 49 attractiveness points, measured 48 risk points, and has a 70% confidence measure. It does not mean a 49% return or a 70% chance of making money.

An AI explanation can also contain its own confidence value. That is the model's assessment of its explanation; the saved scoring confidence is calculated by the scoring engine. Neither is a calibrated probability of investment success.

### Where the investment score comes from

Python calculates the final score. The AI writes the explanation. The current default scoring weights are:

| Component | Plain meaning | Default contribution |
| --- | --- | --- |
| Fundamental | Business profitability and financial strength | 30% |
| Valuation | Price relative to earnings, sales, assets or cash generation | 20% |
| Growth | How quickly business results are growing | 15% |
| Technical | Patterns in prices and trading activity | 10% |
| Sentiment | Positive or negative tone of available news | 10% |
| Catalyst | Events that could change the company's outlook | 10% |
| Risk | Measured concerns | A penalty with 15% weight |

The default calculation adds the six positive contributions, subtracts the risk penalty, and keeps the result between 0 and 100. These are model rules, not universal financial laws; configured weights can change.

For example, if all six positive components are 60 and risk is 40, the default score is `60 × 0.95 − 40 × 0.15 = 51`.

Some missing inputs receive a neutral fallback of 50. **A 50 can mean “we lack information,” rather than “we measured average performance.”** Read coverage and warnings alongside scores.

### Recommendation labels

These are app categories derived from the score, not instructions to place a trade. Current default thresholds are:

| Score | Label | Plain meaning |
| --- | --- | --- |
| 80–100 | STRONG_OPPORTUNITY | Strongest category under the scoring rules. |
| 70 to below 80 | OPPORTUNITY | Looks promising under the rules. |
| 60 to below 70 | WATCH | Worth following. |
| 45 to below 60 | NEUTRAL | No strong overall signal. |
| 30 to below 45 | CAUTION | Several concerns. |
| 15 to below 30 | HIGH_RISK | Weak overall ranking. This label comes from investment score, not a direct risk-score threshold. |
| Below 15 | AVOID | Lowest category under the rules. |

## 3. Basic stock language

| Term | Simple explanation | Example or detail |
| --- | --- | --- |
| Fintech | Technology used for financial work | This app uses software to collect and analyze financial information. |
| Stock / share / equity | A small ownership piece of a company | Owning shares means owning a small part of the business. “Equity” can also mean owners' value in financial reports. |
| Ticker / symbol | A short identifier used to look up a security | AAPL identifies Apple in our US stock data. Exchange context matters. |
| Exchange | A market where securities trade | The same business can have different listings. |
| Sector / industry | Broad / narrower business grouping | Technology / software. Useful when comparing similar companies. |
| Market cap | Share price multiplied by the number of shares | 10 million shares at $20 gives a $200 million market cap. This is not the company's cash balance. |
| ETF | Exchange-traded fund: a traded basket of investments | SPY is a fund, so ordinary company financial ratios may be missing or less meaningful. |
| Benchmark | A reference used to compare performance | Compare a strategy with an index or ETF over the same dates. |
| Index | A measurement of a selected group of securities | Used to describe a market or group of companies. |
| Return | How much an investment gained or lost relative to its starting value | $100 becoming $110 is a 10% price return. Dividends and costs depend on the calculation. |
| Dividend | Money a company distributes to shareholders | A price-only return may leave this out. |
| Stock split | More shares with a proportionately lower price | A 2-for-1 split doubles shares; the split itself does not double your wealth. |
| Adjusted price | Historical price changed to account for certain corporate actions | Check which adjustments the data source includes before interpreting returns. |
| OHLCV | Open, High, Low, Close, Volume | A summary of prices and trading quantity for a time period. |
| Volume | Number of shares traded | High volume means more trading, not necessarily more buyers than sellers. |
| Liquidity | How easily something can be traded | The app's volume-based liquidity score is an approximation, not a guarantee of execution price. |
| Spread | Difference between the best buying and selling prices | A wider spread can make trading more expensive. |

## 4. Fundamentals: how the business is doing

**Fundamental analysis** looks at the business behind the stock. **Technical analysis** looks at price and trading patterns.

Financial reports usually cover a **quarter** (roughly three months) or a **year**. A reporting period is the period the numbers describe; a filing date is when the report was published. **TTM** means “trailing twelve months,” the most recent twelve months combined. Always check the period, currency and units when comparing numbers.

### Financial statements

| Term | Plain meaning |
| --- | --- |
| Income statement | Sales, expenses and profit over a period. |
| Balance sheet | What the business owns and owes at a particular date. |
| Cash-flow statement | How cash came in and went out over a period. |
| Revenue / sales | Money earned from selling goods or services before subtracting expenses. |
| Gross profit | Revenue minus the direct cost of producing the goods or services. |
| Operating income | Profit after operating costs, before items such as taxes and financing costs. |
| Net income / earnings | Profit after the remaining expenses, including taxes. |
| Assets | Things the company owns or controls. |
| Liabilities | Obligations the company owes. Includes more than borrowed debt. |
| Debt | Borrowed money that must be repaid. |
| Cash | Cash available on the balance sheet. |
| Shareholders' equity / book value | Assets minus liabilities: accounting value belonging to owners. |
| Operating cash flow | Cash generated by normal business activity. Profit and cash flow can differ. |
| Capex / capital expenditure | Spending on assets such as equipment and buildings. |
| Free cash flow / FCF | Commonly operating cash flow minus capital expenditure. Cash left after that investment. |
| EPS | Earnings per share: profit allocated to each share. |

### Ratios and growth measurements

A ratio compares two numbers. It makes different-sized companies easier to compare, but business type and accounting differences still matter.

| Term | Simple explanation | Example or interpretation |
| --- | --- | --- |
| P/E | Share price divided by earnings per share | $20 price / $2 EPS = 10. Roughly $10 of share price per $1 of annual earnings. Negative earnings complicate interpretation. |
| P/S | Company market value divided by sales | A way to compare price with revenue, including when profits are absent. Sales alone do not tell you profitability. |
| P/B | Company market value divided by book equity | Compares the market price with accounting equity. Can be less informative for businesses built on intangible assets. |
| Enterprise value / EV | A measure of business value that typically includes debt and subtracts cash | Broader than market cap. |
| EBITDA | Earnings before interest, taxes, depreciation and amortization | An operating-performance approximation. It is not free cash flow. |
| EV/EBITDA | Enterprise value divided by EBITDA | Another valuation comparison. |
| ROE | Return on equity: profit relative to owners' accounting equity | Measures how much profit is generated relative to that equity. Debt or small equity can inflate it. |
| ROA | Return on assets: profit relative to assets | Measures profit relative to the asset base. |
| Gross / operating / net margin | The corresponding profit divided by revenue | $10 net profit on $100 revenue means a 10% net margin. |
| Debt/equity | Debt relative to owners' equity | Describes borrowing relative to the equity base. |
| Current ratio | Current assets divided by current liabilities | A rough measure of ability to cover near-term obligations. |
| FCF yield | Free cash flow relative to market value | $5 annual FCF / $100 market value = 5%. It is not a promised cash payout. |
| Revenue growth | How much sales increased or decreased | $100 becoming $110 is 10% growth. |
| Earnings growth | How much profit increased or decreased | Comparisons can be misleading around losses or a tiny starting profit. |
| FCF growth | How much free cash flow changed | Cash flow can fluctuate because of investment timing. |
| YoY / QoQ | Year-over-year / quarter-over-quarter | Comparing with the same period last year / the previous quarter. |
| Basis point / bps | One hundredth of a percentage point | 100 bps = 1 percentage point. |

**Cheap** in valuation language means cheap relative to a financial measure. A $5 stock is not automatically cheaper than a $500 stock.

## 5. Technical indicators: what prices have been doing

An **indicator** is a calculated summary of historical prices or volume. A **signal** is an interpretation of that summary. A historical pattern does not guarantee the next price move.

| Term | Plain meaning |
| --- | --- |
| Trend | The general direction of prices over a chosen period. |
| Momentum | How much prices have moved over a recent period. Positive momentum means they rose over that window. |
| SMA | Simple moving average: average price over a window, with equal weight for each observation. |
| EMA | Exponential moving average: average giving more weight to recent observations. |
| RSI | Relative Strength Index: compares recent upward and downward movements on a 0–100 scale. “Overbought” or “oversold” describes recent movement, not fair business value. |
| MACD | Moving Average Convergence Divergence: compares faster and slower moving averages to describe momentum changes. |
| Signal line / crossover | A reference line / one indicator crossing another. Used to flag a possible change in momentum. |
| ATR | Average True Range: typical size of price swings, considering gaps between periods. It measures movement size, not direction. |
| Bollinger Bands | Bands around an average price whose width responds to variation. They are not guaranteed price boundaries. |
| VWAP | Volume-Weighted Average Price: average price giving more weight to heavier trading. Our calculation uses the loaded bars; do not assume it is a live intraday execution benchmark. |
| Volatility | How much returns fluctuate. Higher means larger variation, not automatically falling prices. |
| Annualized volatility | Variation scaled to a yearly convention. It is an estimate based on historical returns. |
| Volume anomaly | Unusually high trading volume compared with a recent average. It signals unusual activity without proving its cause. |
| Support / resistance | Price areas analysts think may attract buying / selling. These are interpretations, not hard limits. |
| Bullish / bearish | An expectation of rising / falling prices, or a positive / negative interpretation. |

## 6. Risk, macroeconomics and events

| Term | Simple explanation |
| --- | --- |
| Drawdown | A decline from an earlier peak. $100 falling to $80 is a 20% drawdown. |
| Maximum drawdown | The biggest peak-to-trough decline within the measured period. Some outputs store a positive loss magnitude; others use a negative signed return. |
| VaR / Value at Risk | A loss threshold estimated from returns at a chosen confidence level. Our risk calculation uses a lower historical daily-return percentile; it can be negative. It is not the worst possible loss. |
| Fundamental risk | Concerns in the company's finances, such as debt and weak financial health. |
| Macro / macroeconomic | The wider economy rather than one company. |
| GDP | A measure of an economy's production. |
| Inflation / CPI | Rising general prices / a consumer-price measure used to track them. |
| Interest rate | The cost of borrowing money. Rate changes can affect costs and valuations. |
| Unemployment | A measure of people seeking work without a job. |
| Yield | A return measure whose meaning depends on context, such as a bond yield or FCF yield. |
| Catalyst | An event that could change expectations or valuation, positively or negatively. |
| Earnings release | Publication of company financial results. |
| Guidance | Management's outlook for future business performance. |
| Earnings surprise | Results differing from the expectation used for comparison. |
| M&A | Mergers and acquisitions: businesses combining or buying other businesses. |
| Filing / SEC filing | A formal regulatory document. SEC filings relate to US securities regulation. |
| Sentiment | Whether the language or interpretation is positive, negative or neutral. Positive coverage does not prove strong financial performance. |
| Materiality | How important an event might be to the business or investment case. |
| Severity | How serious an issue or event is considered to be. |
| Anomaly | Something unusual compared with a reference pattern. It is a reason to investigate. |

## 7. Reading the AI explanation

| Term | What it means in the app |
| --- | --- |
| Summary | A short overview. |
| Market interpretation | The AI's explanation of what the information may mean. |
| Investment thesis | The argument for why the company might be attractive or unattractive. |
| Bull case | Reasons the outcome could be favorable. |
| Bear case | Reasons the outcome could be unfavorable. |
| Risk factor | A condition that could undermine the argument. |
| Invalidating condition | Something that would make the thesis stop making sense. |
| Evidence / citation | A source offered to support a statement. Check whether it supports that specific statement. |
| Source-backed claim | A statement associated with a source in the saved analysis. Attribution is not proof that every detail is true. |
| Evidence warning | A problem with source support. Some unsupported causes may be dropped by validation. |
| Snapshot | A saved picture of inputs at a particular time. It explains an old result even when newer data arrives. |
| Provenance | Where information came from and when or how it was obtained. |

### Data and AI words

| Term | Simple explanation |
| --- | --- |
| Provider / API | A data supplier / the interface the app uses to request its information. |
| Free tier / quota / rate limit | A free plan / an allowance / how quickly requests may be made. These can limit symbols, history and data types. |
| Ingestion | Bringing external data into our database. |
| Normalization | Putting different suppliers' data into a consistent format. |
| Missing / null / N/A | No usable value is available. It is different from zero. |
| Coverage | How much required information is actually available. Financial coverage tracks usable scoring inputs. |
| Freshness / stale | How recent information is / information that may be too old for the question. |
| Fallback | A substitute rule used when the preferred input is absent. |
| Degraded | A step continued with incomplete support. It does not necessarily mean the job failed. |
| LLM | Large Language Model: the AI used to generate the explanation. |
| Prompt | Instructions and information sent to the AI. |
| Token | A unit of text processed by the AI; relevant to usage limits and cost. |
| Embedding | A numeric representation used to find text with related meaning. |
| RAG | Retrieval-Augmented Generation: find relevant stored documents and provide them to the AI before it writes. |
| Hybrid search | Combining meaning-based search with text matching. |
| Deterministic scoring | Python applies defined scoring rules. The same inputs and rules reproduce the calculation; changing data, rules or time-dependent inputs can change it. |
| Validation | Checks that results have the required structure and follow certain rules. It does not independently establish every financial fact. |

The current scoring code limits confidence to at most 95%, and to at most 50% when a financial component has no usable inputs and requires fallback. Other penalties can lower it further.

Source switches control the deep-dive narrative inputs. Disabling news or fundamentals skips their snapshot and RAG retrieval; disabling technical or macro removes those narrative sections. The deterministic scoring engine still uses its stored scoring inputs. A disabled section is an intentional omission, not a missing-data failure.

## 8. Portfolios and backtesting

A **portfolio** is a collection of investments. Portfolio calculations and backtesting are supported in the backend; the visible controls depend on the page and API.

| Term | Plain meaning |
| --- | --- |
| Position / holding | One investment in a portfolio. |
| Weight / allocation | Fraction of the portfolio assigned to an investment. A 20% weight means one fifth of portfolio value. |
| Diversification | Spreading investments so one outcome matters less. It does not eliminate losses. |
| Correlation | How much two investments tend to move together. Low correlation can help diversification. |
| Covariance | A related calculation using the size and co-movement of returns; used in portfolio math. |
| Optimization | Choosing weights according to an objective and constraints. The result depends on assumptions and inputs. |
| Sector limit / position limit | A cap on exposure to one sector / one holding. |
| Rebalancing | Adjusting holdings back to target weights. |
| Backtest | Applying strategy rules to historical data to simulate past behavior. |
| Strategy | Rules for selecting, buying, selling or weighting investments. |
| Score threshold | Include investments only when their score passes a specified cutoff. |
| Equal weight | Give each selected investment the same portfolio share. |
| Momentum strategy | Select using recent price movement. |
| Benchmark return | The reference investment's return over the comparison period. |
| Excess return | Strategy return minus benchmark return, using the same return convention. |
| Alpha | In this app's benchmark result, portfolio total return minus benchmark total return. It is not the more elaborate risk-adjusted alpha used in some finance models. |
| Beta | How strongly portfolio returns move with benchmark returns. Around 1 means similar sensitivity; estimates depend on the measured period. |
| P&L | Profit and loss: money gained or lost. Realized P&L comes from sold positions; unrealized P&L is the change in value of holdings still owned. |
| Equity curve | Portfolio value plotted through the simulation. Here “equity” means account value. |
| CAGR / annualized return | A yearly growth-rate summary across a period. It does not mean every year earned that amount. |
| Sharpe ratio | Return relative to variation in returns, after a reference risk-free return. The backtest performance calculation currently assumes a 0% risk-free rate. |
| Win rate / hit rate | Fraction of evaluated outcomes counted as successes. Read what counts as a success; this differs from confidence. |
| Transaction cost | Fees and other modeled trading expenses. |
| Slippage | Difference between an assumed price and an achievable execution price. |
| Look-ahead bias | Accidentally using information before it was available historically. That makes simulations look better than they should. |
| Pinned / frozen snapshot | Saved inputs used to make a simulation repeatable. Check which inputs are pinned; other inputs can still come from changing data. |
| Survivorship bias | Looking only at investments that still exist while excluding historical failures. |
| Overfitting | Choosing rules that match past noise and fail on new data. |

Before comparing backtests, check their dates, price coverage, benchmark, strategy rules, costs and data assumptions. An attractive historical result is not a prediction. Stored data coverage and missing historical snapshots can limit what a simulation establishes.

Automated daily snapshots save prices and scores at the first successful capture of each UTC day. Scheduler restarts and simultaneous scheduler runs reuse the existing day's capture rather than create another. Manual snapshots can still capture different times that day. Older duplicate snapshots remain available because saved backtests may reference them.

The backtest page's trade win rate counts SELL executions above the position's average cost. Breakeven is not a win, and the count is not weighted by shares or profit. One large loss can outweigh many small wins. The page describes the simulation as assuming no fees or slippage unless documented otherwise.

## 9. A simple way to read a deep dive

1. Check the company, analysis date and dates of the underlying data.
2. Read **investment score**, **risk** and **confidence** separately.
3. Check financial coverage and missing-input warnings before interpreting a score near 50.
4. Read the summary, then the bull and bear cases together.
5. Inspect the sources supporting the important claims, including their dates.
6. Read the conditions that would invalidate the thesis.
7. Compare similar businesses using comparable periods and units.

### Example

An imaginary company has an investment score of 72, risk of 65 and confidence of 45%. Its revenue grew 15%, but financial coverage is incomplete and recent news is strongly positive.

The default label is **OPPORTUNITY** because of its investment score. Risk is still substantial, and the low confidence means the supporting inputs are limited. Revenue growth says sales increased; it does not by itself establish profit growth. The next useful step is to inspect the missing finances and evidence behind the explanation.

## 10. Where these definitions come from

This guide describes the app's current implementation. Defaults can change with configuration or code updates.

- [Scoring weights and recommendation thresholds](../app/domains/stock/config.py)
- [Investment scoring, coverage and confidence](../app/domains/stock/scoring/investment_scoring.py)
- [Financial fields](../app/domains/stock/models/financial.py)
- [Technical indicators](../app/domains/stock/scoring/technical_analysis.py)
- [Risk calculations](../app/domains/stock/scoring/risk.py)
- [Portfolio calculations](../app/domains/stock/scoring/portfolio_optimizer.py)
- [Backtesting](../app/domains/stock/scoring/backtest.py)
- [How the framework analysis runs](FRAMEWORK_ANALYSIS_PATH.md)
