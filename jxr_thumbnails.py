from __future__ import annotations

import base64
import json
from pathlib import Path


def build_jxr_thumbnails_html(items: list[tuple[str, str]]) -> str:
    """Build one self-contained WebView page to convert a batch of PS5 JXR thumbnails."""
    if not items:
        raise ValueError("Nenhuma miniatura JXR foi fornecida.")
    if len(items) > 60:
        raise ValueError("O lote excede o limite de 60 miniaturas.")

    bundle_path = Path(__file__).resolve().parent / "assets" / "jpegxr.js"
    if not bundle_path.is_file():
        raise FileNotFoundError("Decodificador JPEG XR ausente em assets/jpegxr.js")

    encoded_items = []
    for token, source_path in items:
        if not token or not token.isalnum() or len(token) > 40:
            raise ValueError("Token de miniatura inválido.")
        source = Path(source_path)
        if not source.is_file() or source.stat().st_size > 10 * 1024 * 1024:
            continue
        encoded_items.append({
            "token": token,
            "bytes": base64.b64encode(source.read_bytes()).decode("ascii"),
        })

    if not encoded_items:
        raise ValueError("Nenhuma miniatura JXR legível foi encontrada.")

    decoder_js = bundle_path.read_text(encoding="utf-8")
    decoder_js = decoder_js.replace("</script", "<\\/script")
    items_json = json.dumps(encoded_items, ensure_ascii=True, separators=(",", ":"))

    page = r"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Miniaturas PS5</title></head>
<body><div id="status">Preparando miniaturas…</div>
<script>
__DECODER_JS__
</script>
<script>
(async function () {
  const items = __ITEMS__;
  const status = document.getElementById("status");
  const decodeBase64 = (value) => {
    const binary = atob(value);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    return bytes;
  };
  try {
    const codec = await jpegxr();
    let completed = 0;
    let converted = 0;
    let failed = 0;
    for (const item of items) {
      try {
        const image = codec.decode(decodeBase64(item.bytes));
        const info = image.pixelInfo;
        if (info.colorFormat !== "RGB" ||
            !["8", "10"].includes(info.bitDepth) ||
            ![3, 4].includes(info.channels)) {
          throw new Error("Formato JXR de miniatura não suportado");
        }

        const bytesPerPixel = info.bitsPerPixel / 8;
        const view = new DataView(image.bytes.buffer, image.bytes.byteOffset,
                                  image.bytes.byteLength);
        const scale = Math.min(1, 480 / image.width, 270 / image.height);
        const width = Math.max(1, Math.round(image.width * scale));
        const height = Math.max(1, Math.round(image.height * scale));
        const canvas = document.createElement("canvas");
        canvas.width = width;
        canvas.height = height;
        const ctx = canvas.getContext("2d", {alpha: false});
        const output = ctx.createImageData(width, height);

        for (let y = 0; y < height; y++) {
          const sy = Math.min(image.height - 1, Math.floor(y / scale));
          for (let x = 0; x < width; x++) {
            const sx = Math.min(image.width - 1, Math.floor(x / scale));
            const source = (sy * image.width + sx) * bytesPerPixel;
            const target = (y * width + x) * 4;
            if (info.bitDepth === "10") {
              // JPEG XR RGB101010: R[29:20], G[19:10], B[9:0].
              // Matches jxrlib's RGB101010_RGB24 conversion routine.
              const packed = view.getUint32(source, true);
              output.data[target] = (packed >>> 22) & 0xFF;
              output.data[target + 1] = (packed >>> 12) & 0xFF;
              output.data[target + 2] = (packed >>> 2) & 0xFF;
            } else {
              output.data[target] = view.getUint8(source + (info.bgr ? 2 : 0));
              output.data[target + 1] = view.getUint8(source + 1);
              output.data[target + 2] = view.getUint8(source + (info.bgr ? 0 : 2));
            }
            output.data[target + 3] = 255;
          }
        }
        ctx.putImageData(output, 0, 0);
        const jpeg = canvas.toDataURL("image/jpeg", 0.84).split(",", 2)[1];
        console.log("PS5_THUMB:" + item.token + ":" + jpeg);
        converted++;
      } catch (error) {
        console.log("PS5_THUMB_ERROR:" + item.token + ":" +
                    (error && error.message ? error.message : String(error)));
        failed++;
      }
      completed++;
      status.textContent = "Miniaturas " + completed + "/" + items.length +
                           " · " + converted + " convertidas · " + failed + " falhas";
    }
    status.textContent = "Miniaturas prontas · " + converted + " convertidas · " + failed + " falhas";
    console.log("PS5_THUMB_DONE:" + converted + ":" + failed);
  } catch (error) {
    console.log("PS5_THUMB_BATCH_ERROR:" +
                (error && error.message ? error.message : String(error)));
  }
})();
</script></body></html>"""

    return page.replace("__DECODER_JS__", decoder_js).replace("__ITEMS__", items_json)

