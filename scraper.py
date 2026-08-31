#!/usr/bin/env python3
"""Notify Slack when a new one-of-a-kind F155 CLAPTON goes live on freitag.ch.

Every FREITAG bag is a unique piece with its own SKU, so "new bag" means "a SKU we
haven't seen before appears in the page's in-stock list".
"""

import gzip
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

PRODUCT_URL = "https://freitag.ch/en_DE/products/f155-clapton"
SITE_ROOT = "https://freitag.ch/en_DE"
STATE_FILE = Path(__file__).resolve().parent / "state" / "seen.json"
TIMEOUT = 30
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S
)


def die(message):
    """Abort without touching state, so the next run can retry cleanly."""
    print(f"error: {message}", file=sys.stderr)
    sys.exit(1)


def fetch_html():
    request = urllib.request.Request(
        PRODUCT_URL,
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Encoding": "gzip",
            "Accept-Language": "en",
        },
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        body = response.read()
        if response.headers.get("Content-Encoding") == "gzip":
            body = gzip.decompress(body)
    return body.decode("utf-8", "replace")


def format_price(price):
    if not price:
        return ""
    amount = price["centAmount"] / (10 ** price.get("fractionDigits", 2))
    return f"{amount:,.2f} {price['currencyCode']}"


def clean_color(color):
    """'310 königsblau' -> 'königsblau' (the number is an internal colour code)."""
    if not color:
        return None
    parts = color.split(maxsplit=1)
    return parts[1] if len(parts) == 2 and parts[0].isdigit() else color


def parse_bags(html):
    match = NEXT_DATA_RE.search(html)
    if not match:
        die("__NEXT_DATA__ blob not found — page structure changed")
    try:
        sources = json.loads(match.group(1))["props"]["pageProps"]["data"]["data"][
            "dataSources"
        ]
    except (json.JSONDecodeError, KeyError) as exc:
        die(f"could not read dataSources from __NEXT_DATA__: {exc}")
    variants = next(
        (source["allVariants"] for source in sources.values() if "allVariants" in source),
        None,
    )
    if variants is None:
        die("no all-variants data source on the page — page structure changed")

    bags = []
    for product in variants:
        variant = product["variants"][0]
        if not variant.get("isOnStock"):
            continue
        attributes = variant.get("attributes", {})
        images = variant.get("images") or []
        bags.append(
            {
                "sku": product["productId"],
                "name": attributes.get("model-full-name") or product.get("name", "F155"),
                "color": clean_color(attributes.get("ai-main-color-1")),
                "price": format_price(variant.get("price")),
                "url": SITE_ROOT + product["_url"],
                "image": images[0] if images else None,
            }
        )
    return bags


def load_seen():
    if not STATE_FILE.exists():
        return None
    return set(json.loads(STATE_FILE.read_text()))


def save_seen(skus):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(sorted(skus), indent=1) + "\n")


def describe(bag):
    return " — ".join(part for part in (bag["name"], bag["color"]) if part)


def notify(webhook_url, bag):
    """POST to a Slack Workflow Builder webhook trigger.

    The keys below must match the variables declared on the trigger exactly — Slack
    rejects the request if any are missing or unexpected. Formatting lives in the
    workflow's "Send a message" step, not here.
    """
    payload = json.dumps(
        {
            "title": describe(bag),
            "price": bag["price"],
            "url": bag["url"],
            "image": bag["image"] or "",
        }
    ).encode()
    request = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            body = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Slack returned HTTP {exc.code}: {exc.read()[:200]!r}") from exc
    # Slack answers 200 with {"ok": false, "error": ...} for a bad payload, so a
    # silent rejection would otherwise look like a delivered notification.
    if '"ok":false' in body.replace(" ", ""):
        raise RuntimeError(f"Slack rejected the payload: {body[:200]}")


def main():
    dry_run = "--dry-run" in sys.argv[1:]
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook_url and not dry_run:
        die("SLACK_WEBHOOK_URL is not set")

    try:
        html = fetch_html()
    except (urllib.error.URLError, OSError) as exc:
        die(f"could not fetch {PRODUCT_URL}: {exc}")

    bags = parse_bags(html)
    if not bags:
        die("page parsed but listed no in-stock bags — refusing to update state")
    print(f"{len(bags)} F155 CLAPTON in stock")

    seen = load_seen()
    if dry_run:
        for bag in bags:
            flag = "NEW" if seen is not None and bag["sku"] not in seen else "   "
            print(f"  {flag} {bag['sku']}  {bag['price']:>12}  {describe(bag)}")
            print(f"       {bag['url']}")
        return

    if seen is None:
        save_seen(bag["sku"] for bag in bags)
        print(f"first run: seeded state with {len(bags)} SKUs, sent no notifications")
        return

    new_bags = [bag for bag in bags if bag["sku"] not in seen]
    for bag in new_bags:
        try:
            notify(webhook_url, bag)
        except (RuntimeError, urllib.error.URLError, OSError) as exc:
            # Leave state untouched so this bag is retried on the next run.
            die(f"could not notify about {bag['sku']}: {exc}")
        print(f"notified: {bag['sku']} {describe(bag)}")

    save_seen(seen | {bag["sku"] for bag in bags})
    print(f"{len(new_bags)} new" if new_bags else "nothing new")


if __name__ == "__main__":
    main()
