# RBK Vendedor IA — Gateway de Voz v0.4.0

Esta versão adiciona conversa contínua em turnos, preservando os ramais
validados anteriormente.

## Ramais

- `602`: eco pelo gateway.
- `603`: transcrição Groq.
- `604`: um turno com STT, LLM e Piper.
- `605`: conversa técnica contínua com memória de contexto.

## Fluxo do ramal 605

```text
Carlos se apresenta
→ cliente responde
→ Whisper transcreve
→ LLM atualiza o estado comercial
→ Carlos faz uma pergunta técnica
→ cliente responde novamente
→ processo continua até conclusão ou limite
```

## Estado comercial mantido durante a ligação

- nome do cliente;
- produto;
- marca da máquina;
- modelo da máquina;
- quantidade;
- dados técnicos;
- observações.

O estado final é registrado nos logs como `CONVERSA FINAL`. Ainda não é
gravado no PostgreSQL nem enviado ao CRM.

## Regras de segurança comercial

- uma pergunta por turno;
- não repetir dados já respondidos;
- não inventar preço, estoque, prazo ou compatibilidade;
- encerrar quando o cliente solicitar;
- limitar a conversa a oito turnos por padrão;
- para corrente de motosserra, priorizar passo, calibre e elos.

## Limites

- uma chamada simultânea no piloto;
- sem interrupção da fala da IA;
- sem consulta ao Olist;
- sem persistência no CRM nesta versão.
