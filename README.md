# RBK Vendedor IA — Gateway de Voz v0.6.0

O ramal `605` passa a consultar o catálogo real da API Comercial.

## Fluxo

```text
cliente pede a peça
→ Groq identifica produto, marca e modelo
→ gateway chama /olist/produtos/pesquisar
→ API pesquisa o catálogo sincronizado do Olist
→ Carlos informa descrição, preço e estoque
```

## Comportamento

- Um produto: Carlos informa código, descrição, preço e estoque.
- Vários produtos: Carlos apresenta as duas primeiras opções e pede
  “primeira” ou “segunda”. O cliente também pode informar o SKU.
- Nenhum produto: Carlos pergunta uma vez pelo código ou referência.
- Erro de API: registra a solicitação para continuidade.

Preço e estoque vêm exclusivamente da API Comercial. O resultado e a opção
selecionada são persistidos junto à chamada.

## Variáveis novas

```env
CONSULTA_CATALOGO_ATIVA=true
CONSULTA_CATALOGO_LIMITE=5
CONSULTA_CATALOGO_TIMEOUT=25
MAX_OPCOES_FALADAS=2
MAX_TENTATIVAS_CATALOGO=2
```

Não há alteração no Asterisk nem na API Comercial nesta etapa.
