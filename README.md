# PCL CF Relay

A minimal, self-hosted **CurseForge API relay** used by my personal [Plain Craft Launcher (PCL)](https://github.com/Meloong-Git/PCL) installation.

## Why

Since July 2026 CurseForge requires an `x-api-key` header for API and CDN access. PCL 2.13.1.1 ships a hard-coded key that has since been revoked, so CurseForge search / version lookup / file downloads fail with `403`. Instead of embedding a key into a client binary (which would leak it), this relay keeps **my own API key on my own server** and exposes the same paths the launcher expects.

## How it works

```
PCL (my PC)  ->  https://<my-domain>/  ->  Caddy (auto HTTPS)  ->  127.0.0.1:8088 (proxy.py)
                                                                    |- /curseforge/* -> api.curseforge.com   (x-api-key injected)
                                                                    |- /modrinth/*   -> api.modrinth.com
                                                                    |- /files/*      -> edge.forgecdn.net    (x-api-key injected when set)
                                                                    `- /data/*       -> cdn.modrinth.com
```

The launcher is patched (string replacement in its IL) so that `api.curseforge.com`, `api.modrinth.com`, `cdn.modrinth.com` and `edge.forgecdn.net` are rewritten to this relay's domain. No key is ever placed in the launcher.

## Security model

- `CF_API_KEY` lives only in the server-side environment file (`/opt/pcl-cf-relay/cf-relay.env`, mode 600).
- The relay listens on `127.0.0.1` only; Caddy terminates TLS.
- Per-IP rate limiting is enforced by the upstream / server (single user in practice).
- No public API is offered: the relay serves exactly one launcher installation of mine.

## Deployment (Ubuntu/Debian)

```bash
sudo mkdir -p /opt/pcl-cf-relay
sudo cp proxy.py cf-relay.env /opt/pcl-cf-relay/
sudo cp pcl-cf-relay.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now pcl-cf-relay
curl -s http://127.0.0.1:8088/__health   # {"ok":true}
```

Then point Caddy at it:

```
cf.example.com {
    reverse_proxy 127.0.0.1:8088
}
```

### Environment

| Variable | Meaning |
|---|---|
| `CF_API_KEY` | my CurseForge API key (server-side only) |
| `CF_UPSTREAMS` | ordered upstreams for `/curseforge/*` |
| `MR_UPSTREAMS` / `FILE_UPSTREAMS` / `CDN_UPSTREAMS` | Modrinth / CurseForge CDN / Modrinth CDN upstreams |
| `BIND` / `PORT` / `UPSTREAM_TIMEOUT` | listen address, port, upstream timeout |

## Compliance

- Single-user, personal use. The API key is **never** distributed, bundled or shared with other users.
- Only files that authors have published on CurseForge/Modrinth are requested, with the authors' chosen distribution settings.
- Not a public mirror service; if the key is ever misused it is rotated immediately.
- If any author or CurseForge asks, the relay is shut down.

## Status

Personal project. Provided as-is, no support.

## License

MIT for this repository's own code.
