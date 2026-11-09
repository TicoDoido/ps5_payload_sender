# PS5 Payload Sender

Aplicativo Android em Flet para enviar payloads ao PS5, transferir arquivos por FTP e consultar/baixar capturas.

## Fun??es

### Payloads
- Varre uma pasta e suas subpastas para localizar arquivos `.elf`, `.bin` e `.js`.
- Permite selecionar um ou v?rios arquivos pelo seletor do Android.
- Envia os bytes originais diretamente por TCP ao IP/porta configurados, em blocos de 1 MiB, sem cabe?alho ou prefixo adicional.
- Porta sugerida para ELF loader: `9021`.

### FTP
- IP FTP inicial independente do IP de envio de payload: `192.168.15.4` (edit?vel e salvo separadamente). Porta inicial: `2121`; usu?rio inicial: `anonymous`.
- Navega por pastas, lista arquivos e permite enviar/baixar arquivos entre o telefone e o PS5.
- Porta, usu?rio, senha e diret?rio remoto podem ser alterados na interface.
- FTP convencional n?o cifra os dados; use somente em uma rede local confi?vel.

### Capturas
- Lista fotos (`JXR`, `JPG`, `PNG`) e v?deos (`MP4`, `WebM`) nas pastas `av_contents` do PS5.
- Agrupa cada m?dia com os arquivos `.dat` e `.meta` de mesmo nome-base, sem listar os sidecars como capturas separadas.
- L? o nome do jogo do `.dat`, e a data/vers?o do jogo do `.meta`.
- Mostra miniaturas JPEG nativas dos v?deos e converte as miniaturas JPEG XR das fotos no pr?prio celular; os layouts RGB de 8-bit e RGB101010 de 10-bit s?o suportados.
- Decodifica capturas JXR no Android com tratamento por formato: SDR 8-bit preservado, RGB inteiro 10/16-bit interpretado como PQ/BT.2020 e scRGB float/fixed convertido para SDR.
- A previa e enviada como imagem isolada, sem moldura HTML; a exportacao PNG usa a resolucao original da captura (incluindo 3840x2160), sem reduzir para o tamanho da previa.
- A exporta??o PNG ? transferida em blocos pelo WebView para evitar mensagens grandes truncadas. O JXR original permanece dispon?vel para download e nunca ? alterado.
- A classificacao dos formatos e o fluxo de cores foram conferidos com a referencia publica [PS5Upload](https://github.com/phantomptr/ps5upload/blob/main/client/src-tauri/src/commands/screenshot_convert.rs); o processamento deste aplicativo foi implementado localmente.
- Diret?rio inicial de fotos: `/user/av_contents/photo/NPXS40087`.
- Diret?rio inicial de v?deos: `/user/av_contents/video/NPXS40087`.

Os diret?rios s?o edit?veis na interface. `NPXS40087` ? o identificador observado neste PS5 e pode variar em outros consoles/ambientes.

## Requisitos

- Python 3.10 ou superior.
- `flet==0.28.3`
- `flet-permission-handler==0.1.0`
- `flet-webview==0.1.0`
- Flutter 3.29.2 ou compat?vel com o Flet CLI instalado.
- JDK 17 e Android SDK (com as licen?as aceitas pelo operador).

## Execu??o local

```bash
pip install -r requirements.txt
flet run main.py
```

## APK Android

```bash
flet build apk --output build/apk
```

O projeto solicita permiss?es de rede e acesso ao armazenamento. No primeiro uso, conceda as permiss?es apresentadas pelo Android para que o app possa salvar arquivos em `Download/PS5 Captures`.

## Testes

```bash
python -m unittest discover -s tests -v
```

## Licen?as e cr?ditos

- O envio TCP original foi baseado no `payload_sender.py` do projeto Y2JB, de Gezine, sob licen?a MIT.
- FTP usa a biblioteca padr?o `ftplib`.
- A convers?o JXR usa o pacote `jpegxr` 0.3.0 (wrapper BSD-3-Clause) e a biblioteca `jxrlib`; os avisos/licen?as est?o em `assets/LICENSE-jpegxr.md` e `assets/LICENSE-jxrlib.json`.

Use o aplicativo apenas em consoles, redes e ambientes para os quais voc? tenha autoriza??o.
