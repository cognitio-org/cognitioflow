"""
Spoken tutor (Phase 8, Part B): one browser WebSocket <-> one Vertex AI Live *dialog* session.

Where live.py transcribes and hands text back for the normal chat path, this one keeps the whole turn
inside Gemini: the student's speech goes up, the tutor's speech comes back, and Gemini itself decides
when it has been interrupted. That is the part a browser loop cannot do — the microphone must stay
open while the tutor talks, and only the model hears both sides well enough to stop mid-sentence.

  browser -> server  binary frames of 16 kHz mono PCM16, then the text frame {"stop": true}
  server -> browser  binary frames of 24 kHz mono PCM16 to play,
                     {"said": text} for what the student was heard to say,
                     {"spoke": text} for what the tutor said, so the screen keeps the words,
                     {"interrupted": true} when the student talked over the tutor — stop playback now,
                     {"limit": true} near Vertex's session cap, then {"done", "seconds", "cost_usd"}
                     or {"error": message}.

Credentials never reach the browser: Vertex is called with the service account's ADC. No audio is stored.
The system instruction is built by the caller from the course's own tutor prompt and its ticked excerpts,
so the spoken tutor answers under the same rules as the typed one.
"""
import asyncio
import json
import os
import time

MODEL = os.environ.get("VOICE_DIALOG_MODEL", "")     # no default on purpose: an invented model id fails at the worst moment
LOCATION = os.environ.get("VOICE_DIALOG_LOCATION", os.environ.get("VOICE_LOCATION", "global"))
VOICE_NAME = os.environ.get("VOICE_DIALOG_VOICE", "Charon")   # a measured male voice; Vertex names its own
LANGUAGE = "en-GB"
MAX_SECONDS = float(os.environ.get("VOICE_DIALOG_MAX_SECONDS", str(14 * 60)))
IN_BYTES_PER_SECOND = 32000          # 16 kHz x 2 bytes, what the browser sends
USD_PER_MINUTE = float(os.environ.get("VOICE_DIALOG_USD_PER_MIN", "0.023"))  # a readout, not a bill
_client = None


def available() -> bool:
    return bool(os.environ.get("GCP_PROJECT")) and bool(MODEL) and os.environ.get("VOICE_DIALOG", "on").lower() != "off"


def dialog_config(system: str):
    from google.genai import types
    return types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction=types.Content(parts=[types.Part(text=system or "")], role="user") if system else None,
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=VOICE_NAME)),
            language_code=LANGUAGE),
        input_audio_transcription=types.AudioTranscriptionConfig(),    # what he said, for the screen
        output_audio_transcription=types.AudioTranscriptionConfig())   # what it said, so the words are not lost with the sound


def _connect(system: str):
    global _client
    if _client is None:
        from google import genai
        _client = genai.Client(vertexai=True, project=os.environ["GCP_PROJECT"], location=LOCATION)
    return _client.aio.live.connect(model=MODEL, config=dialog_config(system))


async def relay(websocket, system, connect=None, clock=time.monotonic, sleep=asyncio.sleep) -> dict:
    """Run one spoken conversation over an accepted WebSocket and close it.
    Returns {said, spoke, seconds, cost_usd, error}. `connect`, `clock` and `sleep` are injectable for tests."""
    from google.genai import types
    connect = connect or _connect
    said, spoke, state = [], [], {"audio": 0}
    summary = {"said": "", "spoke": "", "seconds": 0.0, "cost_usd": 0.0, "error": ""}

    async def downstream(session):
        async for message in session.receive():
            content = getattr(message, "server_content", None)
            if not content:
                continue
            if getattr(content, "interrupted", False):
                # He started talking. Whatever is queued in the browser is already stale.
                await websocket.send_json({"interrupted": True})
                continue
            heard = getattr(content, "input_transcription", None)
            if heard is not None and (heard.text or "").strip():
                said.append(heard.text.strip())
                await websocket.send_json({"said": heard.text.strip()})
            spoken = getattr(content, "output_transcription", None)
            if spoken is not None and (spoken.text or "").strip():
                spoke.append(spoken.text.strip())
                await websocket.send_json({"spoke": spoken.text.strip()})
            turn = getattr(content, "model_turn", None)
            for part in (getattr(turn, "parts", None) or []):
                blob = getattr(part, "inline_data", None)
                if blob is not None and blob.data:
                    await websocket.send_bytes(blob.data)

    def raise_if_failed(task):
        if task.done() and not task.cancelled() and task.exception():
            raise task.exception()

    try:
        async with connect(system) as session:
            receiving = asyncio.create_task(downstream(session))
            started = clock()
            try:
                while True:
                    raise_if_failed(receiving)
                    frame = await websocket.receive()
                    if frame.get("type") == "websocket.disconnect":
                        summary.update(said=" ".join(said), spoke=" ".join(spoke),
                                       seconds=round(state["audio"] / IN_BYTES_PER_SECOND, 1))
                        return summary
                    if frame.get("bytes"):
                        state["audio"] += len(frame["bytes"])
                        await session.send_realtime_input(
                            audio=types.Blob(data=frame["bytes"], mime_type="audio/pcm;rate=16000"))
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
                await sleep(0.1)
                raise_if_failed(receiving)
            finally:
                receiving.cancel()
    except Exception as e:   # Vertex refused, quota, model name wrong, network: the page falls back to its own loop
        summary["error"] = f"The spoken tutor is unavailable right now ({type(e).__name__})."
        try:
            await websocket.send_json({"error": summary["error"]})
            await websocket.close(code=1011)
        except Exception:
            pass
        return summary

    seconds = state["audio"] / IN_BYTES_PER_SECOND
    summary.update(said=" ".join(said), spoke=" ".join(spoke), seconds=round(seconds, 1),
                   cost_usd=round(seconds / 60 * USD_PER_MINUTE, 5))
    await websocket.send_json({"done": True, "said": summary["said"], "spoke": summary["spoke"],
                               "seconds": summary["seconds"], "cost_usd": summary["cost_usd"]})
    await websocket.close(code=1000)
    return summary
