# Setting API keys for model providers

1) Create a local `.env` from the example:

```bash
cp .env.example .env
# then edit .env to add your keys
```

2) Export for current shell (or add to `~/.zshrc`):

```bash
export ANTHROPIC_API_KEY="sk-..."
export OPENAI_API_KEY="sk-..."
```

3) Quick test (redacted keys are used from env):

```bash
# Anthropic
curl -s -o /dev/null -w "%{http_code}\n" -H "x-api-key: $ANTHROPIC_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"claude-2.1","prompt":"hi","max_tokens_to_sample":1}' \
  https://api.anthropic.com/v1/complete

# OpenAI
curl -s -o /dev/null -w "%{http_code}\n" -H "Authorization: Bearer $OPENAI_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"hi"}]}' \
  https://api.openai.com/v1/chat/completions
```

4) Useful tips
- Don't commit `.env` to Git. Add `.env` to `.gitignore` if not present.
- Some CLIs offer `login` or `configure` commands (e.g. `openclaw login`).
- If requests return `401`, check keys for typos or expiration.
