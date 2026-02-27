# Crypto-Tax-Optimizer — Public Demo

## Deployment
- GitHub: `jon-m-normile/Crypto-Tax-Optimizer` (branch: `main`)
- Deployed on Render as `crypto-tax-optimizer` at `https://crypto-tax-optimizer.onrender.com`.
- Render free tier. Auto-deploys from `main`.
- Previously had a separate `render-deploy` branch — this was merged into `main` and the branch is now redundant.

## Purpose
Public-facing Streamlit demo embedded in `demo.html` on `freedomfromfiat.com`. No password required. Shows how the Tax Optimization Algorithm selects lots to minimize capital gains.

## Tab Structure (intentional)
| Tab | Shown |
|---|---|
| Purchase | Yes |
| Portfolio | Yes |
| History | Yes |
| Tax Calculation | Yes |
| Tax Waterfall | **No — Plus only** |
| Comparison | **No — Plus only** |

The Tax Waterfall tab exists in the codebase (`render_tax_waterfall_status()`) but is **intentionally not included** in the `st.tabs()` call in `main()`. Do not add it back. It is a differentiating feature of the Plus version.

## Key Architecture
- Single-file Streamlit app: `app.py`.
- Engines: `engines/lot_selection_engine.py`, `engines/tax_calculation_engine.py`.
- Models: `models/data_models.py`.
- Sample data loaded via sidebar; users can also upload their own CSV.

## What's Different from Plus
- No Tax Waterfall tab
- No Comparison tab
- No live Mercury/Kraken integration
- No password protection
