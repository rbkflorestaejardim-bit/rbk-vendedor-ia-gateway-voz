# RBK Vendedor IA — Gateway de Voz v0.5.1

Correção de latência e interpretação técnica.

## Alterações

- reduz o silêncio de fechamento do turno de 1,2 s para 0,70 s;
- reduz a fala mínima válida para 0,45 s;
- prioriza `whisper-large-v3` para maior precisão;
- envia glossário técnico ao STT;
- preserva códigos de modelos na transcrição;
- adiciona classificação determinística de modelos Stihl `MS` e `FS`;
- interpreta `carburador para MS 170` como:
  - produto: carburador;
  - tipo de máquina: motosserra;
  - marca: Stihl;
  - modelo: MS 170.

A classificação não confirma compatibilidade. Ela apenas estrutura corretamente o pedido antes das perguntas técnicas.

A API Comercial 0.7.0 e o Asterisk não precisam ser alterados.
