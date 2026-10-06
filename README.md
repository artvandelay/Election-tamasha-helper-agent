# Election Tamasha rules helper

English helper for the Election Tamasha table. It answers from the June 2026 instruction manual, and it can take the current game position with the question.

The rulebook is `static/rules.html`. The chat is a small Python server that calls [OpenRouter](https://openrouter.ai/) with `~deepseek/deepseek-flash-latest`, which follows the current DeepSeek Flash model.

The OpenRouter key stays in `.env`. That file is gitignored. Nothing in this repo can spend the key by itself.

## Run

```bash
cp .env.example .env
# put OPENROUTER_API_KEY in .env

python3 server.py
```

Open http://127.0.0.1:8787

The rules page is http://127.0.0.1:8787/rules

## Ask from another program

`POST /api/chat`

```json
{
  "message": "Can I buy a winning Clean candidate?",
  "position": {
    "version": "basic",
    "phase": "horse-trading",
    "side": "yellow",
    "constituency": "",
    "notes": "Yellow CPF is 11 Cr."
  },
  "history": []
}
```

The answer is `{ "answer": "...", "model": "..." }`.

A WhatsApp webhook can call this same endpoint later. It is not connected yet. If you put the server on a public URL, set `CHAT_SECRET` and send `Authorization: Bearer <CHAT_SECRET>`. Without that secret, anyone who can reach the port can spend the OpenRouter key.

## What it will not know

Vote prices printed on a specific Campaign, Big Campaign, PartyKundali, Breaking News, Attack, or Victim card are not in the manual. The helper is supposed to say that, instead of guessing.
