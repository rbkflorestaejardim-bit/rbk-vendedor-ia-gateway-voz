# RBK Vendedor IA — Gateway de Voz v0.5.0

Esta versão preserva os ramais `602`, `603`, `604` e `605` e adiciona
persistência da conversa multi-turno na API Comercial.

## Dados registrados

Ao encerrar uma chamada no ramal `605`, o gateway envia:

- identificador único da chamada;
- horários e duração;
- cada fala do cliente;
- cada resposta do Carlos;
- resumo determinístico;
- estado comercial final;
- dados técnicos;
- motivo de encerramento;
- modelos STT, LLM e TTS utilizados.

## Variáveis novas

```env
API_COMERCIAL_URL=https://api-comercial.129-121-37-172.sslip.io
API_COMERCIAL_KEY=...
PERSISTENCIA_VOZ_ATIVA=true
PERSISTENCIA_CLIENTE_ID=<UUID do cliente de teste>
PERSISTENCIA_AGENDA_ID=
PERSISTENCIA_VENDEDOR_CODIGO=CARLOS_RS
PERSISTENCIA_DIRECAO=entrada
PERSISTENCIA_NUMERO_ORIGEM=7001
PERSISTENCIA_NUMERO_DESTINO=605
```

O ramal e o `extensions.conf` não mudam nesta etapa.
