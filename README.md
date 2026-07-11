# RBK Vendedor IA — Gateway de Voz v0.3.0

Primeiro ciclo completo de voz:

```text
fala do cliente
→ Whisper Groq
→ Llama 3.1 8B Groq
→ Piper TTS local
→ resposta na ligação
```

## Ramais

- `602`: eco pelo gateway.
- `603`: transcrição Groq.
- `604`: uma interação completa com STT, LLM e TTS.

## Voz local

O Dockerfile instala `piper-tts==1.4.2` e baixa a voz
`pt_BR-faber-medium`.

O modelo Faber é pt-BR, qualidade medium, 22.050 Hz e tem dataset CC0.
O Piper é distribuído sob GPL-3.0.

## Limites desta versão

- Um único turno de conversa.
- Uma chamada simultânea.
- Sem interrupção da fala da IA.
- Sem consulta ao ERP.
- A IA não pode informar preço, estoque ou compatibilidade.
