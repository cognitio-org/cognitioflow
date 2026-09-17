"""
Tutor dictation relay (Phase 8, Part A): one browser WebSocket <-> one Vertex AI Live transcription session.

  browser -> server  binary frames of 16 kHz mono PCM16 (about 100 ms each), then the text frame {"stop": true}
  server -> browser  {"interim": text} while you speak and {"final": text} as phrases settle — both carry the whole text
                     so far; {"limit": true} near Vertex's 10-minute cap; then {"done": text, "seconds", "cost_usd"}
                     or {"error": message}

Vertex is reached with the service account's Application Default Credentials; the browser only ever receives transcript
text — no key, token or credential. No audio is stored. Model and location come from the environment.
"""
import asyncio
import json
import os
import time

MODEL = os.environ.get("VOICE_MODEL", "gemini-3.5-transcribe-live-preview")
LOCATION = os.environ.get("VOICE_LOCATION", "global")   # the preview model answers on Vertex's global endpoint (probed 2026-09-15)
LANGUAGE = "en-GB"
MAX_VOCABULARY = 100
MAX_SECONDS = 9 * 60 + 30            # Live sessions end at 10 minutes
BYTES_PER_SECOND = 32000             # 16 kHz x 2 bytes
USD_PER_MINUTE = float(os.environ.get("VOICE_USD_PER_MIN", "0.009"))  # estimate for the cost readout, not a bill
SETTLE_SECONDS = 1.5                 # after stop, finish once no new text has arrived for this long
MAX_SETTLE_SECONDS = 8.0
_client = None                       # an API client, not session state


def available() -> bool:
    return bool(os.environ.get("GCP_PROJECT")) and os.environ.get("VOICE_GEMINI", "on").lower() != "off"


def vocabulary_terms(terms) -> list:
    return [t for t in dict.fromkeys((t or "").strip() for t in terms) if t][:MAX_VOCABULARY]


def live_config(terms):
    from google.genai import types
    vocab = vocabulary_terms(terms)
    return types.LiveConnectConfig(
        response_modalities=["TEXT"],
        input_audio_transcription=types.AudioTranscriptionConfig(language_codes=[LANGUAGE], custom_vocabulary=vocab or None))


def _connect(terms):
    global _client
    if _client is None:
        from google import genai
        _client = genai.Client(vertexai=True, project=os.environ["GCP_PROJECT"], location=LOCATION)
    return _client.aio.live.connect(model=MODEL, config=live_config(terms))


async def relay(websocket, terms, connect=None, clock=time.monotonic, sleep=asyncio.sleep) -> dict:
    """Run one dictation over an accepted WebSocket and close it. Returns {text, seconds, cost_usd, error}.
    `connect` (terms -> async context manager yielding a Live session), `clock` and `sleep` are injectable for tests."""
    from google.genai import types
    connect = connect or _connect
    finals, state = [], {"audio": 0, "last_text": clock()}
    summary = {"text": "", "seconds": 0.0, "cost_usd": 0.0, "error": ""}

    def so_far(extra: str = "") -> str:
        return " ".join(p for p in (*finals, extra.strip()) if p)

    async def downstream(session):
        async for message in session.receive():
            content = getattr(message, "server_content", None)
            if not content:
                continue
            interim = getattr(content, "interim_input_transcription", None)
            final = getattr(content, "input_transcription", None)
            if interim is not None and interim.text:
                state["last_text"] = clock()
                await websocket.send_json({"interim": so_far(interim.text)})
            if final is not None and final.text and final.text.strip():
                state["last_text"] = clock()
                finals.append(final.text.strip())
                await websocket.send_json({"final": so_far()})

    def raise_if_failed(task):
        if task.done() and not task.cancelled() and task.exception():
            raise task.exception()

    try:
        async with connect(terms) as session:
            receiving = asyncio.create_task(downstream(session))
            started = clock()
            try:
                while True:
                    raise_if_failed(receiving)
                    frame = await websocket.receive()
                    if frame.get("type") == "websocket.disconnect":   # tab closed: nothing left to send to
                        summary.update(text=so_far(), seconds=state["audio"] / BYTES_PER_SECOND)
                        return summary
                    if frame.get("bytes"):
                        state["audio"] += len(frame["bytes"])
                        await session.send_realtime_input(audio=types.Blob(data=frame["bytes"], mime_type="audio/pcm;rate=16000"))
                        if clock() - started > MAX_SECONDS:
                            await websocket.send_json({"limit": True})
                            break
                    elif frame.get("text"):
                        try:
                            if json.loads(frame["text"]).get("stop"):
                                break
                        except (ValueError, AttributeError):
                            pass
                await session.send_realtime_input(audio_stream_end=True)
                stop_at = clock()
                state["last_text"] = max(state["last_text"], stop_at)
                while not receiving.done() and clock() - state["last_text"] < SETTLE_SECONDS and clock() - stop_at < MAX_SETTLE_SECONDS:
                    await sleep(0.1)
                raise_if_failed(receiving)
            finally:
                receiving.cancel()
    except Exception as e:  # Vertex refused, quota, network: the browser falls back to Browser mode for this attempt
        summary["error"] = f"Gemini dictation is unavailable right now ({type(e).__name__})."
        try:
            await websocket.send_json({"error": summary["error"]})
            await websocket.close(code=1011)
        except Exception:
            pass
        return summary

    seconds = state["audio"] / BYTES_PER_SECOND
    summary.update(text=so_far(), seconds=round(seconds, 1), cost_usd=round(seconds / 60 * USD_PER_MINUTE, 5))
    await websocket.send_json({"done": summary["text"], "seconds": summary["seconds"], "cost_usd": summary["cost_usd"]})
    await websocket.close(code=1000)
    return summary
