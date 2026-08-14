# options-desk clock (Cloudflare Worker)

Fires GitHub `workflow_dispatch` at **09:15 ET** (premarket prelayer), **09:30 ET** (RTH live chains), and **16:30 ET** (overnight) on weekdays. Does not call Finviz. Does not send `force`.

## Secrets

```bash
cd infra/cloudflare-clock
npx wrangler secret put GH_TOKEN    # fine-grained PAT: Actions write on denysyarin/options-desk
npx wrangler secret put GH_OWNER    # denysyarin
npx wrangler secret put GH_REPO     # options-desk
npx wrangler deploy
```

Cron is `*/15 * * * *`. The handler no-ops unless the America/New_York wall clock is exactly 09:15, 09:30, or 16:30 on a weekday.

Spare clock: [cron-job.org](https://cron-job.org) POSTing the same GitHub dispatch URL with that PAT.

Manual: Actions → premarket, rth, or overnight → Run workflow → `force` if you missed the window.
