import asyncio
import io
import json
import logging
import os
import signal
import struct
import urllib.error
import urllib.request
import uuid
import wave
from collections import deque
from dataclasses import dataclass


HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "9019"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
GROQ_STT_MODEL = os.getenv(
    "GROQ_STT_MODEL",
    "whisper-large-v3-turbo",
).strip()
GROQ_STT_LANGUAGE = os.getenv("GROQ_STT_LANGUAGE", "pt").strip()

ECHO_UUID = os.getenv(
    "ECHO_UUID",
    "11111111-1111-4111-8111-111111111111",
).strip()
STT_UUID = os.getenv(
    "STT_UUID",
    "22222222-2222-4222-8222-222222222222",
).strip()

VAD_RMS_THRESHOLD = int(os.getenv("VAD_RMS_THRESHOLD", "350"))
SILENCE_SECONDS = float(os.getenv("SILENCE_SECONDS", "1.2"))
MIN_SPEECH_SECONDS = float(os.getenv("MIN_SPEECH_SECONDS", "0.6"))
MAX_CAPTURE_SECONDS = float(os.getenv("MAX_CAPTURE_SECONDS", "12"))
PRE_ROLL_SECONDS = float(os.getenv("PRE_ROLL_SECONDS", "0.3"))

SAMPLE_RATE = 8000
SAMPLE_WIDTH = 2
CHANNELS = 1

TYPE_HANGUP = 0x00
TYPE_UUID = 0x01
TYPE_DTMF = 0x03
TYPE_AUDIO_8KHZ = 0x10
TYPE_ERROR = 0xFF

HEADER_SIZE = 3
MAX_PAYLOAD = 65535


logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("gateway-voz")


@dataclass
class SessionStats:
    frames_audio: int = 0
    bytes_audio: int = 0
    frames_dtmf: int = 0
    max_rms: int = 0


def pcm_rms(payload: bytes) -> int:
    """Calcula RMS de PCM signed linear 16-bit little-endian."""
    if len(payload) < 2:
        return 0

    usable_length = len(payload) - (len(payload) % 2)
    samples = struct.unpack(
        f"<{usable_length // 2}h",
        payload[:usable_length],
    )
    if not samples:
        return 0

    mean_square = sum(sample * sample for sample in samples) / len(samples)
    return int(mean_square ** 0.5)


def pcm_to_wav(pcm_audio: bytes) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(CHANNELS)
        wav_file.setsampwidth(SAMPLE_WIDTH)
        wav_file.setframerate(SAMPLE_RATE)
        wav_file.writeframes(pcm_audio)
    return output.getvalue()


def encode_multipart(
    fields: dict[str, str],
    file_field: str,
    filename: str,
    file_content: bytes,
    file_content_type: str,
) -> tuple[bytes, str]:
    boundary = f"----RBKBoundary{uuid.uuid4().hex}"
    body = bytearray()

    for name, value in fields.items():
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(
            (
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
                f"{value}\r\n"
            ).encode()
        )

    body.extend(f"--{boundary}\r\n".encode())
    body.extend(
        (
            f'Content-Disposition: form-data; name="{file_field}"; '
            f'filename="{filename}"\r\n'
            f"Content-Type: {file_content_type}\r\n\r\n"
        ).encode()
    )
    body.extend(file_content)
    body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode())

    return bytes(body), boundary


def transcribe_with_groq(pcm_audio: bytes) -> dict:
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY não configurada.")

    wav_audio = pcm_to_wav(pcm_audio)
    fields = {
        "model": GROQ_STT_MODEL,
        "language": GROQ_STT_LANGUAGE,
        "response_format": "json",
        "temperature": "0",
    }
    body, boundary = encode_multipart(
        fields=fields,
        file_field="file",
        filename="fala.wav",
        file_content=wav_audio,
        file_content_type="audio/wav",
    )

    request = urllib.request.Request(
        "https://api.groq.com/openai/v1/audio/transcriptions",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Accept": "application/json",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "User-Agent": "RBK-Vendedor-IA-Gateway/0.2.0",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            response_data = response.read().decode(
                "utf-8",
                errors="replace",
            )
            return json.loads(response_data)
    except urllib.error.HTTPError as error:
        body_error = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Groq STT retornou HTTP {error.code}: {body_error}"
        ) from error


async def read_exactly_or_none(
    reader: asyncio.StreamReader,
    size: int,
) -> bytes | None:
    try:
        return await reader.readexactly(size)
    except asyncio.IncompleteReadError as exc:
        if exc.partial:
            logger.warning(
                "Conexão encerrada com leitura parcial: esperado=%s recebido=%s",
                size,
                len(exc.partial),
            )
        return None


async def send_frame(
    writer: asyncio.StreamWriter,
    frame_type: int,
    payload: bytes = b"",
) -> None:
    if len(payload) > MAX_PAYLOAD:
        raise ValueError("Payload maior que o limite do AudioSocket.")

    writer.write(
        bytes([frame_type]) +
        struct.pack(">H", len(payload)) +
        payload
    )
    await writer.drain()


async def handle_client(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
) -> None:
    peer = writer.get_extra_info("peername")
    session_uuid: str | None = None
    mode = "unknown"
    stats = SessionStats()

    stt_audio = bytearray()
    pre_roll: deque[bytes] = deque()
    pre_roll_duration = 0.0
    speech_started = False
    speech_duration = 0.0
    silence_duration = 0.0
    total_capture_duration = 0.0
    finish_reason: str | None = None

    logger.info("Nova conexão AudioSocket: peer=%s", peer)

    try:
        while True:
            header = await read_exactly_or_none(reader, HEADER_SIZE)
            if header is None:
                break

            frame_type = header[0]
            payload_length = struct.unpack(">H", header[1:3])[0]

            payload = await read_exactly_or_none(reader, payload_length)
            if payload is None:
                break

            if frame_type == TYPE_HANGUP:
                logger.info(
                    "Hangup recebido: uuid=%s peer=%s",
                    session_uuid,
                    peer,
                )
                break

            if frame_type == TYPE_UUID:
                if payload_length != 16:
                    logger.error(
                        "UUID inválido: tamanho=%s peer=%s",
                        payload_length,
                        peer,
                    )
                    await send_frame(writer, TYPE_ERROR, b"\x01")
                    break

                session_uuid = str(uuid.UUID(bytes=payload))
                if session_uuid == ECHO_UUID:
                    mode = "echo"
                elif session_uuid == STT_UUID:
                    mode = "stt"
                else:
                    mode = "unknown"

                logger.info(
                    "Sessão identificada: uuid=%s modo=%s peer=%s",
                    session_uuid,
                    mode,
                    peer,
                )
                continue

            if frame_type == TYPE_DTMF:
                stats.frames_dtmf += 1
                digit = payload.decode("ascii", errors="replace")
                logger.info(
                    "DTMF recebido: uuid=%s digito=%s",
                    session_uuid,
                    digit,
                )
                continue

            if frame_type == TYPE_AUDIO_8KHZ:
                stats.frames_audio += 1
                stats.bytes_audio += payload_length
                frame_duration = payload_length / (
                    SAMPLE_RATE * SAMPLE_WIDTH
                )

                if mode == "echo":
                    await send_frame(
                        writer,
                        TYPE_AUDIO_8KHZ,
                        payload,
                    )
                    continue

                if mode != "stt":
                    continue

                total_capture_duration += frame_duration
                rms = pcm_rms(payload)
                stats.max_rms = max(stats.max_rms, rms)
                is_speech = rms >= VAD_RMS_THRESHOLD

                if not speech_started:
                    pre_roll.append(payload)
                    pre_roll_duration += frame_duration

                    while (
                        pre_roll and
                        pre_roll_duration > PRE_ROLL_SECONDS
                    ):
                        removed = pre_roll.popleft()
                        pre_roll_duration -= len(removed) / (
                            SAMPLE_RATE * SAMPLE_WIDTH
                        )

                    if is_speech:
                        speech_started = True
                        for frame in pre_roll:
                            stt_audio.extend(frame)
                        pre_roll.clear()
                        pre_roll_duration = 0.0
                        speech_duration += frame_duration
                        silence_duration = 0.0
                        logger.info(
                            "Início de fala detectado: uuid=%s rms=%s",
                            session_uuid,
                            rms,
                        )
                else:
                    stt_audio.extend(payload)

                    if is_speech:
                        speech_duration += frame_duration
                        silence_duration = 0.0
                    else:
                        silence_duration += frame_duration

                    if (
                        speech_duration >= MIN_SPEECH_SECONDS and
                        silence_duration >= SILENCE_SECONDS
                    ):
                        finish_reason = "silencio"
                        break

                if total_capture_duration >= MAX_CAPTURE_SECONDS:
                    finish_reason = "tempo_maximo"
                    break

            elif frame_type == TYPE_ERROR:
                logger.error(
                    "Erro recebido do Asterisk: uuid=%s codigo=%s",
                    session_uuid,
                    payload.hex() or "sem_codigo",
                )
                break
            else:
                logger.warning(
                    "Tipo de frame não tratado: uuid=%s tipo=0x%02x bytes=%s",
                    session_uuid,
                    frame_type,
                    payload_length,
                )

        if mode == "stt":
            if speech_started and stt_audio:
                logger.info(
                    "Enviando áudio para Groq: uuid=%s motivo=%s "
                    "segundos=%.2f bytes=%s max_rms=%s",
                    session_uuid,
                    finish_reason or "conexao_encerrada",
                    len(stt_audio) / (SAMPLE_RATE * SAMPLE_WIDTH),
                    len(stt_audio),
                    stats.max_rms,
                )
                result = await asyncio.to_thread(
                    transcribe_with_groq,
                    bytes(stt_audio),
                )
                transcript = (result.get("text") or "").strip()
                logger.info(
                    "TRANSCRICAO GROQ: uuid=%s texto=%r",
                    session_uuid,
                    transcript,
                )
            else:
                logger.warning(
                    "Nenhuma fala válida detectada: uuid=%s "
                    "segundos_totais=%.2f max_rms=%s limiar=%s",
                    session_uuid,
                    total_capture_duration,
                    stats.max_rms,
                    VAD_RMS_THRESHOLD,
                )

    except asyncio.CancelledError:
        raise
    except (ConnectionError, BrokenPipeError) as exc:
        logger.warning(
            "Conexão perdida: uuid=%s peer=%s erro=%s",
            session_uuid,
            peer,
            exc,
        )
    except Exception:
        logger.exception(
            "Erro inesperado na sessão: uuid=%s peer=%s",
            session_uuid,
            peer,
        )
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass

        logger.info(
            "Sessão encerrada: uuid=%s modo=%s peer=%s "
            "frames_audio=%s bytes_audio=%s frames_dtmf=%s max_rms=%s",
            session_uuid,
            mode,
            peer,
            stats.frames_audio,
            stats.bytes_audio,
            stats.frames_dtmf,
            stats.max_rms,
        )


async def main() -> None:
    if not GROQ_API_KEY:
        logger.warning(
            "GROQ_API_KEY não configurada. O modo echo funcionará, "
            "mas o teste STT falhará."
        )

    server = await asyncio.start_server(
        handle_client,
        host=HOST,
        port=PORT,
        reuse_address=True,
    )

    addresses = ", ".join(
        str(sock.getsockname())
        for sock in server.sockets or []
    )
    logger.info(
        "Gateway de voz RBK v0.2.0 iniciado: endereços=%s "
        "echo_uuid=%s stt_uuid=%s modelo_stt=%s",
        addresses,
        ECHO_UUID,
        STT_UUID,
        GROQ_STT_MODEL,
    )

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            pass

    async with server:
        await stop_event.wait()

    logger.info("Gateway de voz RBK encerrado.")


if __name__ == "__main__":
    asyncio.run(main())
