# Studio Desenho

Editor de pintura em Python/PyQt6. Interface inspirada na organização do Photoshop,
com temas claro e escuro, e estabilização com seleção simples inspirada no SAI.

## Abrir

### Executável standalone para Windows

Depois de compilado (veja abaixo), o arquivo **`dist/StudioDesenho.exe`** é a versão
standalone para Windows de 64 bits. Copie somente esse `.exe` para o outro computador e dê
dois cliques: não é necessário instalar Python, bibliotecas, FFmpeg ou copiar a pasta `venv`.
Fontes, traduções e o que estiver em `assets/` (incluindo modelos 3D e pincéis `.abr` que
você tenha colocado lá) entram no executável.
A primeira abertura pode levar alguns segundos enquanto os arquivos são extraídos
para uma pasta temporária. A execução não precisa de internet.

Na versão compilada, configurações, biblioteca pessoal, cache e recuperação ficam
em **`%LOCALAPPDATA%\Studio Desenho`**, para persistirem entre execuções e funcionarem
mesmo quando a pasta do executável não permite gravação. Para transferir também
os dados pessoais da versão em Python, copie `.studio-settings.json`,
`.studio-library.json` e, se existir, `.studio-background.png` da pasta do projeto
para essa pasta no outro PC. Uma imagem de fundo com caminho antigo pode precisar
ser selecionada novamente nas opções de aparência.

Para recompilar após alterar o código (somente no computador de desenvolvimento):

```powershell
.\venv\Scripts\python.exe -m pip install -r requirements-build.txt
powershell -ExecutionPolicy Bypass -File .\compilar.ps1
```

A receita está em `StudioDesenho.spec`; o resultado é `dist/StudioDesenho.exe`.
O empacotamento segue a documentação de
[arquivos spec](https://pyinstaller.org/en/stable/spec-files.html) e
[caminhos em execução](https://pyinstaller.org/en/stable/runtime-information.html)
do PyInstaller. Não distribua `build/` ou o ambiente `venv`.

### Executar o código Python

Monte o ambiente uma vez (Python 3.13 recomendado):

```powershell
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
```

Depois, no Windows, dê dois cliques em **iniciar.bat** ou execute:

```powershell
.\venv\Scripts\python.exe -B main.py
```

## Ajustar o traço

Comece com **S-4** no estabilizador e **Toque leve** no painel **Pincel e traço**.
As duas configurações são independentes:

- **Estabilizador:** 0 é livre; 1–15 suavizam gradualmente; S-1–S-7 oferecem mais
  firmeza com um pequeno atraso. Os botões Livre, Suave e Firme são atalhos.
- **Toque leve:** a pressão baixa já produz espessura útil, sem saturar imediatamente;
  pressionar mais continua aumentando a espessura. Normal e Pressão firme são alternativas.
- **Tamanho mínimo:** define o piso da espessura como percentual do tamanho escolhido.
- **Guia:** mostra a distância entre o cursor e a ponta estabilizada. Pode ser ocultada.

O estabilizador reamostra a entrada em intervalos regulares ao longo de uma curva
Catmull-Rom (traços rápidos ficam redondos, sem virar polígono) e aplica suavização temporal
com um pequeno buffer. Ao levantar a caneta, conclui o caminho pendente e alcança a posição
final. O algoritmo é próprio: os nomes dos níveis não garantem equivalência ao SAI.
A avaliação da sensação final exige experimentar com a mesa e o driver reais.
Se quiser maior firmeza, aumente o nível; se houver atraso excessivo, diminua.

## Recursos

A área de trabalho usa ícones QtAwesome, barras compactas e painéis encaixáveis:
ferramentas à esquerda, parâmetros do pincel e estabilizador no topo, e cor,
pincel e camadas à direita. O painel de pincel separa as abas Pincel e Estabilização.
Camadas têm miniaturas, controle de visibilidade e indicação de bloqueio.
O seletor de cor permite ajustar saturação/luminosidade e matiz separadamente.

Use **Pintura / Foco na tela**, no topo, ou **F11** para recolher os painéis e
recuperar a disposição anterior. **Exibir → Restaurar área de trabalho** recompõe
a organização padrão. A barra inferior permite editar o zoom diretamente.
Os temas incluem ícones, menus, seletores e a barra nativa de título em versões
compatíveis do Windows. `preview_dark.png` e `preview_light.png` mostram a interface.

O design está separado em `workbench.py`, `design_widgets.py`, `themes.py` e
`assets/`; os algoritmos de desenho e estabilização ficam em seus próprios módulos.

Pincel, borracha com transparência, conta-gotas, seletor HSV com tons escuros,
tamanhos fracionários, opacidade consistente por traço, pressão para tamanho,
zoom no cursor, navegação, rotação, camadas com visibilidade/opacidade/bloqueio,
duplicação e ordenação, desfazer/refazer e navegador de imagem.

Salve em **.sdp** para preservar camadas, transparência, animação e guias.
**Arquivo → Exportar** gera PNG, JPEG, WebP, MP4 (com áudio), GIF ou spritesheet PNG + JSON.
Desmarque **Papel branco** para exportar com transparência. PSD e os formatos do SAI
ainda não são suportados.

### Interface e idioma

Visual escuro e plano, com painéis em cartões: menus com o logotipo à esquerda, barra de
opções da ferramenta no topo, coluna de ferramentas agrupadas à esquerda (o triângulo no canto
indica mais ferramentas: clique com o botão direito ou segure o clique), chips de cor
principal/secundária, documento em aba, faixa de atalhos de painéis e painéis à direita (roda
de cores com triângulo, pincéis, camadas). O tema claro segue a mesma linguagem.
Toda a interface usa a fonte **Inter** (incluída em `assets/fonts`, licença OFL).

**Personalizar aparência** (botão de paleta ao lado do sol/lua, ou **Exibir → Personalizar
aparência…**, Ctrl+Alt+K) abre um modal com prévia ao vivo:

- **Cores:** temas prontos (Oceano, Ametista, Âmbar, Rosa, Floresta, Grafite, Clássico estilo
  Photoshop, Alto contraste) e as 13 cores da interface — fundo, painéis, campos, bordas, textos,
  destaque, seleção, área ao redor do desenho… — **separadas para o modo escuro e o claro**.
  Mudar só a cor de destaque já ajusta a cor de seleção.
- **Imagem de fundo:** preencher, ajustar, esticar, lado a lado ou centralizar; intensidade,
  desfoque, opacidade dos painéis (ficam translúcidos sobre a imagem) e opção de mostrar a
  imagem também ao redor da tela de desenho. Uma cópia da imagem é guardada junto das
  configurações (`.studio-background.png`).
- **Texto e formas:** fonte da interface, tamanho do texto, cantos arredondados e espessura
  das bordas.
- **Exportar / importar tema** em `.studiotheme` para compartilhar; **Restaurar padrão** volta
  ao visual original e **Cancelar** desfaz tudo o que foi pré-visualizado.

**Idioma:** português do Brasil por padrão, com inglês opcional pelo seletor **PT-BR / EN** na
barra de opções ou em **Exibir → Idioma**. A troca é imediata e fica salva. As traduções estão
em `translations/en.json`; os textos do Qt (OK/Cancelar, seletor de arquivos) usam a tradução
oficial do Qt.

### Camadas

Cada camada tem **modo de mistura** (normal, multiplicar, tela, sobrepor, escurecer, clarear,
subexposição e superexposição de cor, luz forte, luz suave, diferença, exclusão e adição),
opacidade, **bloqueio de transparência** (pinta só onde já há desenho) e bloqueio total.
**Mesclar com a camada abaixo** aplica a mistura e a opacidade.

### Modelos 3D (glTF)

O **Manequim 3D** também abre modelos `.glb` com esqueleto: os da pasta `assets/3D` aparecem
na lista de modelos e **Abrir arquivo .glb…** carrega outros. O repositório não traz modelos
(veja [Licença](#licença)); coloque em `assets/3D` os `.glb` que você tiver direito de usar. Clique numa parte para selecionar
o osso que a controla e arraste para girar (Shift gira em profundidade); os controles
Dobrar/Girar/Inclinar ajustam com precisão e **Mostrar ossos** desenha o esqueleto. Animações
gravadas no arquivo viram poses prontas, com um controle de momento. Modelos sem esqueleto
podem ser iluminados e enquadrados. As cores podem vir das texturas do modelo ou ser uma cor
única; luz, sombra projetada, chão, estilos de sombra e **Inserir na tela** funcionam como no
manequim. A renderização usa a placa de vídeo (OpenGL 3.3, via `moderngl`).

### Ferramentas de desenho

- **Pincel (B)**, **Lápis (N)** com grão de grafite e pressão na opacidade, **Caneta (P)**
  de nanquim e **Lápis pixel art (Shift+N)** sem suavização. Cada ferramenta lembra o
  próprio tamanho e o próprio pincel da biblioteca.
- **Balde (G)** com tolerância, área contígua, amostragem de todas as camadas e expansão
  sob o traço, para colorir lineart sem falhas.
- **Shift + clique** traça uma reta a partir do fim do último traço.
- **Girar vista (R)**: arraste para girar a tela; Shift gira em passos de 15°.
- **Esfumar (Shift+E)** arrasta a tinta e **Desfocar** suaviza a camada ativa; a opacidade
  define a intensidade.
- **Formas (O)**: linha, retângulo, retângulo arredondado, elipse, polígono (clique nos pontos
  e dê duplo clique ou Enter), estrela e seta; contorno, preenchido ou contorno + cor
  secundária. Shift mantém a proporção e Alt desenha a partir do centro.
- **Degradê (Shift+G)**: linear, radial, espelhado ou cônico, da cor principal para a
  secundária ou para transparente; respeita a seleção e o bloqueio de transparência.
- **Texto (T)**: clique na tela para escrever com fonte, tamanho, negrito/itálico,
  alinhamento, cor e contorno (ótimo para onomatopeias de quadrinho), numa nova camada.

### Seleção e transformação

Retângulo (M), elipse (Shift+M), laço (L) e varinha mágica (W). Shift adiciona, Alt
subtrai, Shift+Alt intersecta e Ctrl mantém a proporção; o modo também pode ser escolhido
na barra de opções. A pintura, a borracha e o balde ficam limitados à seleção.
O menu **Seleção** inverte, expande, contrai e suaviza a borda. **Mover (V)** desloca a
seleção ou a camada. **Editar** copia, recorta, cola como nova camada, preenche, limpa,
gira 90°/180°/livremente e espelha (a seleção ou a camada inteira).

### Guias

O menu **Guias** liga réguas nas bordas (Ctrl+R) e grade (Ctrl+'). A **perspectiva**
(Shift+U) aceita 1, 2 ou 3 pontos de fuga: clique para criar, arraste para mover e use o
botão direito para remover; há modelos prontos no menu. A **régua paralela** (U) define
uma direção. Com **Ajustar traço às guias** (Ctrl+;) o traço segue a direção mais próxima
do primeiro movimento: um ponto de fuga, a vertical/horizontal ou a régua.
As guias ficam salvas no projeto e nunca aparecem na exportação.

Ferramentas de apoio sobre o desenho:

- **Simetria (Shift+S)**: espelho vertical, horizontal, quatro quadrantes, radial
  (caleidoscópio) e mandala, com 2 a 32 cópias. Clique na tela para posicionar o eixo.
  Vale para pincel, lápis, caneta, pixel art, borracha, esfumar e desfocar.
- **Imagem de referência**: carregue uma foto ou rascunho que fica por cima ou atrás do
  desenho, com opacidade ajustável; arraste para mover e use a roda para a escala.
  Ela não entra nas camadas nem na exportação.
- **Composição**: regra dos terços, proporção áurea, espiral áurea, diagonais e centro.
- **Grade isométrica**, além da grade quadrada.
- **Tela → Espelhar vista** (Ctrl+Alt+F) e **Ver em tons de cinza** (Ctrl+Alt+Y) para
  conferir proporções e valores sem alterar o desenho.

### Quadrinhos

- **Nova página de quadrinho** traz formatos de comic americano, mangá, formatinho, A4,
  webtoon e tirinha, com sangria e área segura.
- **Painel Quadrinhos** (ícone de livro na faixa lateral ou **Quadrinhos → Painel de
  quadrinhos**) reúne tudo: página, letreiramento, efeitos e publicação.
- **Gerar página estilizada** (Ctrl+Alt+G): um clique monta quadros estilizados na página, e
  cada novo clique sorteia outra variação (Ctrl+Z volta). Estilos: ação com cortes diagonais,
  mangá dinâmico, cinematográfico, impacto (quadro com borda explosiva), clássico, suave
  (cantos arredondados), flashback/sonho (bordas onduladas), destaque com inserções (quadro
  dentro de quadro), splash com inserções ou aleatório. Alguns quadros **sangram** até a borda
  da página. As sarjetas têm a mesma largura mesmo nas diagonais, e a ordem de leitura segue
  a leitura ocidental ou a de mangá. Dá para escolher a quantidade de quadros ou deixar
  automático.
- **Gerar quadros…** abre todas as opções: os modelos fixos de grade (splash, 2×2, clássico de
  6, tirinhas, yonkoma…) ou linhas × colunas, ou qualquer estilo acima com **Outra variação**;
  margem, espaçamento, borda, cores e prévia. A camada “Quadros” fica bloqueada no topo e
  cobre a arte fora dos quadros; desenhe nas camadas abaixo.
- **Selecionar quadro** (Shift+W): clique num quadro para limitar a pintura a ele (Shift soma,
  Alt subtrai); as inserções ficam fora da seleção do quadro onde estão.
- **Balões** (ferramenta Balão, Shift+T): clique onde fica o balão e arraste até quem fala para
  apontar o rabicho. Tipos: fala, pensamento (nuvem com bolinhas), grito (espinhos), sussurro
  (tracejado), narração (caixa), rádio/eletrônico e **onomatopeia** (letras grandes inclinadas
  com contorno e sombra). Fonte, tamanho, cores e contorno, com prévia; cada balão vai para
  uma camada própria acima dos quadros, então pode atravessar as bordas.
- **Linhas de ação**: foco/concentração, velocidade e explosão, com quantidade, área livre no
  centro, espessura, ângulo, irregularidade e posição do centro.
- **Retícula**: pontos, degradê de pontos, linhas, hachura cruzada e granulado, com
  espaçamento, densidade e ângulo. Linhas e retícula ficam dentro do quadro (ou da seleção) e
  vão para uma camada nova.
- **Gerar capítulo…** cria várias páginas de uma vez numa pasta, cada uma com uma disposição
  diferente no estilo escolhido, camadas “Rascunho” e “Arte”, quadros e número.
- **Exportar capítulo em PDF…** junta as páginas (em ordem natural de nome) num PDF no tamanho
  e na resolução de cada página.
- **Numerar esta página** e **Numerar páginas em lote** gravam a camada “Número da página”,
  com posição no lado externo (alternando páginas pares e ímpares), prefixo, tamanho e cor.
  O lote segue a ordem natural dos nomes de arquivo.
- **Criar capa** monta fundo, arte, título com contorno, número da edição, autor, editora
  e espaço para código de barras, cada um em sua camada.

### Pincéis

O dock **Pincel** abre na aba **Pincéis**: uma lista com a prévia real do traço, filtro por
categoria e busca. Clique para usar o pincel na ferramenta ativa (Pincel, Lápis ou Caneta;
cada uma lembra o seu). Há 41 pincéis prontos: básicos, pintura digital, sombreado suave,
lápis 2H, HB, 6B, lapiseira e lápis de cor, caneta nanquim, técnica, caligráfica e pena G de
mangá, pincéis de cerdas, chato, seco, ancinho, fios de cabelo, mistura e óleo/acrílica,
aquarela, aquarela lavada e seca, giz pastel, giz de cera, carvão, esfuminho, e pincéis de
efeito e natureza (folhagem, grama, nuvens, esponja, spray, pontilhismo, brilhos, estrelas,
textura e respingos). As pontas geradas têm 512 px, para que pincéis grandes continuem nítidos;
as de cerdas são feitas de fios individuais, cada um com sua carga de tinta e comprimento.

O traço é acumulado como cobertura de 16 bits: cada pincelada aproxima a cobertura do seu
próprio nível (valor da ponta × opacidade da pressão) na taxa do fluxo. Assim a pressão
define o tom (passar de novo no mesmo traço não escurece além dela) e as estrias das
cerdas não se fecham. O motor aplica **textura de papel** presa à folha (papel com fibras,
papel áspero, trama de tela, papel de carvão vergé, aquarela ou imagem própria): o pigmento
pega primeiro nos relevos e, com mais pressão, entra nos vales, como no papel de verdade.
**Bordas úmidas** acumulam pigmento no contorno da aquarela; pontas de **cerdas acompanham
a direção** do traço (a primeira pincelada já sai na direção certa) e o **esgotamento da
tinta** faz o traço terminar seco e falhado. As pontas pequenas usam cópias reduzidas por
média de área, compartilhadas entre traços; SciPy e as texturas são preparados em segundo
plano ao abrir o programa, para o primeiro traço não travar.

**Criar / editar** (também em **Recursos → Criar pincel…**) abre o editor com prévia ao vivo,
em quatro abas:

- **Ponta:** galeria com as 18 pontas prontas (redonda, lápis, cerdas, chato, giz, carvão,
  aquarela, respingos, folha, grama, brilho…), ponta de imagem, da camada atual ou **de um
  arquivo `.abr` do Photoshop** (escolhida numa galeria); **Partir de** copia as configurações
  de outro pincel; dureza, proporção, ângulo, espaçamento e fluxo.
- **Forma:** pressão no tamanho, **afinar o início**, **velocidade → tamanho**, variação de
  tamanho, de proporção e de ângulo, direção do traço, **espelhar ao acaso**, dispersão e
  **quantidade por passo**.
- **Tinta:** pressão → opacidade, **pressão → fluxo**, **variação de opacidade**, esgotamento
  da tinta e bordas úmidas.
- **Textura:** galeria com 16 texturas prontas (papel, papel áspero, tela, carvão, aquarela,
  kraft, pastel em colmeia, linho, juta, concreto, madeira, areia, esponja, ruído fino, hachura
  e retícula de mangá) ou imagem própria, com força, escala, **contraste** e **inverter**.

Cada controle explica o que faz ao passar o mouse; **Desfazer alterações** volta ao início.
Os pincéis padrão viram cópias editáveis.

**Importar** (botão com texto no painel de pincéis, ou **Recursos → Importar pincéis do
Photoshop (.abr)…**) aceita `.abr` do Photoshop e `.sbrush`; também dá para **arrastar os
arquivos para o painel**. Cada predefinição do Photoshop mantém nome, ponta, diâmetro,
espaçamento, ângulo, proporção, pressão no tamanho e na opacidade, variações de tamanho, ângulo,
proporção e opacidade, espelhamento, dispersão com quantidade, bordas úmidas e a textura do
pacote (com inversão e contraste).

**Compartilhar:** exporte os selecionados em `.sbrush` ou copie um **código de texto**
(começa com `STUDIO-PINCEL:`) para colar num chat ou e-mail; quem recebe usa
**Importar → Colar código**.

### Paletas

O painel **Paletas** vem com Pele, Metais, Prata, Ouro, Cobre, Diamante, Grama, Madeira,
Pedra, Cabelo, Fogo, Céu e água, Sombras, Luz, Neutros, Pôr do sol, Oceano, Floresta, Pastel,
Neon, Terra, Mangá (cinzas), Retrô 80, Game Boy e PICO-8. Crie paletas e adicione a
cor atual; o botão direito remove ou substitui uma cor. Importa .json, .gpl
(GIMP/Krita/Aseprite), .hex (Lospec), .txt (Paint.NET), .aco e .ase (Photoshop/Adobe) e
exporta .gpl, .json ou .hex.

### Qualidade da tela

Com zoom abaixo de 100% a tela mostra uma redução por média de área (sem serrilhado nem
cintilação), atualizada só na região pintada. A partir de 200% cada pixel vira um quadrado
uniforme, unido aos vizinhos por uma transição de um pixel de tela ("sharp bilinear"): nem
borrado como a interpolação bilinear, nem com blocos de tamanhos desiguais como o vizinho
mais próximo em zooms quebrados. Ampliações inteiras (200%, 300%…) mostram os pixels exatos
para pixel art. A escala de tela do Windows é considerada.

Todos os traços (inclusive borracha e pincéis redondos sólidos) são carimbos unidos pelo
máximo da cobertura; as pontas redondas são desenhadas analiticamente, com rampa de borda de
um pixel em qualquer tamanho, por isso a borda fica suavizada e regular mesmo vista de perto.

### Desempenho

- A imagem final (modos de mistura, camadas de sombra, câmera, parallax, transições e
  legendas) fica guardada entre as repinturas; durante o traço só a área tocada é composta de
  novo. Na animação, os quadros já compostos ficam na memória (com limite), então a reprodução
  compõe cada quadro uma vez. Exportar, salvar e o conta-gotas continuam usando a composição
  completa.
- Os efeitos do pincel (textura, bordas úmidas) são aplicados uma vez por repintura sobre tudo
  o que foi pintado desde a anterior, e não a cada evento da caneta.
- Mover o mouse repinta só a área do cursor; a miniatura do navegador e as das camadas são
  refeitas só quando mudam.
- Salvar regrava só as camadas que mudaram e comprime as que mudaram em paralelo; abrir também
  descomprime as camadas em paralelo, e camadas vazias são reaproveitadas. Isso deixa salvar,
  o salvamento automático, a numeração em lote, gerar capítulo e exportar PDF bem mais rápidos
  em páginas grandes (A4 a 300 dpi).
- Na abertura, as pontas de pincel geradas vêm de um cache (`.studio-cache/`), e módulos pesados
  (SciPy, controle de mídia) só carregam quando são usados.

### Spotify

Quando o Spotify está tocando, a barra de status mostra artista e faixa, com faixa anterior,
tocar/pausar, próxima e o volume do Spotify (a roda do mouse sobre o controle também ajusta).
Funciona com o aplicativo do Spotify para Windows, sem login nem Premium: usa os controles de
mídia do Windows e o mixer de volume. **Exibir → Controle do Spotify na barra de status** liga
ou desliga; **Aceitar outros players** inclui navegador, YouTube e outros.

### Esqueleto (Bone Tool)

No modo animação, a **Bone Tool (K)** abre o painel **Esqueleto**. Os botões *+ Humano*,
*+ Braço*, *+ Perna* e *+ Cauda* criam esqueletos prontos e nomeados (quadril, tronco,
pescoço, cabeça, ombro, braço, antebraço, mão, coxa, canela e pé, lados esq./dir.).
Também é possível escolher o modelo em **Criar** na barra de opções e arrastar um retângulo.

- **Posar:** arraste um osso para girá-lo (os filhos acompanham). Arrastar a ponta da mão
  ou do pé dobra o braço ou a perna inteira (IK); Alt + arrastar usa IK em qualquer osso;
  Shift + arrastar, ou o círculo da raiz, move. Cada pose vira keyframe do quadro atual.
- **Criar:** arraste num espaço vazio para um osso novo; Ctrl + arrastar da ponta de um osso
  cria um osso filho.
- **Ajustar esqueleto** (modo na barra de opções) estica e move os ossos para encaixar no
  desenho, sem criar keyframes.
- **Criar camadas das partes** gera uma camada vinculada para cada osso; desenhe cada parte
  nela. O painel também renomeia, vincula camadas, espelha a pose, copia a pose do quadro
  anterior e zera poses. O botão direito sobre um osso abre as mesmas opções.

### Manequim 3D, luz e sombra

**Recursos → Manequim 3D (Ctrl+Shift+M)** abre um manequim articulado: corpo inteiro (com
dedos), cabeça e busto, mão direita e mão esquerda; proporções adulto, heroico, feminino,
infantil e chibi. Há poses prontas (em pé, T/A-pose, andando, correndo, sentado, acenando,
pulando, guarda de luta, pensativo, apontando; mãos aberta, relaxada, punho, apontando, V,
joinha, pinça e garra; cabeça em vários ângulos) e é possível **salvar poses próprias**.

Clique numa parte e arraste para girá-la; Shift + arrastar gira em profundidade; os controles
Dobrar/Girar/Inclinar ajustam com precisão. Arraste o fundo para orbitar, use o botão direito
para mover e a roda para zoom. A **luz** tem direção, altura, predefinições e Ctrl + arrastar;
há sombra projetada e sombra no chão. A sombra pode ser suave, dura, cel, hachura, hachura
cruzada, retícula, action comic ou conforme a cor do modelo, com contorno das partes ou da
silhueta. **Inserir na tela** cria a camada do manequim e uma camada de sombra editável.
O renderizador é próprio (numpy), sem dependência de OpenGL.

### Camada de sombra

**Camadas → Nova camada de sombra (Ctrl+Shift+H)**, ou o botão de meia-lua no painel
Camadas. Tudo que for pintado nela é tratado como sombra; tons mais escuros e opacos geram
sombra mais forte. O estilo pode ser trocado a qualquer momento, sem repintar: suave, dura,
cel/anime, hachura, hachura cruzada, retícula, action comic ou **conforme as cores do
desenho** (escurece e esfria a cor de cada área abaixo). Cor, mistura (multiplicar/normal),
espaçamento, ângulo e intensidade ficam no painel Camadas. **Em pixels** converte a sombra
numa camada comum com a mesma aparência; **Mesclar abaixo** aplica a sombra na camada de
baixo, só onde ela tem desenho.

### Animação

No modo animação, a **timeline** mostra uma grade de células por camada (estilo Aseprite),
com faixas de câmera, ossos, áudio (com forma de onda) e legendas, régua de quadros e tags
coloridas. Clique ou arraste para navegar; **Ctrl + arrastar** move um quadro; **Shift +
clique** seleciona um trecho; duplo clique na régua muda a duração e no nome renomeia a
camada; Ctrl + roda muda a largura dos quadros. A barra traz reproduzir em loop, FPS
(aplica a todos os quadros), onion skin com quantidade de quadros antes/depois e opacidade,
e botões para novo quadro, quadro vazio, duplicar, excluir, duração, tag e keyframes. O botão
direito em um quadro duplica, exclui, inverte a ordem, dobra ou divide a duração, move,
copia/cola/limpa a célula e cria tags com a seleção. **Animação → Inserir intermediário**
(Alt+I) cria um quadro vazio entre dois quadros para desenhar o meio do movimento.

Também: esqueletos; keyframes de câmera (com tremor), de camada e parallax; transições (fade,
dissolver, revelar, deslizar, íris, zoom e clarão); áudio com dublagem pelo microfone,
corte, divisão, volume, fades e redução de ruído; legendas sincronizadas com SRT.

Uma cópia de recuperação é gravada a cada minuto quando há alterações e não há um
traço em andamento. Na próxima inicialização após uma interrupção, é oferecida a recuperação.
Tema, sensibilidade, nível do estabilizador, tamanho da janela e organização dos painéis são lembrados ao fechar.
Ao executar o código Python, esses arquivos locais ficam na própria pasta do programa;
no executável standalone, ficam em `%LOCALAPPDATA%\Studio Desenho`.

## Atalhos

| Ação | Atalho |
|---|---|
| Pincel / lápis / caneta / pixel art | B / N / P / Shift+N |
| Borracha / balde / conta-gotas | E / G / I |
| Esfumar / degradê / formas / texto | Shift+E / Shift+G / O / T |
| Simetria / espelhar vista / tons de cinza | Shift+S / Ctrl+Alt+F / Ctrl+Alt+Y |
| Reproduzir / quadro anterior / próximo | Enter / , / . |
| Inserir intermediário / duplicar quadro | Alt+I / Alt+D |
| Mover pixels / mover tela / girar vista | V / H / R |
| Seleção retangular / elíptica / laço / varinha | M / Shift+M / L / W |
| Selecionar tudo / desmarcar / inverter | Ctrl+A / Ctrl+D (ou Esc) / Ctrl+Shift+I |
| Copiar / recortar / colar como camada | Ctrl+C / Ctrl+X / Ctrl+V |
| Limpar / preencher seleção | Delete / Alt+Backspace |
| Girar 90° | Ctrl+] / Ctrl+[ |
| Régua paralela / perspectiva | U / Shift+U |
| Réguas / grade / ajustar às guias | Ctrl+R / Ctrl+' / Ctrl+; |
| Bone Tool / manequim 3D / camada de sombra | K / Ctrl+Shift+M / Ctrl+Shift+H |
| Pegar cor temporariamente | Ctrl + clique |
| Mover tela | Espaço + arrastar ou botão do meio |
| Zoom | Roda do mouse |
| Ajustar à janela / 100% | Ctrl+0 / Ctrl+1 |
| Diminuir / aumentar pincel | [ / ] |
| Desfazer / refazer | Ctrl+Z / Ctrl+Shift+Z ou Ctrl+Y |
| Personalizar aparência | Ctrl+Alt+K |
| Gerar página estilizada / balão / selecionar quadro | Ctrl+Alt+G / Shift+T / Shift+W |
| Salvar / salvar como | Ctrl+S / Ctrl+Shift+S |
| Exportar PNG | Ctrl+Shift+E |
| Nova camada / duplicar | Ctrl+Shift+N / Ctrl+J |

Painéis podem ser movidos, separados em janelas ou reabertos pelo menu Exibir.
`main_original.py` preserva o editor anterior. `overlay.py` continua como aplicativo separado.

## Verificação

```powershell
.\venv\Scripts\python.exe -B -m unittest discover -s tests -v
```

Os testes verificam redução de tremor, consistência entre taxas de entrada, término
curvo do traço, resposta à pressão, desenho, borracha, opacidade, histórico,
camadas, projetos e zoom; `tests/test_tools.py` cobre lápis, caneta e pixel art,
seleções e seus modos, varinha, balde, mover, girar, copiar/colar, ajuste à perspectiva e
à régua, quadros, numeração, capa, formatos de paleta e transições.
`tests/test_models_ui.py` cobre leitura glTF, renderização e pose dos modelos 3D, modos de
mistura, bloqueio de transparência, ferramentas agrupadas, roda de cores e troca de idioma.
`tests/test_brushes_music.py` cobre texturas, bordas úmidas, prévias, códigos de
compartilhamento, importação ABR, a redução da tela e o controle de música.
`tests/test_performance.py` confere que a tela em cache é idêntica à composição completa
(mistura, animação com câmera, tons de cinza, zoom reduzido, desfazer) e que o traço sai igual
qualquer que seja a frequência de repintura. `tests/test_comics.py` cobre os estilos de página
(quadros dentro da página, sarjetas iguais nas diagonais, leitura de mangá, sangria, inserções),
geração com um clique e desfazer, seleção de quadro por clique, balões, linhas de ação, retícula,
capítulo, PDF e o reaproveitamento de camadas ao salvar. `tests/test_appearance.py` cobre temas por modo,
folha de estilo, imagem de fundo, o modal (prévia, cancelar, aplicar), arquivos de tema e fontes.
`tests/test_drawing_tools.py` cobre formas, polígono, degradê, esfumar/desfocar, texto,
simetria, imagem de referência, vista espelhada, tons de cinza, composição, grade
isométrica e as operações da timeline (mover, inverter, duplicar, excluir, FPS, onion skin).
`tests/test_rig_shadows.py` cobre esqueletos (modelos, FK, IK, ajuste, espelho), camadas
de sombra (estilos, conversão, mesclagem, salvamento) e o manequim 3D (poses, render, inserção).
A interface é executada sem janela visível nos testes. Os testes que dependem de um arquivo
`.abr` em `assets/Brushes` ou de modelos em `assets/3D` são pulados quando esses arquivos não existem.

## Licença

O código do Studio Desenho é distribuído sob a **GNU General Public License v3.0** — veja
[`LICENSE`](LICENSE). A GPL é exigida pelo PyQt6, que é licenciado sob GPL v3.

Arquivos de terceiros:

- **Fonte Inter** (`assets/fonts`): SIL Open Font License 1.1, em `assets/fonts/OFL-Inter.txt`.
- **Modelos 3D** (`assets/3D`) e **pincéis do Photoshop** (`assets/Brushes`): não fazem parte do
  repositório, porque pertencem aos seus autores e têm licenças próprias. As pastas ficam vazias;
  o programa funciona sem eles e aceita arquivos `.glb` e `.abr` abertos ou importados pelo usuário.
- As dependências de `requirements.txt` mantêm suas próprias licenças (MIT, BSD e GPL v3, todas
  compatíveis).
