# Verificação do TVHub

Data: 18/10/2026. Base de compatibilidade usada: Chrome 47 / SRAF 4.0, conforme o projeto existente.

Este documento mantém o registro das verificações. As capturas e os registros brutos anteriores foram arquivados fora do projeto durante sua organização; novas execuções geram saídas em `tests/results/`.

## Testes automáticos

- **18 testes do servidor e dos chats passaram** (`tests/test_app.py`). Cobrem validação de canais, busca além do limite antigo de 600 canais, paginação, Streamlink no ambiente correto, alternativa de resolução Twitch, emotes, moderação, cache do chat, playlists com chaves/mapas e proxy com intervalos de bytes.
- **15 testes de descoberta/miniaturas passaram** (`tests/test_discovery.py`). Cobrem prioridade do nome exato, resultados reais sem duplicatas, cache, paginação local Twitch, idioma/categoria Kick, validação dos filtros, falhas de plataforma, JPEG 320×180, escolha de variante HLS pequena, captura limitada a um quadro, logotipo alternativo e reaproveitamento de capturas simultâneas.
- **5 testes de compatibilidade HLS passaram** (`tests/test_hls_compat.py`). Cobrem o master misto do History, manutenção das qualidades AVC e áudio externo, preservação de playlists sem AVC, propagação do perfil de compatibilidade e preservação de chaves/mapas.
- **15 testes de adaptação de vídeo passaram** (`tests/test_video_compatibility.py`). Cobrem HEVC sem AVC, escolha de fonte até 720p, áudio externo, correção manual, cancelamento antes/durante a consulta, limites de processos, encerramento completo, expiração, timeouts, janela inicial mínima de HLS e validação dos arquivos da sessão.
- **31 testes de interface passaram** (`tools/verificar_interface.py`) em Chrome instalado, sem erros JavaScript. Incluem pesquisa exata/similar, pesquisa antiga cancelada, filtros/paginação, retorno à aba com todas as páginas carregadas, disposição da aba Descobrir, duas miniaturas simultâneas e ausência de consultas remotas na página inicial. A adaptação automática/manual, cancelamento ao voltar e tratamento de falha também foram verificados.
- O controle foi testado com nomes de teclas, `keyIdentifier`, eventos somente `keyup` e sequências `keydown`/`keypress`/`keyup` sem duplicar a ação. Movimentos de mouse mudaram o foco, o OK clicou no elemento selecionado e um OK acompanhado por clique de mouse não ativou o botão duas vezes. Seletores foram editados/confirmados/cancelados só com o teclado.
- As regressões de ponteiro foram reproduzidas antes da correção: foco forçado em outro botão seguido de clique sintético abria o elemento errado; movimento de mouse depois de uma seta real mudava a seleção novamente. Os dois testes passaram após o app assumir a seleção e bloquear mudanças de foco do ponteiro. Também passaram os cenários de seta acompanhada por mouse, OK mantido pressionado, foco em diálogos/Tab e abertura IPTV com o perfil AVC.
- Os três arquivos JavaScript da interface foram analisados com **Acorn 8.15.0 e `ecmaVersion: 5`**. hls.js 0.12.4, sem alterações nesta etapa, já havia passado na mesma verificação.
- Layout conferido em **1920×1080, 1280×720, 1024×768 e 390×844**, sem rolagem horizontal do conteúdo.
- Modo TV inspecionado em 1280×720; a primeira fileira inclui os nomes dos canais dentro da área visível.
- A aba Descobrir também foi verificada nas quatro resoluções, sem rolagem horizontal. Capturas reais de descoberta, pesquisa e IPTV foram inspecionadas em 1280×720 com foco visível e cursor oculto.

Os testes de interface simulam a mídia; seus resultados verificam estados e navegação, sem afirmar suporte de codec no equipamento alvo.

## Consultas e reprodução reais

- Twitch IRC: conexão TLS e entrada no chat confirmadas, estado `connected`.
- Twitch: resolução da transmissão de Gaules e carregamento da playlist pelo proxy confirmados com HTTP 200.
- Twitch: reprodução real em **1920×1080** pelo HLS nativo do Chrome, `readyState = 4`, vídeo em execução e sem erros JavaScript. A alternativa de resolução GraphQL também foi consultada diretamente e retornou uma playlist válida com HTTP 200.
- Kick: consulta de mensagens públicas confirmada, com 25 mensagens retornadas.
- Kick: resolução do endereço HLS e proxy da playlist confirmados com HTTP 200.
- Kick: reprodução real iniciada no Chrome, com quadros decodificados (`videoWidth > 0`), `readyState = 4`, vídeo em execução e sem erros JavaScript.
- Kick via MediaSource/hls.js: reprodução real em **1280×720**, `readyState = 4` e vídeo em execução. Esse caminho também foi testado ao forçar o navegador a não anunciar HLS nativo.
- IPTV Brasil: catálogo real carregado com HTTP 200; 397 entradas no momento da consulta. A interface pede páginas de 60.
- hls.js 0.12.4: biblioteca servida pelo servidor local com HTTP 200.

Esses resultados registram a disponibilidade no momento da consulta; canais podem sair do ar e endpoints podem mudar.

## Pesquisa, descoberta e imagens reais

- Pesquisa `gaules`: **10 resultados Twitch e 16 Kick**, com o canal exato em primeiro lugar nas duas plataformas.
- Descobrir em português: **12 lives na primeira página** de cada plataforma. A segunda página trouxe **9 Twitch e 1 Kick**, sem repetir canais da primeira página no momento da consulta.
- Filtro de Minecraft na Twitch e League of Legends na Kick: **12 resultados** na primeira página de cada consulta, todos com a categoria solicitada.
- Pesquisa de categorias `minecraft`: **10 resultados Twitch e 12 Kick**.
- As miniaturas reais das duas plataformas retornaram HTTP 200, **320×180**, com aproximadamente **12 KB** cada.
- Captura real de **ConecTV Brasil**: JPEG **320×180**, aproximadamente **9 KB**, obtido em **2,8 s**. Não foi necessário carregar o player no navegador para gerar a imagem.
- A interface real exibiu descoberta, pesquisa e 60 entradas IPTV com miniaturas, sem erros JavaScript. A página inicial não solicita descoberta nem prévias.
- A consulta geral Twitch aceita no máximo 30 entradas. Seus cursores remotos exigiram uma verificação adicional; a implementação usa paginação do lote público em cache. Não depende dessa operação restrita. Por categoria, o lote tem até 60 entradas. A Kick filtra português explicitamente porque a rota localizada, sozinha, retorna vários idiomas.

As consultas e capturas desta etapa foram preservadas no arquivo externo, incluindo `discovery-real-check.json` e as imagens de descoberta, pesquisa e IPTV. Os números variam com as transmissões disponíveis. Logotipo e iniciais são alternativas esperadas quando um sinal não permite capturar um quadro.

## History e seleção de codec

O master atual de **History (Brazil)** anuncia vídeo HEVC/H.265 em 480p e 1080p, além de AVC/H.264 em 720p. O caminho IPTV agora solicita preferência por AVC e recebe apenas a variante H.264 disponível nesse master. Essa mudança também se aplica a outros canais com masters mistos.

- Playlist real: **3 variantes antes, 1 depois**, mantendo `tracks-v3a1/mono.m3u8` com o áudio original.
- FFprobe através do proxy: vídeo **H.264 Main, 1280×720**, e áudio **AAC LC**.
- Chrome com HLS nativo: **1280×720, readyState 4, 94 quadros decodificados**, vídeo em execução e sem erros JavaScript.
- Chrome com MediaSource/hls.js 0.12.4: **1280×720, readyState 4, 94 quadros decodificados**, vídeo em execução e sem erros JavaScript.
- A captura real mostra imagem do programa no player. Não houve transcodificação.

O registro `history-playback-check.json` e as imagens do History foram preservados no arquivo externo. A variante escolhida anteriormente pelo firmware da TV não foi observada diretamente; estes resultados confirmam a seleção e a reprodução corrigidas no PC.

## CNN Brasil e canais sem variante H.264

A consulta real da CNN Brasil confirmou **HEVC/H.265 em todas as quatro qualidades**, com áudio AAC. Isso explica por que somente preferir AVC, como no History, não oferecia uma alternativa para esse sinal.

O app passou a detectar esse caso antes de abrir o vídeo. O computador produz H.264 Constrained Baseline, nível 3.1, `yuv420p`, até 1280×720/30 fps, com áudio AAC LC e HLS versão 3. A lista só é entregue ao player após conter ao menos três segmentos; uma lista inicial menor causou erro de análise no HLS nativo durante os testes.

- **CNN com HLS nativo:** 1280×720, `readyState = 4`, 94 quadros decodificados e sem erros JavaScript.
- **CNN com hls.js/MediaSource:** os mesmos 1280×720, `readyState = 4` e 94 quadros, sem erros JavaScript.
- O FFprobe confirmou **H.264 Constrained Baseline e AAC LC** na saída entregue ao navegador.
- A reprodução em andamento foi confirmada após aproximadamente 10 segundos desde o pedido, incluindo três segundos de vídeo reproduzido, no computador testado.
- Ao voltar aos canais, a resposta de liberação só foi concluída depois de encerrar o FFmpeg e remover os arquivos temporários. Não restaram conversões ativas nos dois testes.
- **History foi testado novamente pelo novo fluxo:** vídeo original em 1280×720, sem iniciar conversão.

As capturas e o registro `cnn-compatibility-real.json` foram guardados com as evidências externas. Os testes automáticos somam **53 casos do servidor e 31 de interface**. A entrada `app.py` também foi iniciada como processo separado: página, arquivos estáticos e APIs responderam na estrutura reorganizada.

## Organização do projeto

O iniciador continua sendo `RUN_IPTV.bat`, agora apontando para `app.py`. Documentação fica em `docs/`; os testes do app permanecem em `tests/`, e a verificação visual em `tools/`. Ferramentas de SSD, versões antigas, cópias de trabalho e saídas de diagnóstico foram retiradas da pasta do sistema. A cópia compactada externa foi verificada por hash antes da movimentação. `.venv/` foi mantida para preservar o ambiente de execução.

## Validação que depende da TV física

- Confirmar o suporte real do firmware ao codec e à resolução das transmissões.
- Confirmar o recebimento das teclas no portal/navegador SRAF.
- Confirmar se o firmware entrega movimentos/cliques à página e permite captura de ponteiro; a adaptação foi validada com eventos reais do Chrome no PC, sem acesso ao controle físico da TV.
- Conferir áudio, estabilidade prolongada, legibilidade à distância e consumo de memória.
- Usar o chat leve como padrão. A página oficial de chat depende dos requisitos atuais da plataforma e pode não executar no Chrome 47.

O chat leve é de leitura. Na Kick, consulta mensagens recentes e pode perder mensagens em canais de grande movimento. Para autenticar e enviar mensagens, use o chat original em um navegador compatível.

Novas capturas de interface são geradas em `tests/results/`. `player-chat.png` contém texto propositalmente inválido para verificar que mensagens não são executadas como HTML; não representa uma conversa real.
