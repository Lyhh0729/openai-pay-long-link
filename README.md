# OpenAI PayPal Link Extractor

Standalone local tool for extracting a PayPal redirect link from a ChatGPT access token.

## Run

```powershell
cd openai_pay_long_link
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app:app --host 127.0.0.1 --port 8787
```

Open:

```text
http://127.0.0.1:8787
```

## Docker

```bash
cd openai_pay_long_link
docker compose up -d --build
```

Open:

```text
http://127.0.0.1:8787
```

Stop:

```bash
docker compose down
```

The server does not ship with a built-in outbound proxy. Fill in the JP proxy
and US/DE provider proxy fields in the page before running.

For normal PP extraction:

```text
checkout stage: JP proxy
provider stage: US or DE proxy, matching the selected region
approve stage: JP proxy
random billing profile: US or DE, matching the selected region
```

Before generation, the server checks proxy connectivity and verifies the
observed outlet country.

## API

```http
POST /api/long-link
Content-Type: application/json

{
  "accessToken": "eyJ...",
  "jp_proxy": "http://user:pass@jp-host:port",
  "us_proxy": "http://user:pass@provider-host:port",
  "billing_country": "US",
  "payment_locale": "en",
  "stripe_publishable_key": ""
}
```

The server creates a ChatGPT checkout, calls:

```text
https://api.stripe.com/v1/payment_pages/{cs_id}/init
```

Then it reads `stripe_hosted_url` and changes:

```text
https://checkout.stripe.com -> https://pay.openai.com
```

## Streaming Logs

The UI uses:

```http
POST /api/long-link/stream
```

The endpoint returns newline-delimited JSON log events while the task is
running, followed by the final result event.
