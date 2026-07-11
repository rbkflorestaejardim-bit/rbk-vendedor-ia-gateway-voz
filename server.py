import asyncio
import audioop
import io
import json
import logging
import math
import os
import re
import signal
import struct
import time
import urllib.error
import urllib.request
import uuid
import wave
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from piper import PiperVoice


HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "9019"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
GROQ_STT_MODEL = os.getenv(
    "GROQ_STT_MODEL",
    "whisper-large-v3-turbo",
).strip()
GROQ_STT_LANGUAGE = os.getenv("GROQ_STT_LANGUAGE", "pt").strip()
GROQ_LLM_MODEL = os.getenv(
    "GROQ_LLM_MODEL",
    "llama-3.1-8b-instant",
).strip()

PIPER_VOICE_MODEL = os.getenv(
    "PIPER_VOICE_MODEL",
    "/app/voices/pt_BR-faber-medium.onnx",
).strip()

ECHO_UUID = os.getenv(
    "ECHO_UUID",
    "11111111-1111-4111-8111-111111111111",
).strip()
STT_UUID = os.getenv(
    "STT_UUID",
    "22222222-2222-4222-8222-222222222222",
).strip()
CONVERSATION_UUID = os.getenv(
    "CONVERSATION_UUID",
    "33333333-3333-4333-8333-333333333333",
).strip()

VAD_RMS_THRESHOLD = int(os.getenv("VAD_RMS_THRESHOLD", "350"))
SILENCE_SECONDS = float(os.getenv("SILENCE_SECONDS", "1.2"))
MIN_SPEECH_SECONDS = float(os.getenv("MIN_SPEECH_SECONDS", "0.6"))
MAX_CAPTURE_SECONDS = float(os.getenv("MAX_CAPTURE_SECONDS", "12"))
PRE_ROLL_SECONDS = float(os.getenv("PRE_ROLL_SECONDS", "0.3"))

SAMPLE_RATE = 8000
SAMPLE_WIDTH = 2
CHANNELS = 1
AUDIO_FRAME_MS = 20
AUDIO_SAMPLES_PER_FRAME = SAMPLE_RATE * AUDIO_FRAME_MS // 1000
AUDIO_BYTES_PER_FRAME = AUDIO_SAMPLES_PER_FRAME * SAMPLE_WIDTH

TYPE_HANGUP = 0x00
TYPE_UUID = 0x01
TYPE_DTMF = 0x03
TYPE_AUDIO_8KHZ = 0x10
TYPE_ERROR = 0xFF

HEADER_SIZE = 3
MAX_PAYLOAD = 65535

GREETING_TEXT = (
    "Olá. Aqui é o Carlos da RBK Distribuidora. "
    "Este é um teste do vendedor virtual. "
    "Depois do sinal, diga seu nome e o produto que deseja consultar."
)

SYSTEM_PROMPT = """
Você é Carlos, vendedor técnico da RBK Distribuidora Floresta e Jardim.
Atende clientes sobre peças e acessórios para roçadeiras, motosserras,
sopradores, cortadores de grama e equipamentos similares.

Regras obrigatórias:
- Responda em português do Brasil.
- Use no máximo duas frases curtas e 240 caracteres.
- Não use markdown, listas ou emojis.
- Não invente preço, estoque, prazo, código, aplicação ou compatibilidade.
- Neste piloto você ainda não consulta o ERP.
- Faça apenas uma pergunta técnica por resposta.
- Se o produto for genérico, pergunte marca e modelo da máquina.
- Para corrente de motosserra, pergunte marca/modelo ou passo, calibre e
  quantidade de elos.
- Seja profissional, direto e cordial.
- Não diga que é humano.
""".strip()


logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("gateway-voz")

PIPER_VOICE: PiperVoice | None = None


@dataclass
class SessionStats:
    frames_audio: int = 0
    bytes_audio: int = 0
    frames_dtmf: int = 0
    max_rms: int = 0


def pcm_rms(payload: bytes) -> int:
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


def transcribe_with_groq(pcm_audio: bytes) -> str:
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
            "User-Agent": "RBK-Vendedor-IA-Gateway/0.3.0",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            response_data = response.read().decode(
                "utf-8",
                errors="replace",
            )
            payload = json.loads(response_data)
            return (payload.get("text") or "").strip()
    except urllib.error.HTTPError as error:
        body_error = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Groq STT retornou HTTP {error.code}: {body_error}"
        ) from error


def sanitize_llm_text(text: str) -> str:
    text = re.sub(r"[*_`#>\[\]{}]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > 300:
        text = text[:297].rstrip() + "..."
    return text


def generate_sales_reply(transcript: str) -> str:
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY não configurada.")

    body = json.dumps(
        {
            "model": GROQ_LLM_MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": transcript,
                },
            ],
            "temperature": 0.2,
            "max_completion_tokens": 90,
        }
    ).encode("utf-8")

    request = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "RBK-Vendedor-IA-Gateway/0.3.0",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(
                response.read().decode("utf-8", errors="replace")
            )
            content = payload["choices"][0]["message"]["content"]
            clean_content = sanitize_llm_text(content)
            if not clean_content:
                raise RuntimeError("A Groq retornou uma resposta vazia.")
            return clean_content
    except urllib.error.HTTPError as error:
        body_error = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Groq LLM retornou HTTP {error.code}: {body_error}"
        ) from error


def synthesize_piper_pcm8k(text: str) -> bytes:
    if PIPER_VOICE is None:
        raise RuntimeError("Voz Piper não carregada.")

    wav_buffer = io.BytesIO()
    with wave.open(wav_buffer, "wb") as wav_file:
        PIPER_VOICE.synthesize_wav(text, wav_file)

    wav_buffer.seek(0)
    with wave.open(wav_buffer, "rb") as wav_file:
        source_channels = wav_file.getnchannels()
        source_width = wav_file.getsampwidth()
        source_rate = wav_file.getframerate()
        audio_data = wav_file.readframes(wav_file.getnframes())

    if source_channels == 2:
        audio_data = audioop.tomono(
            audio_data,
            source_width,
            0.5,
            0.5,
        )
        source_channels = 1

    if source_channels != 1:
        raise RuntimeError(
            f"Piper gerou {source_channels} canais; esperado: 1."
        )

    if source_width != SAMPLE_WIDTH:
        audio_data = audioop.lin2lin(
            audio_data,
            source_width,
            SAMPLE_WIDTH,
        )
        source_width = SAMPLE_WIDTH

    if source_rate != SAMPLE_RATE:
        audio_data, _ = audioop.ratecv(
            audio_data,
            SAMPLE_WIDTH,
            CHANNELS,
            source_rate,
            SAMPLE_RATE,
            None,
        )

    if len(audio_data) % SAMPLE_WIDTH:
        audio_data = audio_data[:-1]

    return audio_data


def generate_tone_frame(
    frequency_hz: float,
    start_sample: int,
    sample_count: int,
    amplitude: int = 6500,
) -> bytes:
    samples = []
    for index in range(sample_count):
        absolute_sample = start_sample + index
        angle = 2.0 * math.pi * frequency_hz * absolute_sample / SAMPLE_RATE
        samples.append(int(amplitude * math.sin(angle)))
    return struct.pack(f"<{sample_count}h", *samples)


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


async def send_pcm_realtime(
    writer: asyncio.StreamWriter,
    pcm_audio: bytes,
) -> float:
    total_bytes = len(pcm_audio)
    offset = 0

    while offset < total_bytes:
        payload = pcm_audio[offset:offset + AUDIO_BYTES_PER_FRAME]
        if len(payload) < AUDIO_BYTES_PER_FRAME:
            payload += b"\x00" * (
                AUDIO_BYTES_PER_FRAME - len(payload)
            )

        await send_frame(writer, TYPE_AUDIO_8KHZ, payload)
        offset += AUDIO_BYTES_PER_FRAME
        await asyncio.sleep(AUDIO_FRAME_MS / 1000)

    return total_bytes / (SAMPLE_RATE * SAMPLE_WIDTH)


async def speak_text(
    writer: asyncio.StreamWriter,
    text: str,
    session_uuid: str | None,
) -> float:
    start = time.perf_counter()
    pcm_audio = await asyncio.to_thread(synthesize_piper_pcm8k, text)
    synthesis_seconds = time.perf_counter() - start
    audio_seconds = len(pcm_audio) / (SAMPLE_RATE * SAMPLE_WIDTH)

    logger.info(
        "TTS PIPER: uuid=%s sintese=%.2fs audio=%.2fs texto=%r",
        session_uuid,
        synthesis_seconds,
        audio_seconds,
        text,
    )

    await send_pcm_realtime(writer, pcm_audio)
    return audio_seconds


async def send_tone(
    writer: asyncio.StreamWriter,
    frequency_hz: float = 1000.0,
    duration_seconds: float = 0.18,
    gap_after_seconds: float = 0.12,
) -> None:
    total_samples = max(1, int(SAMPLE_RATE * duration_seconds))
    sent_samples = 0

    while sent_samples < total_samples:
        frame_samples = min(
            AUDIO_SAMPLES_PER_FRAME,
            total_samples - sent_samples,
        )
        payload = generate_tone_frame(
            frequency_hz=frequency_hz,
            start_sample=sent_samples,
            sample_count=frame_samples,
        )
        if len(payload) < AUDIO_BYTES_PER_FRAME:
            payload += b"\x00" * (
                AUDIO_BYTES_PER_FRAME - len(payload)
            )

        await send_frame(writer, TYPE_AUDIO_8KHZ, payload)
        sent_samples += frame_samples
        await asyncio.sleep(AUDIO_FRAME_MS / 1000)

    if gap_after_seconds > 0:
        silence_frames = max(
            1,
            int(gap_after_seconds * 1000 / AUDIO_FRAME_MS),
        )
        silence_payload = b"\x00" * AUDIO_BYTES_PER_FRAME
        for _ in range(silence_frames):
            await send_frame(
                writer,
                TYPE_AUDIO_8KHZ,
                silence_payload,
            )
            await asyncio.sleep(AUDIO_FRAME_MS / 1000)


async def handle_client(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
) -> None:
    peer = writer.get_extra_info("peername")
    session_uuid: str | None = None
    mode = "unknown"
    stats = SessionStats()

    captured_audio = bytearray()
    pre_roll: deque[bytes] = deque()
    pre_roll_duration = 0.0
    speech_started = False
    speech_duration = 0.0
    silence_duration = 0.0
    total_capture_duration = 0.0
    finish_reason: str | None = None
    ignore_audio_seconds = 0.0

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
                elif session_uuid == CONVERSATION_UUID:
                    mode = "conversation"
                else:
                    mode = "unknown"

                logger.info(
                    "Sessão identificada: uuid=%s modo=%s peer=%s",
                    session_uuid,
                    mode,
                    peer,
                )

                if mode == "stt":
                    logger.info(
                        "Enviando bip inicial pelo AudioSocket: uuid=%s",
                        session_uuid,
                    )
                    await send_tone(writer)
                    ignore_audio_seconds = 0.25

                elif mode == "conversation":
                    greeting_duration = await speak_text(
                        writer,
                        GREETING_TEXT,
                        session_uuid,
                    )
                    await send_tone(writer)
                    ignore_audio_seconds = greeting_duration + 0.45

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

                if mode not in {"stt", "conversation"}:
                    continue

                if ignore_audio_seconds > 0:
                    ignore_audio_seconds = max(
                        0.0,
                        ignore_audio_seconds - frame_duration,
                    )
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
                            captured_audio.extend(frame)
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
                    captured_audio.extend(payload)

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

        if mode in {"stt", "conversation"}:
            transcript = ""

            if speech_started and captured_audio:
                logger.info(
                    "Enviando áudio para Groq: uuid=%s motivo=%s "
                    "segundos=%.2f bytes=%s max_rms=%s",
                    session_uuid,
                    finish_reason or "conexao_encerrada",
                    len(captured_audio) / (SAMPLE_RATE * SAMPLE_WIDTH),
                    len(captured_audio),
                    stats.max_rms,
                )
                transcript = await asyncio.to_thread(
                    transcribe_with_groq,
                    bytes(captured_audio),
                )
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

            if mode == "stt":
                await send_tone(
                    writer,
                    frequency_hz=1200.0,
                    duration_seconds=0.16,
                    gap_after_seconds=0.08,
                )

            elif mode == "conversation":
                if transcript:
                    try:
                        reply = await asyncio.to_thread(
                            generate_sales_reply,
                            transcript,
                        )
                        logger.info(
                            "RESPOSTA LLM: uuid=%s texto=%r",
                            session_uuid,
                            reply,
                        )
                    except Exception:
                        logger.exception(
                            "Falha ao gerar resposta comercial: uuid=%s",
                            session_uuid,
                        )
                        reply = (
                            "Tive uma falha ao processar sua solicitação. "
                            "Este teste será encerrado agora."
                        )
                else:
                    reply = (
                        "Não consegui entender sua resposta. "
                        "Este teste será encerrado agora."
                    )

                final_text = (
                    f"{reply} Obrigado. Este teste será encerrado agora."
                )
                await speak_text(
                    writer,
                    final_text,
                    session_uuid,
                )

            await send_frame(writer, TYPE_HANGUP)

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
    global PIPER_VOICE

    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY não configurada.")

    model_path = Path(PIPER_VOICE_MODEL)
    if not model_path.is_file():
        raise RuntimeError(
            f"Modelo Piper não encontrado: {PIPER_VOICE_MODEL}"
        )

    load_start = time.perf_counter()
    PIPER_VOICE = await asyncio.to_thread(
        PiperVoice.load,
        str(model_path),
    )
    logger.info(
        "Voz Piper carregada: modelo=%s tempo=%.2fs",
        PIPER_VOICE_MODEL,
        time.perf_counter() - load_start,
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
        "Gateway de voz RBK v0.3.0 iniciado: endereços=%s "
        "echo_uuid=%s stt_uuid=%s conversation_uuid=%s "
        "modelo_stt=%s modelo_llm=%s",
        addresses,
        ECHO_UUID,
        STT_UUID,
        CONVERSATION_UUID,
        GROQ_STT_MODEL,
        GROQ_LLM_MODEL,
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
