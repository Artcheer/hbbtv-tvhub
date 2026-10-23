# TVHub — Twitch, Kick e TV na sua tela

Servidor Python com uma interface leve para **Chrome 47 / SRAF 4.0**, a base de compatibilidade registrada neste projeto. O computador resolve as transmissões e os chats; a TV acessa o app pela rede local.

## Abrir o app

No Windows, execute **`RUN_IPTV.bat`**. O navegador abre quando o servidor está pronto. Mantenha essa janela aberta enquanto assiste.

Na TV, digite o endereço mostrado no terminal, por exemplo:

```text
http://192.168.1.2:8080/?tv=1&remote=1
```

O botão **Leve para a sua TV** também mostra esse endereço. Computador e TV precisam estar na mesma rede. `tv=1` amplia a interface; `remote=1` ativa o controle por foco e oculta o cursor. Os botões de TV e controle remoto no topo alternam esses modos separadamente.

Depois de atualizar os arquivos do app, feche a janela antiga do servidor e execute `RUN_IPTV.bat` novamente. Feche e reabra a página na TV para carregar a versão atualizada da interface.

Para iniciar pelo terminal:

```powershell
.\.venv\Scripts\python.exe app.py
```

Para mudar a porta, defina `TVHUB_PORT` antes de iniciar. O padrão é `8080`.

## O que mudou

- Interface com menu lateral, filtros por plataforma e modo ampliado para TV.
- Navegação por setas/OK, foco visível, modo sem cursor e adaptação dos movimentos de mouse enviados por alguns navegadores de TV.
- Favoritos e histórico salvos no navegador. O histórico só registra reproduções iniciadas.
- Pesquisa de canais Twitch/Kick com resultados exatos e nomes parecidos, indicação de live/offline, favoritos e teclado virtual. **Abrir direto** continua disponível.
- Aba **Descobrir** com lives em português, ordenação por audiência, filtros de jogo/assunto e pesquisa de categorias nas duas plataformas.
- Miniaturas estáticas de Twitch, Kick e TV, carregadas apenas nos itens visíveis. A página inicial continua sem imagens remotas ou consultas de descoberta.
- Player com chat lateral, pausa, som, tela cheia e seleção de qualidade quando disponível.
- IPTV por país/categoria, carregamento em páginas de 60 canais e busca em toda a lista selecionada.
- Aba **Meus canais** com a lista própria do usuário: edite `canais.txt` (uma linha por canal, formato `link;nome_do_canal`) e use **Recarregar canais** — sem reiniciar o servidor.
- Reconexão dos chats, mensagens de erro compreensíveis e cancelamento de requisições ao sair do player.

## Controle remoto

| Botão | Ação |
| --- | --- |
| Setas | Navegar pelos botões e canais |
| OK / Enter | Selecionar; mostrar controles quando estiverem ocultos |
| Voltar / Esc | Fechar diálogo ou voltar aos canais |
| Amarelo | Abrir busca |
| Verde | Mostrar/ocultar chat no player |
| Vermelho | Favoritar canal no player |
| Azul | Tela cheia, se o navegador permitir |
| Play / Pause / Stop | Reproduzir, pausar ou voltar aos canais |
| M / botão direito | Voltar ao mouse quando o modo controle estiver ativo |

No computador, `/` abre a busca, `C` alterna o chat e `F` alterna a tela cheia. Na busca, o teclado físico e o virtual funcionam juntos. As teclas coloridas e de mídia dependem do controle/navegador. Em um ambiente HbbTV com OIPF, o app solicita o conjunto de teclas apropriado pela API `keyset`.

No **modo controle**, use **OK** sobre um seletor de idioma, jogo ou qualidade para editar. O contorno fica amarelo: **↑/↓** escolhem, **OK** confirma e **Voltar** cancela. Fora da edição, as setas passam para outro elemento.

O modo controle inicia automaticamente em navegadores identificados como TV/Chrome antigo, nos endereços com `tv=1`/`remote=1`, e pode ser ativado pelo botão com ícone de controle. **O quadrado verde é a seleção mantida pelo app**: o ponteiro não pode substituir essa seleção ao clicar ou tentar focar outro botão. O OK usa o elemento selecionado, incluindo quando o navegador envia um clique sintético.

Quando o navegador entrega setas reais, os movimentos do cursor são ignorados durante esse modo. Quando o firmware envia apenas movimentos de mouse, eles são convertidos em navegação por foco; quando disponível, a captura do ponteiro permite continuar além das bordas da tela. Use o botão de controle, **M**, botão direito ou `remote=0` para usar o mouse novamente.

O recebimento das teclas e a captura do ponteiro dependem do navegador da TV. Se o firmware consumir os eventos antes de entregá-los à página, será necessário alternar o modo de cursor nas opções do próprio navegador. O comportamento na TV física ainda precisa ser conferido.

## Pesquisa, descoberta e miniaturas

Na busca, digite um nome e escolha **Pesquisar canais**. A lista traz canais reais, prioriza o nome exato e permite assistir ou favoritar. **Abrir direto** abre o nome/link informado sem depender do catálogo de pesquisa. Links completos também podem ser abertos com Enter.

Em **Descobrir**, escolha Twitch ou Kick, idioma e jogo/assunto. **Procurar outra categoria** pesquisa jogos e temas além dos mais populares. **Mostrar mais lives** acrescenta lotes de 12 canais. Os catálogos públicos têm limites: a Twitch fornece até 30 entradas na lista geral e até 60 por categoria nesta integração; a Kick consulta até 300 transmissões e filtra o idioma no servidor. A lista não pretende reunir todos os canais existentes. Consultas têm cache curto, e os endpoints públicos podem mudar ou ficar indisponíveis.

As miniaturas são JPEG de **320×180**, sem animação ou reprodução automática, com até duas cargas simultâneas na interface. Imagens distantes da área visível são liberadas. Não há atualização contínua das imagens; elas servem como referência recente e ficam em cache por aproximadamente dois minutos. O botão **Miniaturas** permite desativá-las, e a preferência é salva no navegador.

Na Twitch/Kick, uma live usa a imagem fornecida pela plataforma; canais offline usam o avatar quando disponível. Na TV, o computador tenta capturar um quadro do sinal. Se não conseguir, usa o logotipo disponível ou mantém as iniciais do canal.

As capturas de TV usam **FFmpeg no computador servidor**, com tempo e número de processos limitados. Ele já foi encontrado neste computador. Em outra instalação, deixe `ffmpeg` disponível no `PATH` para obter os quadros; sem ele, os logotipos e os demais recursos continuam funcionando. A TV recebe apenas a imagem pronta.

## Chats

**Chat leve** é o padrão para a TV. Exibe mensagens reais, nomes, emotes e identificadores de moderador/assinante quando fornecidos pela plataforma. Funciona em **modo de leitura**, sem pedir senha ou token. O tamanho do texto pode ser alterado no botão **A+**.

- Twitch: o servidor mantém uma conexão IRC por TLS e a TV consulta as novas mensagens a cada 1,5 segundo.
- Kick: o servidor consulta as mensagens públicas recentes, com atualização da interface a cada 3,5 segundos. Em canais muito movimentados, esse modo pode não mostrar todo o fluxo.
- O navegador mantém no máximo 100 mensagens na tela. Ao ocultar o chat ou sair do player, as consultas são interrompidas. Conexões Twitch sem uso são encerradas após aproximadamente 75 segundos.

**Chat do site** incorpora a página original da plataforma. É uma opção para navegadores capazes de executar o site atual; o Chrome 47 da TV pode não ser suficiente. Autenticação, cookies e permissões do site continuam sob controle da plataforma. **Abrir chat original** abre a página oficial separadamente para entrar na conta e conversar.

O modo leve é independente da página oficial: o vídeo e o chat da TV não precisam carregar os aplicativos web atuais da Twitch/Kick.

## Meus canais (lista própria)

A aba **Meus canais** mostra uma lista de streams escolhida por você. Os canais ficam no arquivo **`canais.txt`**, na pasta do servidor (em instaladores com o executável, junto do `TVHub.exe`). Uma linha por canal, com o **link primeiro** e o **nome depois**, separados por ponto e vírgula:

```text
https://servidor.example/stream.m3u8;Canal Aberto HD
https://servidor.example/live/index.m3u8;Portal do Esporte
https://servidor.example/stream.m3u8;Meu Canal;https://logo.example/meu-canal.png
```

- O campo de logotipo (terceiro, opcional) é a URL de uma imagem.
- Linhas começadas por `#` são anotações e são ignoradas; linhas com erro aparecem no terminal do servidor e são puladas.
- O servidor relê o arquivo quando ele muda: salve e use **Recarregar canais** na aba, sem reiniciar o app.
- Nomes e endereços que não estejam em `http://`/`https://` não são aceitos; vídeos MP4 diretos e master `.m3u8` funcionam como os canais da aba Canais de TV, incluindo o proxy e a adaptação de vídeo.
- "Filtrar lista" busca pelo nome dentro da lista carregada.

## Instalação em um computador novo

Use Python 3.10 ou mais recente no **computador servidor**. A TV não precisa instalar Python.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Se o ambiente foi criado com `uv` e não possui `pip`:

```powershell
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
```

Edite `CHANNELS` em `app.py` para alterar os canais iniciais. Também é possível abrir qualquer canal válido pela busca e adicioná-lo aos favoritos.

## Executáveis (releases)

Cada versão marcada com tag (ex.: `v1.0.0`) é compilada automaticamente pelo Actions em executáveis únicos, publicados na aba Releases:

- `TVHub-windows-x64.exe` — Windows x64
- `TVHub-linux-x64` — Linux x64

Não é preciso instalar Python: baixe, execute e abra o endereço na TV. O FFmpeg continua consultado no `PATH` para capturas e adaptação de vídeo; sem ele, os demais recursos funcionam. Para mudar a porta, defina `TVHUB_PORT=8081` antes de iniciar (no PowerShell: `$env:TVHUB_PORT='8081'; .\TVHub-windows-x64.exe`).

## Compatibilidade e reprodução

- JavaScript ES5 e XMLHttpRequest: sem `fetch`, arrow functions, módulos ou dependência de um framework no navegador.
- CSS com Flexbox e prefixos compatíveis: sem CSS Grid, variáveis CSS, `gap`, `clamp`, `aspect-ratio` ou `backdrop-filter`.
- Ícones e ilustração locais, sem fontes ou bibliotecas visuais externas.
- HLS nativo tem prioridade quando a TV o declara disponível. Caso contrário, o app usa hls.js 0.12.4 servido pelo computador. Essa versão foi mantida para a base antiga do projeto.
- O proxy reescreve playlists, segmentos, chaves AES e mapas de inicialização, inclusive caminhos relativos. Também encaminha requisições de intervalo de bytes.
- Em IPTV, o proxy prefere as variantes **H.264/AVC** quando o canal anuncia esse formato junto com outros codecs. Isso evita selecionar, por exemplo, o H.265/HEVC de um master misto quando existe uma alternativa H.264. As variantes AVC e suas faixas de áudio são preservadas, sem converter o vídeo no computador.
- Quando o canal anuncia apenas formatos como HEVC/H.265, o computador adapta o vídeo para H.264 Baseline e áudio AAC, até 720p/30 fps. A CNN Brasil é um exemplo de origem que precisa dessa adaptação. Canais com uma variante AVC disponível continuam usando o sinal original.
- Se houver áudio sem imagem em um sinal com informações de codec incompletas, use **Corrigir imagem** nos controles do player para solicitar a adaptação.
- A adaptação usa FFmpeg no computador e pode acrescentar alguns segundos à abertura. Há limite de duas conversões simultâneas; a reprodução libera o processo ao sair e sessões sem consultas expiram após aproximadamente 35 segundos. Os segmentos temporários ficam na pasta temporária do Windows, fora do projeto.
- No HLS nativo, a TV controla a seleção de qualidade; o seletor do app permanece desabilitado.
- Codec, resolução máxima e suporte a HLS ainda dependem do hardware/firmware. Compatibilidade de sintaxe e testes em Chrome atual não substituem a validação na TV física.

O servidor usa Streamlink pelo Python do próprio ambiente, sem depender de um executável global no `PATH`. Canais offline ou serviços indisponíveis apresentam uma opção de tentar novamente.

## Verificação

Testes do servidor, chats, descoberta e miniaturas:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_app.py -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_discovery.py -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_hls_compat.py -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_video_compatibility.py -v
```

Testes de interface com Chrome instalado:

```powershell
uv pip install --python .venv\Scripts\python.exe -r tools\requirements-tests.txt
.\.venv\Scripts\python.exe tools\verificar_interface.py
```

Os testes da interface simulam a mídia para verificar navegação, estados, armazenamento e ciclo do player. A reprodução real e o acesso aos serviços são conferidos separadamente. As novas capturas são geradas em `tests/results/`, pasta ignorada no controle de versão. Consulte [docs/VERIFICACAO.md](docs/VERIFICACAO.md) para os resultados e limites da verificação realizada.

## Estrutura do projeto

```text
HBBTV/
  app.py                    Servidor Flask, APIs e proxy
  chat_service.py           Chats Twitch/Kick
  discovery_service.py      Pesquisa e descoberta
  hls_compat.py             Seleção de variantes compatíveis
  media_previews.py         Miniaturas estáticas
  video_compatibility.py    Adaptação de vídeo no computador
  RUN_IPTV.bat              Iniciador do Windows
  canais.txt                Lista própria de streams (aba Meus canais)
  requirements.txt          Dependências do servidor
  static/                   JavaScript ES5, estilos e ícone
  templates/                Interface HTML
  tests/                    Testes do sistema
  tools/                    Verificação da interface e suas dependências
  docs/                     Documentação de verificação
  .venv/                    Ambiente Python local (não distribuir)
```

As ferramentas de recuperação de SSD, versões antigas, cópias de trabalho e capturas anteriores foram retiradas da pasta do sistema. Uma cópia compactada foi preservada fora do projeto. A inicialização continua sendo feita pelo `RUN_IPTV.bat`.

Referências: [embed de chat da Twitch](https://dev.twitch.tv/docs/embed/chat/), [IRC da Twitch](https://dev.twitch.tv/docs/chat/irc/), [keyset HbbTV](https://developer.hbbtv.org/references/application-management-apis/the-keyset-class), [catálogo IPTV](https://github.com/iptv-org/iptv) e [saída HLS do FFmpeg](https://ffmpeg.org/ffmpeg-formats.html#hls-2). Os endpoints web de leitura pública da Twitch/Kick usados na descoberta, pesquisa e chat Kick não fazem parte de um contrato estável de API e podem mudar.
