# RBK Vendedor IA — Gateway de Voz v0.2.0

Esta versão mantém o eco do ramal `602` e adiciona transcrição real pela Groq
no ramal `603`.

## Modos por UUID

- `11111111-1111-4111-8111-111111111111`: eco AudioSocket.
- `22222222-2222-4222-8222-222222222222`: captura de fala e STT Groq.

## Funcionamento do ramal 603

1. O Asterisk reproduz um bip.
2. O usuário fala uma frase curta.
3. O gateway detecta silêncio.
4. O áudio PCM é convertido para WAV.
5. O WAV é enviado ao modelo `whisper-large-v3-turbo`.
6. A transcrição aparece no log como `TRANSCRICAO GROQ`.

Nesta etapa ainda não há resposta falada da IA.
