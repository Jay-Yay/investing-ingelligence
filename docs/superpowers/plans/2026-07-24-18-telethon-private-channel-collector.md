# Telethon Private-Channel Telegram Collector Implementation Plan

**Goal:** `TelegramCollector` only reads the public web preview (`t.me/s/{channel}`) — private
channels aren't visible there at all, only a real authenticated Telegram user session can read
them. This phase adds a second collector, `TelethonPrivateChannelCollector`, using Telethon
(MTProto) to read messages the user is actually a member of, activating only when
`TELEGRAM_API_ID`/`TELEGRAM_API_HASH`/`TELEGRAM_SESSION` are all configured — `AppSettings`
already had these three fields since Core Foundation, unused until now.

**This phase has a real, honest limit that every other collector in this project didn't have:**
every prior collector (Naver, Telegram public preview, SEC, DART, essays) was built and verified
against a *live* real-world endpoint via `curl`/direct fetch during design. Telethon uses MTProto
(a custom binary protocol over raw sockets), not HTTP — there is no `curl`-equivalent available in
this environment, and generating a real session requires an interactive phone-number + OTP login
that only the user can perform, with a real Telegram account and a real private channel they
belong to. **This plan's API facts come from Telethon's official docs (fetched, not recalled from
training) — verified secondhand, not exercised against a live account.** The collector's own logic
(filtering, checkpointing, error handling) is fully unit-tested against a fake client; the thin
wrapper around the real `telethon.TelegramClient` is not, and cannot be, exercised end-to-end
here. This is flagged explicitly rather than silently claimed as equivalently verified.

**Confirmed via fetching Telethon's official docs (docs.telethon.dev), current stable v1.44.0
(not the v2 alpha, which changes this API meaningfully):**
- `from telethon import TelegramClient`; `from telethon.sessions import StringSession` — a
  `StringSession` is Telethon's serializable, headless-friendly session format, explicitly
  documented for exactly this project's use case (a CI/cron runner with no persistent disk,
  Telethon's own docs use Heroku as the example).
- One-time interactive login: `await client.start()` prompts for phone number then OTP code in
  the terminal (only works in a real interactive terminal — cannot run in `pytest` or CI); the
  resulting string is `client.session.save()`.
- Fetching messages: `async for message in client.iter_messages(entity, limit=N):` — an async
  generator; `limit` bounds it directly, so (unlike the public-preview HTML scraper) **no manual
  pagination loop is needed** — Telethon handles paging internally.
- Message fields: `.raw_text` = plain text with no markup (the right field for plain-content
  capture, vs `.text` which applies the client's parse-mode formatting); `.id` = message ID.
- Async/sync bridging: Telethon's docs present three options; this project picks plain
  `asyncio.run(main())` wrapping an `async def main(): ...` — explicitly avoids `telethon.sync`'s
  global monkey-patching, since the rest of this 100%-synchronous codebase should not be affected
  by importing this one module.
- Errors: `from telethon.errors.rpcerrorlist import FloodWaitError, ChannelPrivateError` — no
  automatic flood-wait retry exists in the library (confirmed: official examples show manual
  `except FloodWaitError as e: time.sleep(e.seconds)`), so this collector must catch it itself.

**Scope decisions:**
- **New optional dependency, not a hard one.** `telethon` is added as an optional extra
  (`[project.optional-dependencies].telethon`), not a base dependency — most users of this project
  will never touch private-channel Telegram collection. `investor_intel/collectors/
  telethon_client.py` imports `telethon` at module level (it's the module's entire reason to
  exist), but `pipeline/collect.py` and `cli.py` only import *that module* lazily, inside the
  function bodies that need it — so `uv run python -m investor_intel doctor` (or any other
  command) still works with zero `telethon` install, exactly like every other optional
  credential-gated feature in this project degrades gracefully rather than hard-failing.
- **Testability via a `Protocol`, not by mocking Telethon's own client class.** A minimal
  `TelethonClientProtocol` (one async method: `iter_messages`) is the seam
  `TelethonPrivateChannelCollector` depends on — tests inject a fake implementing exactly that
  protocol (yielding canned `TelethonMessage`s), never touching real Telethon or asyncio-over-
  MTProto. This mirrors the `SimpleHttpClient`/`DartClient`/`SECClient` dependency-injection
  pattern already used by every other collector, just for an async seam instead of an HTTP one.
- **`limit=200` per run, no manual pagination** — matches phase 17's public-preview page-cap
  scope (bounded, documented) but the mechanism is simpler here since Telethon's own `limit=`
  parameter does the work; no cursor/loop logic to write or test.
- **A new `source.type == "telegram_private"`** in `sources.yaml`, distinct from `"telegram"` —
  the same source needing both public-preview *and* Telethon collection isn't a real scenario
  (if you have Telethon access, you don't need the public-preview fallback for that channel), so
  no dual-registration complexity is built.
- **A new dedicated `telegram_private_document.py`** (own `TELEGRAM_PRIVATE_LIMITATIONS_NOTE`),
  not a reuse of the public collector's `render_telegram_message_body` — that function's note
  hardcodes "공개 웹 미리보기만 수집" which would be factually wrong here. Matches this
  project's established one-`*_document.py`-per-source-type convention.
- **The one-time login flow is a new CLI command (`telethon-login`), not a standalone script** —
  keeps it discoverable alongside `init`/`doctor`, prints the resulting `TELEGRAM_SESSION` value
  for the user to paste into `.env`. Explicitly not unit-tested beyond import/syntax checks (ruff/
  mypy) — it requires a real interactive terminal and a real Telegram account, which is exactly
  the same "cannot verify live" limitation stated above.
- **Manual `FloodWaitError` handling**: catch it, sleep `e.seconds` (capped — see Task 2), retry
  once; a `ChannelPrivateError` (not a member / channel doesn't exist) is treated as a collection
  failure for that source (`CollectResult.errors`), not a crash of the whole `collect` run —
  consistent with every other collector's per-source failure isolation.

## Task breakdown

### Task 1: `collectors/telethon_client.py` — protocol + real wrapper

**Files:** modify `pyproject.toml` (add `telethon` optional extra); create
`investor_intel/collectors/telethon_client.py`; test `tests/test_telethon_client_protocol.py`
(tests the protocol/dataclass shape and any pure logic only — not real Telethon network calls).

**Interfaces:**
- `TelethonMessage` dataclass: `id: int`, `text: str`, `date: datetime` (UTC-aware).
- `TelethonClientProtocol(Protocol)`: `async def iter_messages(self, entity: str, limit: int) ->
  AsyncIterator[TelethonMessage]: ...`
- `RealTelethonClient` — real wrapper: constructor takes `(session: str, api_id: int, api_hash:
  str)`, builds a `telethon.TelegramClient(StringSession(session), api_id, api_hash)`;
  `iter_messages` opens the client as an async context manager, iterates
  `self._client.iter_messages(entity, limit=limit)`, maps each Telethon `Message` to
  `TelethonMessage` (using `.raw_text`), skipping empty-text (media-only) messages, catching
  `FloodWaitError` once with a single capped sleep-and-retry (cap at e.g. 60s — never block a
  `collect` run for an arbitrarily long flood-wait; if still flood-waited after one retry, let it
  raise and be handled as a collection failure like any other error).

- [x] Write failing tests for the parts that don't require a live Telethon session (dataclass
      construction, protocol conformance of a fake implementation), implement, verify pass. Note
      in the test file's docstring/comment that `RealTelethonClient` itself is not exercised here
      — it's a thin pass-through over Telethon's own (separately-tested-upstream) API.
- [x] Commit: `feat: add Telethon client protocol and wrapper for private-channel collection`

### Task 2: `collectors/telegram_private.py` + `telegram_private_document.py`

**Files:** create `investor_intel/collectors/telegram_private_document.py` (renderer,
`TELEGRAM_PRIVATE_LIMITATIONS_NOTE`), `investor_intel/collectors/telegram_private.py`
(`TelethonPrivateChannelCollector`); tests `tests/test_telegram_private_document.py`,
`tests/test_telegram_private_collector.py` (using a fake `TelethonClientProtocol`
implementation, no real Telethon/asyncio-over-MTProto involved).

**Interfaces:**
- `TelethonPrivateChannelCollector(source: SourceConfig, client: TelethonClientProtocol,
  checkpoint_store: CheckpointStore)` implementing the `Collector` protocol — `source_id =
  source.id`; entity/channel extracted from `source.url` the same way as the public collector
  (reuse `_extract_channel`).
- `backfill(days)`/`collect_incremental()` both call `asyncio.run(self._fetch_all_messages())`
  internally (one `asyncio.run` per collect call — no persistent event loop, matching Telethon's
  documented recommendation for one-shot script usage), then apply the same date-cutoff/
  last-seen-id filtering pattern as every other collector.

- [x] Write failing tests (fake client yields canned messages; `backfill`/`collect_incremental`
      produce correct `CollectResult`s; a fake client raising `ChannelPrivateError` produces a
      failed `CollectResult` with an error message, not an unhandled exception; renderer includes
      all 8 sections plus the Telethon-specific limitations note), implement, verify pass
- [x] Commit: `feat: add Telethon-based private channel Telegram collector`

### Task 3: Wire into config + `build_collect_entries` + `telethon-login` CLI command

**Files:** modify `investor_intel/pipeline/collect.py` (lazy-import `telegram_private` module;
new branch for `source.type == "telegram_private"`, gated on all three Telethon env vars being
set), `investor_intel/cli.py` (new `telethon-login` command, lazy-imports `telethon`); extend
`tests/test_build_collect_entries.py`; update `README.md`'s env var table and `RUNBOOK_MD`'s
`doctor` explanation (both currently say Telethon is "out of scope"/"향후 확장 항목" — no longer
true).

- [x] Write a failing test (a `sources.yaml` fixture with one `telegram_private` entry; asserts no
      `TelethonPrivateChannelCollector` entry is created when credentials are missing (with a
      `setup_errors` message), and one *is* created when all three env vars are set — using a
      monkeypatched/injected fake client so this test never imports real `telethon`), implement,
      verify pass
- [x] Commit: `feat: wire Telethon private channel collector into config and collect pipeline`

## Self-review notes

- **The single biggest departure from this project's established rigor, stated plainly:** every
  other collector was verified against a live real endpoint during design; this one's API facts
  are doc-verified but not live-exercised, because doing so requires a real Telegram account,
  phone number, and private channel membership that aren't available in this environment. The
  collector's *own* logic is still fully unit-tested — only the thin real-SDK wrapper isn't.
- **Optional dependency, lazy-imported at the boundary** — `telethon` never becomes a tax on
  users who don't need it, matching this project's existing pattern of every credential-gated
  feature degrading gracefully instead of hard-failing.
- **Protocol-based test seam mirrors the existing `SimpleHttpClient`-style DI pattern** — applied
  to an async boundary instead of an HTTP one, not a new testing philosophy.
- **`telethon-login` is deliberately a manual, unverified-here CLI command** — flagged rather than
  silently presented as tested, consistent with this project's practice of stating limitations
  explicitly instead of overclaiming coverage.
