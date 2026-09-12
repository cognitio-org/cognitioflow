"""Google Cloud Speech-to-Text v2 BatchRecognize: chirp_2 in europe-west4, reading audio straight from the bucket,
results returned inline in the long-running operation. Credentials are ADC (Cloud Run's service account in cloud)."""
import os

from google.api_core import exceptions as gexc
from google.api_core.client_options import ClientOptions
from google.cloud.speech_v2 import SpeechClient, types
from google.longrunning import operations_pb2

from transcribe import ProviderError, group_words

MODEL = "chirp_2"
PERMANENT = (gexc.PermissionDenied, gexc.NotFound, gexc.InvalidArgument, gexc.FailedPrecondition, gexc.Unauthenticated)
_client = None  # an API client, not job state


def _region() -> str:
    return os.environ.get("STT_REGION", "europe-west4")


def _project() -> str:
    project = os.environ.get("GCP_PROJECT")
    if not project:
        import google.auth
        _, project = google.auth.default()
    if not project:
        raise ProviderError("Set GCP_PROJECT so transcription knows which Google Cloud project to bill.")
    return project


def client() -> SpeechClient:
    global _client
    if _client is None:
        _client = SpeechClient(client_options=ClientOptions(api_endpoint=f"{_region()}-speech.googleapis.com"))
    return _client


def _readable(e: Exception) -> str:
    kind = {gexc.PermissionDenied: "permission denied", gexc.Unauthenticated: "not signed in to Google Cloud",
            gexc.NotFound: "not found", gexc.InvalidArgument: "invalid request", gexc.FailedPrecondition: "not ready"}
    label = next((v for k, v in kind.items() if isinstance(e, k)), type(e).__name__)
    return f"Speech-to-Text {label}: {getattr(e, 'message', None) or e}"


def check_ready() -> None:
    if os.environ.get("STORAGE", "local") != "gcs" or not os.environ.get("GCS_BUCKET"):
        raise ProviderError("Transcription needs STORAGE=gcs: Google reads the audio straight from the bucket.")
    if os.environ.get("STORAGE_EMULATOR_HOST"):
        raise ProviderError("Transcription can't read audio from the fake-GCS emulator; use the real bucket.")


def submit(audio_key: str, language: str) -> str:
    check_ready()
    request = types.BatchRecognizeRequest(
        recognizer=f"projects/{_project()}/locations/{_region()}/recognizers/_",
        config=types.RecognitionConfig(
            auto_decoding_config=types.AutoDetectDecodingConfig(),  # WebM/Opus from MediaRecorder
            model=MODEL,
            language_codes=[language],
            features=types.RecognitionFeatures(enable_word_time_offsets=True, enable_automatic_punctuation=True),
        ),
        files=[types.BatchRecognizeFileMetadata(uri=f"gs://{os.environ['GCS_BUCKET']}/{audio_key}")],
        recognition_output_config=types.RecognitionOutputConfig(inline_response_config=types.InlineOutputConfig()),
    )
    try:
        return client().batch_recognize(request=request).operation.name
    except PERMANENT as e:
        raise ProviderError(_readable(e)) from e


def poll(op_id: str):
    try:
        op = client().get_operation(request=operations_pb2.GetOperationRequest(name=op_id))
    except PERMANENT as e:
        raise ProviderError(_readable(e)) from e
    if not op.done:
        return "running", None, ""
    if op.HasField("error") and op.error.code:
        return "failed", None, f"Speech-to-Text error: {op.error.message or op.error.code}"
    response = types.BatchRecognizeResponse.deserialize(op.response.value)
    if not response.results:
        return "failed", None, "Speech-to-Text returned no result for the recording."
    file_result = next(iter(response.results.values()))
    if file_result.error and file_result.error.code:
        return "failed", None, f"Speech-to-Text error: {file_result.error.message or file_result.error.code}"
    words, language, previous_end = [], "", 0.0
    for result in file_result.inline_result.transcript.results:
        language = language or result.language_code
        if result.alternatives:
            alt = result.alternatives[0]
            if alt.words:
                words += [(w.start_offset.total_seconds(), w.word) for w in alt.words]
            elif alt.transcript.strip():
                words.append((previous_end, alt.transcript))  # no word timings: anchor at the previous result's end
        previous_end = result.result_end_offset.total_seconds()
    return "done", group_words(words), language
