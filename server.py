import asyncio
import logging
import os
import signal
import struct
import uuid
from dataclasses import dataclass


HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "9019"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
ECHO_AUDIO = os.getenv("ECHO_AUDIO", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "sim",
}

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
        raise ValueError("Payload maior que o limite do protocolo AudioSocket.")

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
    stats = SessionStats()

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
                logger.info(
                    "Sessão identificada: uuid=%s peer=%s",
                    session_uuid,
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

                if ECHO_AUDIO:
                    await send_frame(
                        writer,
                        TYPE_AUDIO_8KHZ,
                        payload,
                    )
                continue

            if frame_type == TYPE_ERROR:
                logger.error(
                    "Erro recebido do Asterisk: uuid=%s codigo=%s",
                    session_uuid,
                    payload.hex() or "sem_codigo",
                )
                break

            logger.warning(
                "Tipo de frame não tratado: uuid=%s tipo=0x%02x bytes=%s",
                session_uuid,
                frame_type,
                payload_length,
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
            "Sessão encerrada: uuid=%s peer=%s "
            "frames_audio=%s bytes_audio=%s frames_dtmf=%s",
            session_uuid,
            peer,
            stats.frames_audio,
            stats.bytes_audio,
            stats.frames_dtmf,
        )


async def main() -> None:
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
        "Gateway de voz RBK iniciado: endereços=%s echo_audio=%s",
        addresses,
        ECHO_AUDIO,
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
