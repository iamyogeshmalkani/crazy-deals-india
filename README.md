# dealbot: India deals channel for Telegram

Collects deals, keeps its own price history, scores what is a *real* deal, sends
candidates to a private review chat, and posts approved ones to your channel with
your affiliate links. Phase 0 + 1 of [PLAN.md](PLAN.md).

## Try it now (no accounts needed)

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt pytest
PYTHONPATH=src .venv/bin/python -m dealbot demo   # full flow on sample data, prints the messages
.venv/bin/python -m pytest                        # 45 tests
```

## How a run works (every 15 min via GitHub Actions)

1. **Review taps**: reads Approve/Reject taps from the review chat (only `TELEGRAM_REVIEWER_IDS` count).
2. **Collect**: Flipkart Offers API, RSS feeds, and `MANUAL_DEALS_FILE`.
3. **Tag + score**: affiliate-tags every link (foreign tags are stripped), stores price history, applies the deal rules.
4. **Queue**: top candidates go to the review chat as a preview card.
5. **Publish**: approved deals go to the channel, within quiet hours / daily / per-run caps. A link that is not ours is never posted.
6. **Expire**: posts whose offer ended are edited to "DEAL KHATAM".

## What counts as a deal, and how urgency is written

- With ≥6 price points over ≥3 days of history, a deal must be within 5% of the lowest price we have tracked **and** ≥5% below the 30-day median, or ≥25% below the median. A product that is always the same price is rejected even if its MRP is inflated.
- Without enough history, the deal is **unverified**: it needs ≥35% off the listed MRP, is labelled so in the review card, and never gets a "lowest price" claim.
- "Lowest price in N days" uses the real number of days tracked, never a fixed "90".
- Urgency lines come only from data: an offer expiry within 48 h, or a real drop from the price recorded about a day earlier. No data means no urgency line.

## Setup (≈30 min, all free)

1. **Bot + channel**: create a bot with @BotFather, create a public channel, add the bot as an admin with permission to post.
2. **IDs**: message your bot once from your account. Your user id is `message.from.id` in `https://api.telegram.org/bot<TOKEN>/getUpdates`. Use it for `TELEGRAM_REVIEW_CHAT_ID` and `TELEGRAM_REVIEWER_IDS`.
3. **Database**: create a free Supabase or Neon project and copy the connection string into `DATABASE_URL`. Tables are created automatically.
4. **Affiliate identities** (apply early, approval takes days):
   - Amazon Associates India → `AMAZON_TAG`
   - Flipkart Affiliate → `FLIPKART_AFFID` + `FLIPKART_TOKEN` (turns on the offers collector)
   - EarnKaro or Cuelinks for Myntra/Ajio/etc. → `AFFILIATE_WRAP_JSON`, with the deep-link format from their dashboard and `{url}` where the product link goes
5. **Local check**: `cp .env.example .env`, fill it in, run `python -m dealbot check`, then `DRY_RUN=1 python -m dealbot run`.
6. **Deploy**: push to a **public** GitHub repo (unlimited free Actions minutes; secrets stay private), add the values from `.env.example` as repository secrets, and enable the workflow. If you use a private repo, lengthen the cron interval to stay inside the free minutes.

Before posting for real, pin a channel message with your affiliate disclosure and read the Amazon Associates operating agreement (price display rules, link rules).

## Hand-picked deals (works before any API is approved)

Point `MANUAL_DEALS_FILE` at a JSON file in the format of `data/sample_deals.json` (url, price, mrp, optional coupon/bank_offer/expiry). Items run through the same history, scoring, review, and tagging.

## Known limits

- **No Amazon collector yet.** Amazon is retiring its old product API in favour of the Creators API, and I could not confirm India eligibility or the response format. Until then Amazon deals arrive through manual items or RSS, with correct `tag=` links. The collector interface is in `collectors/base.py`.
- **Flipkart Offers returns offers, not prices.** They are posted as "OFFER ALERT" with the real expiry. The Flipkart API is documented as beta.
- **Not tested against live APIs.** The Telegram, Flipkart, and RSS code is tested against mocked responses and Telegram dry-run only. Run `DRY_RUN=1` first, then post to a private test channel.
- **Price deals with no expiry are not auto-ended**: they stay up until you delete them. Price re-checking is a Phase 2 item.
- **Click counts / "N people viewed"** are not built yet (needs the Phase 2 redirect), so no social-proof lines are generated.
- GitHub pauses scheduled workflows in repos with no activity for a while; re-enable from the Actions tab if the channel goes quiet.
