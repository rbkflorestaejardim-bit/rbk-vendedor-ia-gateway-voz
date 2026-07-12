# RBK Vendedor IA — Gateway de Voz v0.5.2

Correção do comportamento comercial do Carlos.

## Nova regra principal

Carlos é vendedor de peças, não mecânico.

Ao ouvir:

```text
Preciso de um carburador para MS 170.
```

o estado esperado é:

```json
{
  "produto": "carburador",
  "tipo_maquina": "motosserra",
  "marca_maquina": "Stihl",
  "modelo_maquina": "MS 170",
  "acao_proxima": "buscar_produto",
  "termo_busca": "carburador Stihl MS 170"
}
```

A resposta será curta:

```text
Certo. Vou procurar carburador para Stihl MS 170 e consultar preço e
disponibilidade.
```

## O que foi removido

- perguntas sobre defeito;
- perguntas sobre sintomas;
- investigação mecânica;
- exigência de quantidade antes de pesquisar;
- repetição contínua do pedido;
- perguntas técnicas sem uma ambiguidade real retornada pelo catálogo.

## Fluxo

- peça + modelo: preparar busca e encerrar a triagem;
- peça sem marca/modelo: perguntar marca e modelo;
- peça + marca sem modelo: perguntar somente o modelo;
- código ou referência exata: preparar busca;
- cliente pede encerramento: encerrar.

O Olist ainda não está conectado ao gateway. Nesta versão, a ação
`buscar_produto` e o `termo_busca` ficam estruturados e persistidos para a
próxima etapa de integração.
