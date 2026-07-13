# RBK Vendedor IA — Gateway de Voz v0.7.2

- remove a orientação para falar depois do sinal;
- desativa o sinal entre turnos por padrão;
- melhora a captura de respostas curtas;
- reduz a pausa para detectar o fim da fala;
- elimina a descrição repetida antes da consulta;
- não repete a descrição inteira após adicionar a quantidade;
- usa decisão local rápida para produtos reconhecidos;
- pesquisa descrição e preço sem consultar estoque.

Variáveis novas:

```env
MULTITURN_TONE_ENABLED=false
POST_TTS_ECHO_GUARD_SECONDS=0.08
BUSCA_RAPIDA_LOCAL_ATIVA=true
MAX_SEM_FALA_TENTATIVAS=3
```
