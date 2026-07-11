# RBK Vendedor IA — Gateway de Voz

Gateway TCP mínimo para validar o protocolo AudioSocket do Asterisk.

## Objetivo desta versão

Receber o áudio PCM enviado pelo Asterisk e devolvê-lo imediatamente para a
chamada. É um teste de eco feito através de um serviço separado, preparando a
arquitetura para STT, LLM e TTS.

## Porta interna

```text
9019/TCP
```

Não publique essa porta na internet. O Asterisk acessará o serviço pela rede
interna do projeto Easypanel.

## Variáveis

```env
HOST=0.0.0.0
PORT=9019
LOG_LEVEL=INFO
ECHO_AUDIO=true
```

## Protocolo tratado

- `0x00`: encerramento
- `0x01`: UUID da chamada
- `0x03`: DTMF
- `0x10`: PCM linear assinado, 16-bit, 8 kHz, mono
- `0xFF`: erro

## Próxima integração

Depois do eco validado, o processamento será substituído por:

```text
Asterisk
→ Gateway de Voz
→ reconhecimento de fala
→ agente comercial
→ síntese de voz
→ Asterisk
```
