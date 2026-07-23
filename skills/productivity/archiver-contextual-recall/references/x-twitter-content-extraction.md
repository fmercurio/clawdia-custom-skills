# X/Twitter Content Extraction Fallback

When extracting content from X/Twitter URLs and the primary methods fail, use the fxtwitter.com API as a reliable fallback.

## Fallback chain

1. **xurl CLI** (`xurl read <URL>`) — preferred, but requires OAuth2 apps registered. If `xurl auth status` shows "No apps registered", skip.
2. **Web readers** (zai, etc.) — often return 403/forbidden for x.com URLs.
3. **fxtwitter.com API** — works without auth, returns full structured JSON.

## fxtwitter API usage

```bash
curl -sL -A "Mozilla/5.0" \
  "https://api.fxtwitter.com/<username>/status/<tweet_id>" 
```

Replace `<username>` and `<tweet_id>` from the original URL:
- Input: `https://x.com/elvissun/status/2065035615800864954`
- API: `https://api.fxtwitter.com/elvissun/status/2065035615800864954`

Returns JSON with:
- `tweet.text` — plain text (may be empty for article-only tweets)
- `tweet.author` — screen_name, name, followers, description
- `tweet.article` — full X Article content when present:
  - `article.title` — article headline
  - `article.preview_text` — first ~2 lines
  - `article.content.blocks[]` — structured content blocks with:
    - `text` — the actual text
    - `type` — "unstyled", "header-two", "ordered-list-item", "unordered-list-item", "blockquote", "atomic"
    - `inlineStyleRanges[]` — bold, italic offsets
    - `entityRanges[]` — links, embedded tweets, media references
  - `article.content.entityMap[]` — resolved entities (links, embedded tweets, media)
- `tweet.media_entities[]` — images with URLs
- `tweet.created_at`, `tweet.likes`, `tweet.bookmarks`, `tweet.views` — engagement metrics

## X Article block types

| type | Meaning |
|------|---------|
| `unstyled` | Regular paragraph |
| `header-two` | Section heading (h2) |
| `ordered-list-item` | Numbered list item |
| `unordered-list-item` | Bullet list item |
| `blockquote` | Blockquote |
| `atomic` | Embedded media/tweet (details in entityMap) |

## Converting blocks to markdown

```python
import json

def blocks_to_markdown(article_data):
    blocks = article_data["content"]["blocks"]
    entities = article_data["content"].get("entityMap", [])
    
    lines = []
    for block in blocks:
        text = block["text"]
        
        if block["type"] == "header-two":
            lines.append(f"\n## {text}\n")
        elif block["type"] == "unordered-list-item":
            lines.append(f"- {text}")
        elif block["type"] == "ordered-list-item":
            lines.append(f"1. {text}")
        elif block["type"] == "blockquote":
            lines.append(f"> {text}")
        elif block["type"] == "atomic":
            # Embedded media/tweet — check entityMap
            pass
        else:
            lines.append(text)
    
    return "\n\n".join(lines)
```

## Limitations

- No authentication required, but rate limits may apply for heavy use.
- Thread/conversation context requires fetching each tweet separately.
- Some media entities may not resolve (atomic blocks with missing entityMap entries).
- The `raw_text` field may differ from `article.content` — always prefer the article blocks for long-form content.

## Use in archiver pipeline

When `archive_item.py` extraction fails on x.com URLs (blocked/403), the fxtwitter API can be called manually to get the content, then passed as `--body` or written directly as a markdown note in the Archiver vault or Second Brain.
