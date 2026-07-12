# RBK Vendedor IA — Gateway de Voz v0.7.0

## Etapa 31A

O ramal 605 passa a trabalhar com orçamento de múltiplos itens:

1. pesquisa o produto;
2. confirma a opção;
3. pergunta a quantidade;
4. adiciona ao rascunho;
5. pergunta qual outro produto o cliente precisa;
6. quando o cliente encerra a lista, inicia ofertas do encarte;
7. oferece um produto por vez, sem mencionar estoque;
8. para após o limite de recusas;
9. resume o carrinho e solicita confirmação.

## Variáveis novas

```env
MAX_CONVERSATION_TURNS=24
ORCAMENTO_IA_ATIVO=true
ENCARTE_OFERTAS_ATIVAS=true
ENCARTE_QUANTIDADE_OFERTAS=5
ENCARTE_MAX_RECUSAS_CONSECUTIVAS=2
```

`ENCARTE_QUANTIDADE_OFERTAS` aceita de 3 a 12.

Produtos do encarte são oferecidos desde que tenham preço na Olist,
independentemente do estoque. Nenhuma mensagem de verificação de
disponibilidade é falada ao cliente.
