# The brief the selector reads

Free text is enough (`select_style.py "idea"`). A structured brief (`--brief-file brief.json`) can set any of:
```json
{ "text": "the idea or script", "audience": "kids|teens|adults|general", "platform": "reels|shorts|tiktok|youtube|square",
  "duration": 35, "moods": ["warm"], "topics": ["history"], "resources": ["gpu"], "prefer_style": "paper-atlas",
  "wants_ai_prompts": false }
```
What is read and how it is used: topic tags (keyword + rarity-weighted fit), mood, audience (hard penalty on a mismatch), story-need vs character support, length vs complexity, hardware (no GPU makes long 3D shots expensive), platform/aspect, and a preference for styles with a verified native engine. The user's explicit style choice always wins.
Ask a question only when `needs_clarification` is returned (no topic or mood recognised).
