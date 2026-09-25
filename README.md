# Live Player

Local livestream monitor for YouTube, Twitch, and Kick. Add channels by username, keep offline rows on the master list, sort live channels by viewer count, and launch VLC through streamlink.

Inspired by [Livestream.Monitor](https://github.com/laurencee/Livestream.Monitor) by [Laurencee](https://github.com/laurencee). This is an independent rewrite for a locally hosted web UI.

## Run

```bash
docker compose up -d --build
```

UI: http://localhost:8112

Play starts `streamlink` in the container and hands VLC a stream on ports `8888-8897`. For access from other machines on your LAN, set `PUBLIC_HOST` in a local `.env` file (see `.env.example`).

## VLC one-click Play

Install the `liveplayer:` protocol handler once on each machine that should open streams in VLC. Setup page: http://localhost:8112/static/vlc-setup.html

- **Windows (PowerShell):** `powershell -ExecutionPolicy Bypass -Command "irm http://localhost:8112/static/install-vlc-handler.ps1 | iex"`
- **macOS / Linux:** `curl -fsSL http://localhost:8112/static/install-vlc-handler.sh | bash`

Then fully quit Chrome and click Play again. Replace `localhost:8112` with your Live Player host if needed.

## Tests

```bash
docker compose run --rm --no-deps live-player pytest
```

Optional Twitch Helix credentials: `TWITCH_CLIENT_ID` and `TWITCH_CLIENT_SECRET`.
