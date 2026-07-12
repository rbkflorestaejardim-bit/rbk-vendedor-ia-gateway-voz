# RBK Vendedor IA — Gateway de Voz v0.6.1

Carlos só oferece ao cliente produtos com preço válido e estoque disponível.

Produtos compatíveis sem preço ou sem estoque permanecem registrados
internamente, mas não são apresentados como opção de compra.

Exemplo: se o SKU 12933 tem preço e estoque e o SKU 2452 não tem nenhum dos
dois, Carlos informa somente o SKU 12933.

Se nenhum produto compatível tiver preço e estoque, Carlos informa que não há
opção disponível e registra a solicitação para atendimento posterior.
