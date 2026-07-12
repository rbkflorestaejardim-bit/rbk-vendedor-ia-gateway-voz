# RBK Vendedor IA — Gateway de Voz v0.7.1

## Correção

A versão 0.7.0 ainda exigia preço e estoque para aceitar produtos do catálogo.
Isso fazia Carlos falar em indisponibilidade e encerrar a ligação.

A versão 0.7.1 aplica:

- produto com preço válido pode entrar no orçamento independentemente do estoque;
- estoque não é falado durante a seleção;
- produto sem preço é registrado para revisão;
- produto não encontrado é registrado para revisão;
- falha de consulta é registrada para revisão;
- nenhuma dessas situações encerra a conversa imediatamente;
- Carlos pergunta qual outro produto o cliente precisa.

As ofertas do encarte continuam sem mencionar estoque ou disponibilidade.
