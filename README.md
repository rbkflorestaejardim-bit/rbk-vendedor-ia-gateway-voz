# RBK Vendedor IA — Gateway de Voz v0.6.3

O gateway passa a respeitar a melhor correspondência calculada pela API.

Exemplo: ao pedir uma luva de malha pigmentada branca, um produto preto com
estoque não substitui a opção branca indisponível.

Carlos oferece somente produtos que:

1. pertencem ao melhor nível de correspondência do pedido;
2. possuem preço válido;
3. possuem estoque disponível.

Se os melhores produtos estiverem indisponíveis, a chamada gera a pendência
de venda futura já criada na Etapa 29.
