# Live Player

Local livestream monitor for YouTube, Twitch, and Kick. Add channels by username, keep offline rows on the master list, sort live channels by viewer count, and launch VLC through streamlink.

Inspired by [Livestream.Monitor](https://github.com/laurencee/Livestream.Monitor) by [Laurencee](https://github.com/laurencee). This is an independent rewrite for a locally hosted web UI.

## Run

```bash
docker compose up -d --build
```

UI: http://192.168.50.49:8112

Play starts `streamlink` in the container and hands VLC an `.m3u` playlist on the LAN (`8888-8897`).

## Tests

```bash
docker compose run --rm --no-deps live-player pytest
```

Optional Twitch Helix credentials: `TWITCH_CLIENT_ID` and `TWITCH_CLIENT_SECRET`.
