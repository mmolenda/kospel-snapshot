# kospel-snapshot (Docker)

This stack runs two containers:

- `fetcher` polls `ha.kospel.pl`, writes:
  - `/data/kospel-YYYYMM.csv` (history)
  - `/data/radek/kospel.json` (latest snapshot)
- `caddy` serves `/data` on port `40520` with HTTP basic auth.

## 1) Prepare host directory

```bash
mkdir -p /root/kospel-snapshot/data
```

## 2) Configure secrets

Create `.env` based on `.env.example`:

```bash
cp .env.example .env
```

Set:

- `KOSPEL_USERNAME`
- `KOSPEL_PASSWORD`
- `CADDY_USER`
- `CADDY_PASSWORD_HASH`

Generate bcrypt hash:

```bash
docker run --rm caddy:2.8-alpine caddy hash-password --plaintext 'your-password'
```

## 3) Start

```bash
docker compose up -d --build
```

The HTTP endpoint is exposed on `:40520`.

## Runtime behavior

- Polling config is in `config/settings.example.toml`.
- Image build copies it to `/app/config/settings.toml`.
- Fetcher loop runs immediately on container start, then sleeps `seconds` (default `120`) between runs.
- `verify_tls` defaults to `false` to match previous script behavior. Set it to `true` if your host can validate the remote certificate chain.
- Output format is unchanged:
  - CSV delimiter is `;`
  - decimal separator in CSV is `,`
  - JSON contains the same keys and `UPDATED`.
