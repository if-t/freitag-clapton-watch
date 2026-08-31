# F155 CLAPTON watch

Every FREITAG bag is a unique piece, so the
[F155 CLAPTON page](https://freitag.ch/en_DE/products/f155-clapton) lists dozens of
individual backpacks that each have their own SKU and tarp pattern — and the good ones sell
out. This checks that page every 5 minutes and sends a Slack message with a direct link
whenever a bag appears that it hasn't seen before.

## How it works

The page is server-rendered Next.js, so no browser or HTML scraping is needed: the script
pulls the `__NEXT_DATA__` JSON blob out of the page and reads the in-stock variant list
straight from it (SKU, price, colour, image, URL). Sold-out pieces are absent from that
list, so "a SKU we haven't seen before" is a reliable definition of "a new bag is live".

Seen SKUs live in `state/seen.json`, which the GitHub Actions workflow commits back to the
repo after each change. Requests are gzipped (164 KB instead of 901 KB) to keep the
5-minute polling light on freitag.ch.

Python 3.12, standard library only — no dependencies.

## Setup

1. **Create a Slack Incoming Webhook** at <https://api.slack.com/apps> → your app →
   *Incoming Webhooks* → *Add New Webhook to Workspace* → pick the channel or your own DM.
   Copy the `https://hooks.slack.com/services/...` URL.

2. **Add it as a repo secret** so the workflow can use it:

   ```sh
   gh secret set SLACK_WEBHOOK_URL   # paste the URL when prompted
   ```

3. That's it — the workflow runs on its own every 5 minutes. Trigger it by hand with:

   ```sh
   gh workflow run check.yml
   ```

The webhook URL is only ever read from the `SLACK_WEBHOOK_URL` environment variable. Don't
commit it.

## Running locally

```sh
# See what's in stock right now. Posts nothing, writes no state.
uv run python scraper.py --dry-run

# A real check: notifies about anything new, then updates state/seen.json.
SLACK_WEBHOOK_URL='https://hooks.slack.com/services/...' uv run python scraper.py
```

Use `uv run` rather than a bare `python3`: a python.org framework install often has no CA
certificates until you run its `Install Certificates.command`, and the fetch fails with
`CERTIFICATE_VERIFY_FAILED`.

`state/seen.json` is committed pre-seeded with the 49 bags that were live when this was
built, so the first run is quiet instead of announcing all of them.

- **Start over** (next run re-seeds silently, no notifications): `rm state/seen.json`
- **Force one test notification**: delete any single SKU from `state/seen.json` and run the
  script — that bag gets announced again.

## Failure behaviour

If the fetch fails, the `__NEXT_DATA__` blob can't be parsed, or the page yields zero
in-stock bags, the script exits non-zero and **leaves `state/seen.json` untouched**. That
matters: writing an empty state would make the next successful run announce every bag on
the page at once. A red workflow run therefore means "the site changed or was unreachable",
and no notifications are lost.
