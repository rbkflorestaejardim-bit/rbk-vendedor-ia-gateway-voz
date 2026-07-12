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
from datetime import datetime, timezone
from pathlib import Path

from piper import PiperVoice


HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "9019"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
GROQ_STT_MODEL = os.getenv(
    "GROQ_STT_MODEL",
    "whisper-large-v3",
).strip()
GROQ_STT_LANGUAGE = os.getenv("GROQ_STT_LANGUAGE", "pt").strip()
GROQ_STT_PROMPT = os.getenv(
    "GROQ_STT_PROMPT",
    (
        "Brazilian Portuguese technical parts sales for forest and garden "
        "equipment. Terms and model names include: carburador, corrente, "
        "motosserra, roçadeira, soprador, Stihl MS 170, MS 180, FS 160, "
        "Husqvarna, Toyama, Kawashima, Tekna, Nagano. Preserve model codes."
    ),
).strip()
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
MULTITURN_UUID = os.getenv(
    "MULTITURN_UUID",
    "44444444-4444-4444-8444-444444444444",
).strip()

MAX_CONVERSATION_TURNS = int(
    os.getenv("MAX_CONVERSATION_TURNS", "8")
)

API_COMERCIAL_URL = os.getenv(
    "API_COMERCIAL_URL",
    "",
).strip().rstrip("/")
API_COMERCIAL_KEY = os.getenv(
    "API_COMERCIAL_KEY",
    "",
).strip()
PERSISTENCIA_VOZ_ATIVA = os.getenv(
    "PERSISTENCIA_VOZ_ATIVA",
    "false",
).strip().lower() in {"1", "true", "sim", "yes"}
PERSISTENCIA_CLIENTE_ID = os.getenv(
    "PERSISTENCIA_CLIENTE_ID",
    "",
).strip()
PERSISTENCIA_AGENDA_ID = os.getenv(
    "PERSISTENCIA_AGENDA_ID",
    "",
).strip()
PERSISTENCIA_VENDEDOR_CODIGO = os.getenv(
    "PERSISTENCIA_VENDEDOR_CODIGO",
    "CARLOS_RS",
).strip().upper()
PERSISTENCIA_DIRECAO = os.getenv(
    "PERSISTENCIA_DIRECAO",
    "entrada",
).strip().lower()
PERSISTENCIA_NUMERO_ORIGEM = os.getenv(
    "PERSISTENCIA_NUMERO_ORIGEM",
    "7001",
).strip()
PERSISTENCIA_NUMERO_DESTINO = os.getenv(
    "PERSISTENCIA_NUMERO_DESTINO",
    "605",
).strip()

VAD_RMS_THRESHOLD = int(os.getenv("VAD_RMS_THRESHOLD", "350"))
SILENCE_SECONDS = float(os.getenv("SILENCE_SECONDS", "0.70"))
MIN_SPEECH_SECONDS = float(os.getenv("MIN_SPEECH_SECONDS", "0.45"))
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

MULTITURN_GREETING_TEXT = (
    "Olá. Aqui é o Carlos da RBK Distribuidora. "
    "Vou fazer algumas perguntas para identificar corretamente a peça. "
    "Depois do sinal, diga seu nome e o produto que procura."
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

MULTITURN_SYSTEM_PROMPT = """
Você é Carlos, vendedor técnico virtual da RBK Distribuidora Floresta e Jardim.
Conduza uma triagem técnica por telefone para identificar corretamente a peça
antes de qualquer consulta de preço, estoque ou compatibilidade.

Retorne SOMENTE um objeto JSON válido com esta estrutura:
{
  "resposta": "fala curta para o cliente",
  "encerrar": false,
  "levantamento_completo": false,
  "motivo_encerramento": "",
  "estado": {
    "nome_cliente": null,
    "produto": null,
    "tipo_maquina": null,
    "marca_maquina": null,
    "modelo_maquina": null,
    "quantidade": null,
    "dados_tecnicos": {},
    "observacoes": []
  }
}

Regras obrigatórias:
- Fale em português do Brasil.
- A resposta deve ter no máximo duas frases curtas e 260 caracteres.
- Faça somente uma pergunta por turno.
- Não repita perguntas já respondidas.
- Atualize e devolva o estado completo, preservando dados anteriores.
- Interprete a estrutura "peça para modelo" corretamente. Exemplo: em
  "carburador para MS 170", produto=carburador, tipo_maquina=motosserra,
  marca_maquina=Stihl e modelo_maquina=MS 170.
- Códigos Stihl iniciados por MS identificam motosserras; não trate "MS"
  como nome de pessoa, unidade de medida ou texto sem significado.
- Não invente preço, estoque, prazo, código, aplicação ou compatibilidade.
- O ERP ainda não está conectado neste piloto.
- Se o cliente pedir para encerrar, disser que não tem interesse ou se
  despedir, use encerrar=true e responda com educação.
- Use levantamento_completo=true somente quando a peça estiver
  tecnicamente identificada e a quantidade estiver informada.
- Para corrente de motosserra, priorize passo, calibre, quantidade de elos
  e quantidade desejada. Marca e modelo ajudam, mas não substituem essas
  medidas quando houver dúvida de aplicação.
- Para outras peças, obtenha produto, marca e modelo da máquina, quantidade
  e ao menos um dado de identificação relevante, como código, medida,
  referência, lado, diâmetro ou descrição específica.
- Se o cliente não souber um dado, peça uma alternativa útil, como código
  gravado na peça, medida ou foto para atendimento posterior.
- Quando o levantamento estiver completo, confirme resumidamente os dados,
  informe que preço e estoque serão consultados na próxima integração e
  encerre.
- Não use markdown, listas, emojis nem texto fora do JSON.
""".strip()

INITIAL_SALES_STATE = {
    "nome_cliente": None,
    "produto": None,
    "tipo_maquina": None,
    "marca_maquina": None,
    "modelo_maquina": None,
    "quantidade": None,
    "dados_tecnicos": {},
    "observacoes": [],
}


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


@dataclass
class CaptureResult:
    audio: bytes
    reason: str
    disconnected: bool
    total_seconds: float
    max_rms: int


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
    if GROQ_STT_PROMPT:
        fields["prompt"] = GROQ_STT_PROMPT
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
            "User-Agent": "RBK-Vendedor-IA-Gateway/0.5.1",
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
            "User-Agent": "RBK-Vendedor-IA-Gateway/0.5.1",
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


def bool_value(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {
            "true",
            "1",
            "sim",
            "yes",
        }
    return False


def clean_state_text(value: object, max_length: int = 160) -> str | None:
    if value is None:
        return None
    text_value = re.sub(r"\s+", " ", str(value)).strip()
    if not text_value:
        return None
    return text_value[:max_length]


def merge_sales_state(
    current_state: dict,
    incoming_state: object,
) -> dict:
    merged = {
        "nome_cliente": current_state.get("nome_cliente"),
        "produto": current_state.get("produto"),
        "tipo_maquina": current_state.get("tipo_maquina"),
        "marca_maquina": current_state.get("marca_maquina"),
        "modelo_maquina": current_state.get("modelo_maquina"),
        "quantidade": current_state.get("quantidade"),
        "dados_tecnicos": dict(
            current_state.get("dados_tecnicos") or {}
        ),
        "observacoes": list(current_state.get("observacoes") or []),
    }

    if not isinstance(incoming_state, dict):
        return merged

    for key in (
        "nome_cliente",
        "produto",
        "tipo_maquina",
        "marca_maquina",
        "modelo_maquina",
        "quantidade",
    ):
        cleaned = clean_state_text(incoming_state.get(key))
        if cleaned is not None:
            merged[key] = cleaned

    incoming_technical = incoming_state.get("dados_tecnicos")
    if isinstance(incoming_technical, dict):
        for key, value in incoming_technical.items():
            clean_key = clean_state_text(key, max_length=80)
            clean_value = clean_state_text(value, max_length=180)
            if clean_key and clean_value:
                merged["dados_tecnicos"][clean_key] = clean_value

    incoming_notes = incoming_state.get("observacoes")
    if isinstance(incoming_notes, list):
        for item in incoming_notes:
            cleaned = clean_state_text(item, max_length=180)
            if cleaned and cleaned not in merged["observacoes"]:
                merged["observacoes"].append(cleaned)

    merged["observacoes"] = merged["observacoes"][-8:]
    return merged


PRODUCT_KEYWORDS = (
    "carburador",
    "corrente",
    "cilindro",
    "pistão",
    "pistao",
    "vela",
    "filtro de ar",
    "filtro de combustível",
    "filtro de combustivel",
    "sabres",
    "sabre",
    "embreagem",
    "mola de partida",
    "cordão de partida",
    "cordao de partida",
    "bobina",
    "magneto",
    "virabrequim",
)


def canonical_product(transcript: str) -> str | None:
    lowered = transcript.casefold()
    for keyword in PRODUCT_KEYWORDS:
        if keyword in lowered:
            if keyword in {"pistao", "pistão"}:
                return "pistão"
            if keyword in {"filtro de combustivel", "filtro de combustível"}:
                return "filtro de combustível"
            if keyword in {"cordao de partida", "cordão de partida"}:
                return "cordão de partida"
            if keyword == "sabres":
                return "sabre"
            return keyword
    return None


def infer_domain_hints(transcript: str) -> dict:
    """Extrai fatos seguros antes do LLM; não decide compatibilidade."""
    hints: dict = {
        "dados_tecnicos": {},
        "observacoes": [],
    }

    product = canonical_product(transcript)
    if product:
        hints["produto"] = product

    # Stihl MS 170 / MS170 / MS-170: família de motosserras Stihl.
    ms_match = re.search(
        r"\b(?:stihl\s+)?m\s*s[\s-]*(\d{2,4}[a-z]?)\b",
        transcript,
        flags=re.IGNORECASE,
    )
    if ms_match:
        model_number = ms_match.group(1).upper()
        hints.update(
            {
                "tipo_maquina": "motosserra",
                "marca_maquina": "Stihl",
                "modelo_maquina": f"MS {model_number}",
            }
        )
        hints["observacoes"].append(
            "Modelo Stihl identificado pelo prefixo MS."
        )

    # Stihl FS: família usual de roçadeiras. Apenas classifica o equipamento.
    fs_match = re.search(
        r"\b(?:stihl\s+)?f\s*s[\s-]*(\d{2,4}[a-z]?)\b",
        transcript,
        flags=re.IGNORECASE,
    )
    if fs_match:
        model_number = fs_match.group(1).upper()
        hints.update(
            {
                "tipo_maquina": "roçadeira",
                "marca_maquina": "Stihl",
                "modelo_maquina": f"FS {model_number}",
            }
        )
        hints["observacoes"].append(
            "Modelo Stihl identificado pelo prefixo FS."
        )

    return hints


def generate_multiturn_decision(
    transcript: str,
    current_state: dict,
    history: list[dict[str, str]],
) -> dict:
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY não configurada.")

    domain_hints = infer_domain_hints(transcript)

    messages: list[dict[str, str]] = [
        {
            "role": "system",
            "content": MULTITURN_SYSTEM_PROMPT,
        }
    ]
    messages.extend(history[-10:])
    messages.append(
        {
            "role": "user",
            "content": (
                "ESTADO ATUAL EM JSON:\n"
                + json.dumps(
                    current_state,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                + "\n\nNOVA FALA DO CLIENTE:\n"
                + transcript
                + "\n\nAtualize o estado e gere o próximo turno."
            ),
        }
    )

    body = json.dumps(
        {
            "model": GROQ_LLM_MODEL,
            "messages": messages,
            "temperature": 0.1,
            "max_completion_tokens": 320,
            "response_format": {
                "type": "json_object",
            },
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
            "User-Agent": "RBK-Vendedor-IA-Gateway/0.5.1",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(
                response.read().decode("utf-8", errors="replace")
            )
            raw_content = payload["choices"][0]["message"]["content"]
            decision_data = json.loads(raw_content)
    except urllib.error.HTTPError as error:
        body_error = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Groq LLM retornou HTTP {error.code}: {body_error}"
        ) from error
    except (KeyError, IndexError, json.JSONDecodeError) as error:
        raise RuntimeError(
            f"Resposta estruturada inválida da Groq: {error}"
        ) from error

    reply = sanitize_llm_text(
        str(decision_data.get("resposta") or "")
    )
    if not reply:
        reply = (
            "Não consegui definir a próxima pergunta técnica. "
            "Vou encerrar este teste."
        )

    updated_state = merge_sales_state(
        current_state,
        decision_data.get("estado"),
    )
    updated_state = merge_sales_state(
        updated_state,
        domain_hints,
    )
    complete = bool_value(
        decision_data.get("levantamento_completo")
    )
    end_conversation = (
        bool_value(decision_data.get("encerrar"))
        or complete
    )

    return {
        "resposta": reply,
        "encerrar": end_conversation,
        "levantamento_completo": complete,
        "motivo_encerramento": clean_state_text(
            decision_data.get("motivo_encerramento"),
            max_length=160,
        ) or "",
        "estado": updated_state,
    }


def montar_resumo_deterministico(
    estado: dict,
    levantamento_completo: bool,
    resultado: str,
) -> str:
    partes: list[str] = []

    campos = [
        ("Cliente", estado.get("nome_cliente")),
        ("Produto", estado.get("produto")),
        ("Tipo de máquina", estado.get("tipo_maquina")),
        ("Marca", estado.get("marca_maquina")),
        ("Modelo", estado.get("modelo_maquina")),
        ("Quantidade", estado.get("quantidade")),
    ]

    for rotulo, valor in campos:
        if valor not in (None, "", [], {}):
            partes.append(f"{rotulo}: {valor}")

    dados_tecnicos = estado.get("dados_tecnicos")
    if isinstance(dados_tecnicos, dict) and dados_tecnicos:
        tecnicos = ", ".join(
            f"{chave}: {valor}"
            for chave, valor in dados_tecnicos.items()
            if valor not in (None, "", [], {})
        )
        if tecnicos:
            partes.append(f"Dados técnicos: {tecnicos}")

    partes.append(
        "Levantamento técnico completo"
        if levantamento_completo
        else "Levantamento técnico incompleto"
    )
    partes.append(f"Resultado: {resultado}")

    return "; ".join(partes)[:4000]


def persistir_conversa_na_api(payload: dict) -> dict | None:
    if not PERSISTENCIA_VOZ_ATIVA:
        logger.info(
            "Persistência de voz desativada: chamada_externa_id=%s",
            payload.get("chamada_externa_id"),
        )
        return None

    ausentes = [
        nome
        for nome, valor in {
            "API_COMERCIAL_URL": API_COMERCIAL_URL,
            "API_COMERCIAL_KEY": API_COMERCIAL_KEY,
            "PERSISTENCIA_CLIENTE_ID": PERSISTENCIA_CLIENTE_ID,
        }.items()
        if not valor
    ]
    if ausentes:
        raise RuntimeError(
            "Persistência ativa com configuração incompleta: "
            + ", ".join(ausentes)
        )

    url = (
        f"{API_COMERCIAL_URL}/chamadas/"
        "registrar-conversa-voz"
    )
    body = json.dumps(
        payload,
        ensure_ascii=False,
    ).encode("utf-8")

    last_error: Exception | None = None

    for attempt in range(1, 4):
        request = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "X-API-Key": API_COMERCIAL_KEY,
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "RBK-Vendedor-IA-Gateway/0.5.1",
            },
        )

        try:
            with urllib.request.urlopen(
                request,
                timeout=30,
            ) as response:
                response_body = response.read().decode(
                    "utf-8",
                    errors="replace",
                )
                result = json.loads(response_body)

                logger.info(
                    "PERSISTENCIA API: chamada_externa_id=%s "
                    "http=%s criada=%s idempotente=%s chamada_id=%s "
                    "interacoes=%s",
                    payload.get("chamada_externa_id"),
                    response.status,
                    result.get("criada"),
                    result.get("idempotente"),
                    (
                        result.get("chamada") or {}
                    ).get("id"),
                    result.get("interacoes_registradas"),
                )
                return result

        except urllib.error.HTTPError as error:
            error_body = error.read().decode(
                "utf-8",
                errors="replace",
            )
            last_error = RuntimeError(
                f"API Comercial retornou HTTP {error.code}: "
                f"{error_body}"
            )
            if error.code < 500 or attempt >= 3:
                raise last_error from error

        except (
            urllib.error.URLError,
            TimeoutError,
            json.JSONDecodeError,
        ) as error:
            last_error = error
            if attempt >= 3:
                raise RuntimeError(
                    "Não foi possível persistir a conversa na "
                    "API Comercial."
                ) from error

        time.sleep(attempt)

    if last_error is not None:
        raise RuntimeError(
            "Falha desconhecida ao persistir conversa."
        ) from last_error

    return None


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


async def read_audiosocket_frame(
    reader: asyncio.StreamReader,
) -> tuple[int, bytes] | None:
    header = await read_exactly_or_none(reader, HEADER_SIZE)
    if header is None:
        return None

    frame_type = header[0]
    payload_length = struct.unpack(">H", header[1:3])[0]
    payload = await read_exactly_or_none(reader, payload_length)
    if payload is None:
        return None

    return frame_type, payload


async def capture_utterance(
    reader: asyncio.StreamReader,
    session_uuid: str,
    stats: SessionStats,
    discard_seconds: float,
) -> CaptureResult:
    captured_audio = bytearray()
    pre_roll: deque[bytes] = deque()
    pre_roll_duration = 0.0
    speech_started = False
    speech_duration = 0.0
    silence_duration = 0.0
    total_capture_duration = 0.0
    local_max_rms = 0
    remaining_discard = max(0.0, discard_seconds)

    while True:
        frame = await read_audiosocket_frame(reader)
        if frame is None:
            return CaptureResult(
                audio=bytes(captured_audio),
                reason="conexao_encerrada",
                disconnected=True,
                total_seconds=total_capture_duration,
                max_rms=local_max_rms,
            )

        frame_type, payload = frame

        if frame_type == TYPE_HANGUP:
            logger.info(
                "Hangup recebido durante captura: uuid=%s",
                session_uuid,
            )
            return CaptureResult(
                audio=bytes(captured_audio),
                reason="hangup",
                disconnected=True,
                total_seconds=total_capture_duration,
                max_rms=local_max_rms,
            )

        if frame_type == TYPE_DTMF:
            stats.frames_dtmf += 1
            digit = payload.decode("ascii", errors="replace")
            logger.info(
                "DTMF recebido: uuid=%s digito=%s",
                session_uuid,
                digit,
            )
            if digit == "#" and speech_started:
                return CaptureResult(
                    audio=bytes(captured_audio),
                    reason="dtmf_finalizacao",
                    disconnected=False,
                    total_seconds=total_capture_duration,
                    max_rms=local_max_rms,
                )
            continue

        if frame_type == TYPE_ERROR:
            logger.error(
                "Erro recebido do Asterisk: uuid=%s codigo=%s",
                session_uuid,
                payload.hex() or "sem_codigo",
            )
            return CaptureResult(
                audio=bytes(captured_audio),
                reason="erro_asterisk",
                disconnected=True,
                total_seconds=total_capture_duration,
                max_rms=local_max_rms,
            )

        if frame_type != TYPE_AUDIO_8KHZ:
            continue

        stats.frames_audio += 1
        stats.bytes_audio += len(payload)
        frame_duration = len(payload) / (
            SAMPLE_RATE * SAMPLE_WIDTH
        )

        if remaining_discard > 0:
            remaining_discard = max(
                0.0,
                remaining_discard - frame_duration,
            )
            continue

        total_capture_duration += frame_duration
        rms = pcm_rms(payload)
        local_max_rms = max(local_max_rms, rms)
        stats.max_rms = max(stats.max_rms, rms)
        is_speech = rms >= VAD_RMS_THRESHOLD

        if not speech_started:
            pre_roll.append(payload)
            pre_roll_duration += frame_duration

            while (
                pre_roll
                and pre_roll_duration > PRE_ROLL_SECONDS
            ):
                removed = pre_roll.popleft()
                pre_roll_duration -= len(removed) / (
                    SAMPLE_RATE * SAMPLE_WIDTH
                )

            if is_speech:
                speech_started = True
                for buffered_frame in pre_roll:
                    captured_audio.extend(buffered_frame)
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
                speech_duration >= MIN_SPEECH_SECONDS
                and silence_duration >= SILENCE_SECONDS
            ):
                return CaptureResult(
                    audio=bytes(captured_audio),
                    reason="silencio",
                    disconnected=False,
                    total_seconds=total_capture_duration,
                    max_rms=local_max_rms,
                )

        if total_capture_duration >= MAX_CAPTURE_SECONDS:
            return CaptureResult(
                audio=bytes(captured_audio),
                reason=(
                    "tempo_maximo"
                    if speech_started
                    else "sem_fala"
                ),
                disconnected=False,
                total_seconds=total_capture_duration,
                max_rms=local_max_rms,
            )


async def handle_multiturn_session(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    session_uuid: str,
    stats: SessionStats,
) -> None:
    state = json.loads(json.dumps(INITIAL_SALES_STATE))
    history: list[dict[str, str]] = []
    recorded_turns: list[dict[str, object]] = []
    no_speech_attempts = 0
    complete = False
    end_reason = "triagem_incompleta"
    result = "triagem_incompleta"

    call_external_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc)
    started_monotonic = time.perf_counter()

    logger.info(
        "Conversa persistível iniciada: uuid=%s "
        "chamada_externa_id=%s cliente_id=%s",
        session_uuid,
        call_external_id,
        PERSISTENCIA_CLIENTE_ID or "não_configurado",
    )

    greeting_duration = await speak_text(
        writer,
        MULTITURN_GREETING_TEXT,
        session_uuid,
    )
    await send_tone(writer)
    discard_seconds = greeting_duration + 0.45

    for turn_number in range(1, MAX_CONVERSATION_TURNS + 1):
        logger.info(
            "Aguardando turno do cliente: uuid=%s turno=%s/%s",
            session_uuid,
            turn_number,
            MAX_CONVERSATION_TURNS,
        )

        capture = await capture_utterance(
            reader=reader,
            session_uuid=session_uuid,
            stats=stats,
            discard_seconds=discard_seconds,
        )
        discard_seconds = 0.0

        if capture.disconnected:
            end_reason = capture.reason
            result = (
                "cliente_desligou"
                if capture.reason in {
                    "hangup",
                    "conexao_encerrada",
                }
                else "falha_canal"
            )
            logger.info(
                "Conversa encerrada pelo canal: uuid=%s motivo=%s",
                session_uuid,
                capture.reason,
            )
            break

        if not capture.audio:
            no_speech_attempts += 1
            logger.warning(
                "Nenhuma fala no turno: uuid=%s turno=%s "
                "tentativa=%s segundos=%.2f max_rms=%s",
                session_uuid,
                turn_number,
                no_speech_attempts,
                capture.total_seconds,
                capture.max_rms,
            )

            if no_speech_attempts >= 2:
                await speak_text(
                    writer,
                    (
                        "Não consegui ouvir sua resposta. "
                        "Vou encerrar este teste agora."
                    ),
                    session_uuid,
                )
                end_reason = "sem_fala"
                result = "sem_fala"
                break

            retry_duration = await speak_text(
                writer,
                (
                    "Não ouvi sua resposta. "
                    "Fale depois do sinal."
                ),
                session_uuid,
            )
            await send_tone(writer)
            discard_seconds = retry_duration + 0.45
            continue

        no_speech_attempts = 0

        logger.info(
            "Enviando áudio para Groq: uuid=%s turno=%s motivo=%s "
            "segundos=%.2f bytes=%s max_rms=%s",
            session_uuid,
            turn_number,
            capture.reason,
            len(capture.audio) / (SAMPLE_RATE * SAMPLE_WIDTH),
            len(capture.audio),
            capture.max_rms,
        )

        transcript = await asyncio.to_thread(
            transcribe_with_groq,
            capture.audio,
        )
        logger.info(
            "TRANSCRICAO GROQ: uuid=%s turno=%s texto=%r",
            session_uuid,
            turn_number,
            transcript,
        )

        if not transcript:
            retry_duration = await speak_text(
                writer,
                (
                    "Não consegui entender o áudio. "
                    "Repita depois do sinal."
                ),
                session_uuid,
            )
            await send_tone(writer)
            discard_seconds = retry_duration + 0.45
            continue

        try:
            decision = await asyncio.to_thread(
                generate_multiturn_decision,
                transcript,
                state,
                history,
            )
        except Exception:
            logger.exception(
                "Falha na decisão multi-turno: uuid=%s turno=%s",
                session_uuid,
                turn_number,
            )
            await speak_text(
                writer,
                (
                    "Tive uma falha ao processar sua resposta. "
                    "Vou encerrar este teste agora."
                ),
                session_uuid,
            )
            recorded_turns.append(
                {
                    "numero": turn_number,
                    "cliente": transcript,
                    "agente": (
                        "Tive uma falha ao processar sua resposta. "
                        "Vou encerrar este teste agora."
                    ),
                }
            )
            end_reason = "falha_processamento"
            result = "falha_processamento"
            break

        state = decision["estado"]
        reply = decision["resposta"]
        complete = decision["levantamento_completo"]

        recorded_turns.append(
            {
                "numero": turn_number,
                "cliente": transcript,
                "agente": reply,
            }
        )

        history.append(
            {
                "role": "user",
                "content": transcript,
            }
        )
        history.append(
            {
                "role": "assistant",
                "content": reply,
            }
        )

        logger.info(
            "DECISAO LLM: uuid=%s turno=%s encerrar=%s "
            "completo=%s motivo=%r resposta=%r",
            session_uuid,
            turn_number,
            decision["encerrar"],
            complete,
            decision["motivo_encerramento"],
            reply,
        )
        logger.info(
            "ESTADO COMERCIAL: uuid=%s turno=%s estado=%s",
            session_uuid,
            turn_number,
            json.dumps(
                state,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        )

        reached_limit = (
            turn_number >= MAX_CONVERSATION_TURNS
            and not decision["encerrar"]
        )

        if reached_limit:
            final_reply = (
                "Registrei as informações disponíveis. "
                "Este teste atingiu o limite de perguntas e será encerrado."
            )
            recorded_turns[-1]["agente"] = (
                f"{reply} {final_reply}"
            )
            await speak_text(
                writer,
                final_reply,
                session_uuid,
            )
            end_reason = "limite_turnos"
            result = "limite_turnos"
            break

        reply_duration = await speak_text(
            writer,
            reply,
            session_uuid,
        )

        if decision["encerrar"]:
            end_reason = (
                decision["motivo_encerramento"]
                or (
                    "levantamento_completo"
                    if complete
                    else "encerrado_pelo_cliente"
                )
            )
            result = (
                "triagem_completa"
                if complete
                else "cliente_encerrou"
            )
            break

        await send_tone(writer)
        discard_seconds = reply_duration + 0.45

    finished_at = datetime.now(timezone.utc)
    duration_seconds = max(
        0,
        int(round(time.perf_counter() - started_monotonic)),
    )

    if complete and result == "triagem_incompleta":
        result = "triagem_completa"
        end_reason = "levantamento_completo"

    summary = montar_resumo_deterministico(
        state,
        complete,
        result,
    )

    logger.info(
        "CONVERSA FINAL: uuid=%s chamada_externa_id=%s "
        "resultado=%s completo=%s motivo=%s estado=%s",
        session_uuid,
        call_external_id,
        result,
        complete,
        end_reason,
        json.dumps(
            state,
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    )

    persistence_payload = {
        "cliente_id": PERSISTENCIA_CLIENTE_ID,
        "vendedor_codigo": PERSISTENCIA_VENDEDOR_CODIGO,
        "provedor": "asterisk_audiosocket",
        "chamada_externa_id": call_external_id,
        "numero_origem": PERSISTENCIA_NUMERO_ORIGEM or None,
        "numero_destino": PERSISTENCIA_NUMERO_DESTINO or None,
        "direcao": (
            PERSISTENCIA_DIRECAO
            if PERSISTENCIA_DIRECAO in {"entrada", "saida"}
            else "entrada"
        ),
        "inicio_em": started_at.isoformat(),
        "fim_em": finished_at.isoformat(),
        "duracao_segundos": duration_seconds,
        "resumo": summary,
        "sentimento": None,
        "intencao": "consulta_peca",
        "resultado": result,
        "levantamento_completo": complete,
        "motivo_encerramento": end_reason,
        "estado_comercial": state,
        "turnos": recorded_turns,
        "modelos": {
            "stt": GROQ_STT_MODEL,
            "llm": GROQ_LLM_MODEL,
            "tts": Path(PIPER_VOICE_MODEL).name,
        },
        "dados_extraidos": {
            "audiosocket_uuid": session_uuid,
            "max_rms": stats.max_rms,
            "frames_audio": stats.frames_audio,
            "bytes_audio": stats.bytes_audio,
            "modo": "multiturn",
        },
    }

    if PERSISTENCIA_AGENDA_ID:
        persistence_payload["agenda_id"] = (
            PERSISTENCIA_AGENDA_ID
        )

    try:
        await asyncio.to_thread(
            persistir_conversa_na_api,
            persistence_payload,
        )
    except Exception:
        logger.exception(
            "FALHA PERSISTENCIA API: uuid=%s "
            "chamada_externa_id=%s",
            session_uuid,
            call_external_id,
        )


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
                elif session_uuid == MULTITURN_UUID:
                    mode = "multiturn"
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

                elif mode == "multiturn":
                    await handle_multiturn_session(
                        reader=reader,
                        writer=writer,
                        session_uuid=session_uuid,
                        stats=stats,
                    )
                    await send_frame(writer, TYPE_HANGUP)
                    return

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
        "Gateway de voz RBK v0.5.1 iniciado: endereços=%s "
        "echo_uuid=%s stt_uuid=%s conversation_uuid=%s "
        "multiturn_uuid=%s modelo_stt=%s modelo_llm=%s "
        "max_turnos=%s persistencia_ativa=%s "
        "cliente_persistencia=%s silencio_final=%.2fs "
        "min_fala=%.2fs",
        addresses,
        ECHO_UUID,
        STT_UUID,
        CONVERSATION_UUID,
        MULTITURN_UUID,
        GROQ_STT_MODEL,
        GROQ_LLM_MODEL,
        MAX_CONVERSATION_TURNS,
        PERSISTENCIA_VOZ_ATIVA,
        PERSISTENCIA_CLIENTE_ID or "não_configurado",
        SILENCE_SECONDS,
        MIN_SPEECH_SECONDS,
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
