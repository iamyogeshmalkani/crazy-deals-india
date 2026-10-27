# India Deals Telegram Channel: Development Plan

Goal: an automated Telegram deals channel for Indian shoppers (Amazon.in, Flipkart, Myntra, Ajio, etc.) that earns affiliate commission on every tracked purchase, with messages that create *genuine* urgency (FOMO), at ₹0 infrastructure cost.

---

## 1. Principles

1. **Real FOMO only.** Urgency is built from verifiable facts (price vs. 90-day low, coupon expiry, stock signals from the source, bank-offer end time). Fake countdowns, invented "only 2 left", or recycled "loot" claims are out. Reasons:
   - India's CCPA *Guidelines for Prevention and Regulation of Dark Patterns, 2023* list false urgency and drip pricing as dark patterns.
   - ASCI guidelines require clear disclosure of affiliate relationships.
   - Amazon Associates and Flipkart can close accounts for misleading content.
   - Fake FOMO burns trust, and trust is the channel's only asset.
2. **Every outbound link is an affiliate link.** No exceptions, enforced in code (the publisher refuses untagged URLs).
3. **Free to build, free to run.** Free tiers only. Verify limits on official pages before depending on them.
4. **Quality over volume.** 25-40 curated posts a day beats 200 spammy ones.

---

## 2. India-specific requirements

| Area | Decision |
|---|---|
| Currency | Show ₹ with Indian digit grouping (₹1,49,999, not ₹149,999). Use `Intl.NumberFormat('en-IN')` or Python `babel`. |
| Language | Hinglish by default (e.g. "Loot lo", "Price gir gaya"), with an English-only option. Hindi/regional channels later. |
| Time | Everything scheduled and displayed in IST. Peak windows: 8-10 am, 12-2 pm, 8-11 pm. Quiet hours 12-7 am (no posting). |
| Sale calendar | Maintain a calendar: Amazon Great Indian Festival, Flipkart Big Billion Days, Diwali, Republic Day, Independence Day, End of Reason Sale, Myntra EORS, Prime Day. Raise cadence during sales. |
| Offers | Parse and show bank/card offers (HDFC, ICICI, SBI, Axis), UPI cashback, and no-cost EMI, since these drive Indian purchase decisions. |
| Categories | Mobiles, electronics, fashion, grocery, home & kitchen, beauty, books. Tag each post so users can follow categories. |
| Disclosure | Pinned message and a footer on every post: "Affiliate links: we may earn a commission at no extra cost to you. Prices can change." |
| Data privacy | The price-alert bot stores Telegram user IDs and watch lists. Collect the minimum, state it in `/privacy`, and support `/deleteme` (DPDP Act 2023). |
| Tax | Affiliate income is taxable. Get a PAN-linked payout setup with the networks, and ask a CA about GST (turnover threshold) and TDS. |

---

## 3. Architecture

```
GitHub Actions cron (public repo, secrets in Actions secrets)
        │
        ├─ collectors/   amazon_in, flipkart, cuelinks_feed, rss_deals
        │       ↓
        ├─ normalize → products + price_history (Postgres)
        │       ↓
        ├─ scorer      (real-deal rules)
        │       ↓
        ├─ composer    (FOMO message engine, Hinglish templates)
        │       ↓
        └─ publisher   (Telegram Bot API, rate-limited queue)

Cloudflare Worker (webhook only)  ← Telegram → price-alert bot commands
```

### Stack (recommended)

- **Python 3.12** for collectors, scorer, composer, publisher (`httpx`, `aiogram` or plain Bot API calls, `psycopg`).
- **Postgres** on Supabase or Neon free tier.
- **GitHub Actions cron** as the scheduler. Cron has a 5-minute minimum interval and is not exact, which is fine here. Use a public repo so run minutes are not capped. Secrets never go in the repo.
- **Cloudflare Worker** only for the Telegram webhook (price-alert bot), because it must respond instantly.
- **Why not a Worker for everything:** the free plan limits CPU time per request and subrequests per invocation, which is tight for feed parsing across many stores. I suggested Workers earlier. This split is more reliable.

### Data model (core tables)

- `products(id, store, store_product_id, title, url, image, category, first_seen)`
- `price_history(product_id, price, mrp, coupon, bank_offer, fetched_at)`
- `deals(id, product_id, score, reasons[], status, posted_at, message_id)`
- `posts(id, deal_id, channel, tg_message_id, sent_at, clicks)`
- `watches(user_id, product_id, target_price, created_at)` for the alert bot
- `affiliate_links(product_id, network, short_url)`

---

## 4. Deal scoring (what earns a post)

A deal posts only if it passes all gates:

1. Current price is within 5% of the 90-day low, or at least 25% below the 30-day median.
2. The stated MRP is not inflated: the discount is computed against our own price history, not the listed MRP.
3. Not posted in the last 7 days unless the price dropped a further 10%.
4. The category daily cap is not exceeded.
5. In stock and the listing is live.

Score = discount vs. history + price-drop size + category demand + offer stack (coupon + bank offer). Top scorers go out first.

---

## 5. FOMO message engine

Urgency comes from real signals. Each post picks the strongest available:

| Signal (real) | Example line |
|---|---|
| Lowest price in 90 days | "📉 90 din ka sabse kam daam!" |
| Price dropped vs. yesterday | "₹4,000 gir gaya, kal ₹24,999 tha" |
| Coupon or offer end time from the source | "⏰ Coupon aaj raat 11:59 tak" |
| Stock signal reported by the source | "⚠️ Sirf kuch pieces bache" (only if the source says so) |
| Bank offer window | "HDFC card pe extra ₹1,500 off, sale tak" |
| Social proof from our own data | "🔥 Pichhle 1 ghante me 312 logon ne dekha" (our own click counter, real) |
| Deal age | "Posted 12 min ago" and auto-edit to "⌛ Price may have changed" later |

### Template

```
🔥 LOOT DEAL | {category}

{title_short}

💰 ₹{price} ~~₹{mrp}~~  ({discount}% off)
📉 {history_line}
🏦 {bank_offer}
⏰ {urgency_line}

👉 {short_affiliate_link}

⚠️ Affiliate link. Price at time of posting; may change.
```

Rules:
- Max 1 urgency line, and it must come from data.
- Emoji budget: 4-6 per post.
- Inline button "Buy Now" (affiliate link) plus "🔔 Alert me" (opens the price-alert bot).
- Auto-edit the post when a deal expires: "❌ Deal ended". This protects trust and gives real FOMO on the next post ("last deal ended in 38 min").
- A/B test hooks, not facts: test emoji and phrasing, track clicks per variant.

---

## 6. Phases

### Phase 0: Setup (2-3 days)
- Create the Telegram channel and bot (@BotFather). Make the bot admin.
- Apply: Amazon Associates India, Flipkart Affiliate, and one network (EarnKaro or Cuelinks). Apply early; approval can take days.
- Create the GitHub repo, Supabase/Neon project, and secrets.
- Write the disclosure and pin it.
- **Done when:** the bot posts a hard-coded message to the channel.

### Phase 1: Manual-assisted MVP (week 1)
- Collector for the affiliate network's deal/coupon feed and the Flipkart Offers API.
- Normalizer + `price_history` storing from day one.
- Link tagger and the composer with 3 templates.
- Review queue: candidate deals go to a private chat with Approve/Reject buttons.
- **Done when:** 10-15 approved posts a day go out with working affiliate links.

### Phase 2: Automation and scoring (week 2-3)
- Scorer with the gates in section 4.
- Amazon collector via the Creators API once the Associates account is approved. Until then, ASIN-based links with `tag=` and network feeds.
- Rate-limited publisher queue with retry.
- Auto-expire and edit posts. Click tracking via redirect (a free Cloudflare Worker short link, ours so we own the data).
- Auto-approve high-score deals; keep manual review for the rest.
- **Done when:** the channel runs unattended for 3 days.

### Phase 3: Growth and the price-alert bot (week 4-6)
- Cloudflare Worker webhook with `/watch <link>`, `/list`, `/stop`, `/deleteme`.
- Daily price check for watched products; alert with affiliate link when the target is hit.
- Cross-post to WhatsApp Channel and Instagram. Add category sub-channels.
- Sale-calendar mode: higher cadence and a pre-sale "wishlist" teaser post.
- **Done when:** price-alert bot has users and generates measurable clicks.

### Phase 4: Monetize beyond affiliate (month 2+)
- Telegram ad revenue share (check eligibility and India support).
- Sponsored posts (labelled).
- Premium early-access tier via Telegram Stars.
- Additional affiliates (travel, recharge/bill pay). Avoid investment and trading referrals (SEBI risk).

---

## 7. Metrics

| Metric | Why |
|---|---|
| Subscribers, daily growth | Audience |
| Views per post / subscribers | Engagement, spam signal |
| Clicks per post, CTR | Deal quality and copy |
| Orders, earnings per click (from network reports) | The real result |
| Post-to-order lag | Tunes the posting schedule |
| Unsubscribes per day | Over-posting signal |
| Deal-expired rate | Price accuracy |

Rule: if unsubscribes rise after a cadence increase, cut the volume.

---

## 8. Risks

| Risk | Mitigation |
|---|---|
| Associates account closure | Follow the operating agreement; disclosure; no stale prices; keep 3 qualifying sales inside the window (verify the India rule) |
| API changes (Amazon PA-API → Creators API; Flipkart APIs are in beta) | Collector interface isolates each source; one module to replace |
| Telegram rate limits | Queue; ~20 messages/min per channel |
| Free-tier changes | Keep logic portable (plain Postgres, plain Python); export data weekly |
| Low initial traffic | Early growth is manual: share in communities, collaborate with other channels, post consistently |
| Misleading-claim complaints | Real-data FOMO only; log the reason behind every urgency line |

---

## 9. Open decisions

1. Python on GitHub Actions (recommended) or all-TypeScript on Cloudflare?
2. Hinglish only, or English as well, at launch?
3. Which affiliate network first: EarnKaro (low payout limit, beginner-friendly) or Cuelinks?
4. Categories to start with (suggest: mobiles, electronics, fashion).
5. Approve-first review queue in Phase 1, or fully automatic from the start?
