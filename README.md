# ECHO partners by HIP

Dashboard of who DG ECHO funds under each Humanitarian Implementation Plan (HIP) over the last three years, and which partners are funded consistently. Prepared for CALP Network.

- **Live page:** GitHub Pages (Settings → Pages).
- **Data:** ECHO's IATI publication via [d-portal.org](https://d-portal.org) (grants, partners, sector tags) and DG ECHO's HIP pages (budgets).
- **Refresh:** `.github/workflows/refresh.yml` runs `scripts/refresh.py` on the 3rd of each month and commits updated files in `data/`. Run it by hand from the **Actions** tab → *Refresh ECHO data* → *Run workflow*.

Caveats: ECHO publishes commitments only, with a lag of months; coverage of HIP budgets varies widely; sub-grantees aren't published; there is no cash/MPC sector tag.
