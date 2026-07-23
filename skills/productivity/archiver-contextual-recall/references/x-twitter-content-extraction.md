# X/Twitter Content Extraction Fallback

When primary extraction fails, use `fxtwitter.com` as a fallback parser:

1. Try your normal HTTP reader first.
2. If blocked/403, request the `fxtwitter` API endpoint:

```bash
curl -sL -A "Mozilla/5.0" \
  "https://api.fxtwitter.com/<username>/status/<tweet_id>"
```

Replace placeholders from the source URL:

- Input: `https://x.com/<username>/status/<tweet_id>`
- API: `https://api.fxtwitter.com/<username>/status/<tweet_id>`

Persist fallback results only through the official intake command:

```bash
python3 .../archive_item.py \
  --title "Recovered X/Twitter content" \
  --source "https://x.com/<username>/status/<tweet_id>" \
  --body "<text from fxtwitter article/content>" \
  --json
```

Do not write markdown notes manually from this fallback path; route all recovered content through the official intake workflow.
