# Tax rules (listed equity, STT paid)

Verified 2026-11-14 on incometaxindia.gov.in. Held in `config/tax.toml` with source URLs.

**Rates (Income-tax Act, 2025):**
- **s.196 STCG:** 20% (https://www.incometaxindia.gov.in/w/section-196-76)
- **s.198 LTCG:** 12.5% on gains above ₹1,25,000 a financial year (https://wm.incometaxindia.gov.in/w/section-198-78)

The rates are the same as the old s.111A/s.112A for transfers on or after 23 July 2024.

**Holding period:**
- Long-term if held **more than 12 months**. The engine treats a lot as long-term from the day after its 12-month anniversary.
- Demat lots are matched **FIFO**, per broker account. The transfer date is the contract-note date.

**What the engine shows per open lot:**
- the term if sold today and the long-term date
- the unrealised gain and the estimated tax if sold now
- a `wait_until` date when a lot turns long-term within 30 days
- the LTCG exemption left this financial year, from realised LTCG

**Not modelled:** loss set-off and carry-forward, the 31 Jan 2018 cost grandfathering, STT, surcharge and cess. Present the figures as gross estimates and suggest a CA for filing.
