from __future__ import annotations

import base64
import html
import json
import os
from pathlib import Path


def build_jxr_viewer_html(jxr_path: str, display_name: str | None = None) -> str:
    """Build a self-contained WebView page that decodes a PS5 JPEG XR capture.

    The bundled jpegxr.js is a single-file WebAssembly build of the BSD-licensed
    jxrlib decoder. The original .jxr file is only read; it is never modified.
    """
    path = Path(jxr_path)
    if not path.is_file():
        raise FileNotFoundError(path)

    if path.stat().st_size > 40 * 1024 * 1024:
        raise ValueError("A captura JXR excede o limite de 40 MB para pré-visualização.")

    bundle_path = Path(__file__).resolve().parent / "assets" / "jpegxr.js"
    if not bundle_path.is_file():
        raise FileNotFoundError(
            "Decodificador JPEG XR não foi incluído no APK: assets/jpegxr.js"
        )

    jxr_b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    decoder_js = bundle_path.read_text(encoding="utf-8")
    decoder_js = decoder_js.replace("</script", "<\\/script")
    safe_name = html.escape(display_name or path.name)

    page = r"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
<title>Prévia HDR</title>
<style>
:root { color-scheme: dark; font-family: Arial, sans-serif; }
html, body { margin:0; padding:0; width:100%; min-height:100%; background:#111318; color:#f4f4f5; }
body { display:flex; flex-direction:column; align-items:center; gap:10px; padding:12px; box-sizing:border-box; }
#name { width:100%; font-size:13px; color:#d4d4d8; overflow-wrap:anywhere; text-align:center; }
#status { width:100%; min-height:36px; color:#a1a1aa; font-size:12px; text-align:center; }
#preview { max-width:100%; max-height:66vh; width:auto; height:auto; object-fit:contain; background:#050505; }
#save { border:0; border-radius:8px; padding:10px 18px; color:#fff; background:#2563eb; font-size:14px; }
#error { color:#fca5a5; font-size:12px; white-space:pre-wrap; text-align:center; }
</style>
</head>
<body>
<div id="name">__DISPLAY_NAME__</div>
<div id="status">Baixando e decodificando a captura HDR…</div>
<canvas id="preview"></canvas>
<button id="save" hidden>Salvar JPEG no celular</button>
<div id="error"></div>
<script>
__DECODER_JS__
</script>
<script>
(async function () {
  const encoded = "__JXR_BASE64__";
  const status = document.getElementById("status");
  const errorBox = document.getElementById("error");
  const canvas = document.getElementById("preview");
  const saveButton = document.getElementById("save");
  let jpegUrl = "";

  function fail(message) {
    status.textContent = "Não foi possível gerar a prévia.";
    errorBox.textContent = message;
  }

  function halfToFloat(h) {
    const sign = (h & 0x8000) ? -1 : 1;
    const exponent = (h >> 10) & 0x1f;
    const mantissa = h & 0x3ff;
    if (exponent === 0) return sign * Math.pow(2, -14) * (mantissa / 1024);
    if (exponent === 31) return mantissa ? NaN : sign * Infinity;
    return sign * Math.pow(2, exponent - 15) * (1 + mantissa / 1024);
  }

  function srgbByte(value) {
    if (!Number.isFinite(value) || value <= 0) return 0;
    if (value >= 1) return 255;
    const mapped = value <= 0.0031308
      ? value * 12.92
      : 1.055 * Math.pow(value, 1 / 2.4) - 0.055;
    return Math.max(0, Math.min(255, Math.round(mapped * 255)));
  }

  try {
    const binary = atob(encoded);
    const input = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) input[i] = binary.charCodeAt(i);

    status.textContent = "Abrindo o decodificador JPEG XR…";
    const decoder = await jpegxr();
    const image = decoder.decode(input);
    const info = image.pixelInfo;

    if (info.colorFormat !== "RGB") {
      throw new Error("Formato de cor não suportado nesta prévia: " + info.colorFormat);
    }
    if (![3, 4].includes(info.channels)) {
      throw new Error("Número de canais não suportado: " + info.channels);
    }

    const bytesPerPixel = info.bitsPerPixel / 8;
    const bitDepth = info.bitDepth;
    const bytesPerSample = bitDepth === "10" ? 0 : bytesPerPixel / info.channels;
    if (bitDepth !== "10" && (!Number.isInteger(bytesPerSample) || ![1, 2, 4].includes(bytesPerSample))) {
      throw new Error("Formato de pixel não suportado: " + bitDepth);
    }
    if (bitDepth === "10" && (info.channels !== 3 || bytesPerPixel !== 4)) {
      throw new Error("Layout RGB101010 incompatível com esta captura.");
    }

    const sourceBytes = image.bytes;
    const sourceView = new DataView(sourceBytes.buffer, sourceBytes.byteOffset, sourceBytes.byteLength);
    const pixelCount = image.width * image.height;
    if (pixelCount <= 0 || pixelCount > 40000000) {
      throw new Error("Dimensões da captura inválidas ou grandes demais.");
    }
    if (!["8", "10", "16", "16Fixed", "16Float", "32", "32Fixed", "32Float"].includes(bitDepth)) {
      throw new Error("Profundidade de cor não suportada: " + bitDepth);
    }

    function componentAt(pixelIndex, channel) {
      const offset = pixelIndex * bytesPerPixel + channel * bytesPerSample;
      if (bitDepth === "10") {
        const packed = sourceView.getUint32(pixelIndex * bytesPerPixel, true);
        if (channel === 0) return ((packed >>> 20) & 0x3ff) / 1023;
        if (channel === 1) return ((packed >>> 10) & 0x3ff) / 1023;
        if (channel === 2) return (packed & 0x3ff) / 1023;
        return 1;
      }
      switch (bitDepth) {
        case "8":
          return sourceView.getUint8(offset) / 255;
        case "16":
          return sourceView.getUint16(offset, true) / 65535;
        case "16Fixed":
          return Math.max(0, sourceView.getInt16(offset, true) / 8192);
        case "16Float":
          return halfToFloat(sourceView.getUint16(offset, true));
        case "32":
          return sourceView.getUint32(offset, true) / 4294967295;
        case "32Fixed":
          return Math.max(0, sourceView.getInt32(offset, true) / 16777216);
        case "32Float":
          return sourceView.getFloat32(offset, true);
        default:
          return 0;
      }
    }

    const scale = Math.min(1, 1280 / image.width, 900 / image.height);
    const outWidth = Math.max(1, Math.round(image.width * scale));
    const outHeight = Math.max(1, Math.round(image.height * scale));
    canvas.width = outWidth;
    canvas.height = outHeight;

    const context = canvas.getContext("2d", { alpha: false });
    const pixels = context.createImageData(outWidth, outHeight);
    const output = pixels.data;
    const hdr = bitDepth === "16Float" || bitDepth === "32Float" ||
                bitDepth === "16Fixed" || bitDepth === "32Fixed";

    status.textContent = "Convertendo " + image.width + " × " + image.height + " para JPEG…";
    for (let y = 0; y < outHeight; y++) {
      const sourceY = Math.min(image.height - 1, Math.floor(y / scale));
      for (let x = 0; x < outWidth; x++) {
        const sourceX = Math.min(image.width - 1, Math.floor(x / scale));
        const sourcePixel = sourceY * image.width + sourceX;

        let r = componentAt(sourcePixel, info.bgr ? 2 : 0);
        let g = componentAt(sourcePixel, 1);
        let b = componentAt(sourcePixel, info.bgr ? 0 : 2);
        let a = info.hasAlpha ? componentAt(sourcePixel, 3) : 1;

        if (info.premultipledAlpha && a > 0) {
          r /= a; g /= a; b /= a;
        }

        if (hdr) {
          const luminance = Math.max(0, 0.2126 * r + 0.7152 * g + 0.0722 * b);
          const white = 4.0;
          const toneScale = luminance > 0
            ? (1 + luminance / (white * white)) / (1 + luminance)
            : 0;
          r *= toneScale; g *= toneScale; b *= toneScale;
        }

        const target = (y * outWidth + x) * 4;
        output[target] = srgbByte(r);
        output[target + 1] = srgbByte(g);
        output[target + 2] = srgbByte(b);
        // PS5 capture JXR files expose an all-zero alpha plane even though the screenshot is opaque.
      // Force opacity so WebView does not render a transparent/black preview.
      output[target + 3] = 255;
      }
    }

    context.putImageData(pixels, 0, 0);
    jpegUrl = canvas.toDataURL("image/jpeg", 0.92);
    status.textContent = "Prévia JPEG pronta · " + outWidth + " × " + outHeight +
                         (hdr ? " · HDR convertido para SDR" : "");
    saveButton.hidden = false;
    saveButton.addEventListener("click", function () {
      const jpegBase64 = jpegUrl.split(",", 2)[1];
      status.textContent = "Enviando JPEG para o armazenamento do celular…";
      console.log("PS5_JXR_SAVE:" + jpegBase64);
    });
  } catch (error) {
    fail(error && error.message ? error.message : String(error));
  }
})();
</script>
</body>
</html>"""

    # Keep the HTML self-contained: WebView does not need internet access.
    return (
        page.replace("__DISPLAY_NAME__", safe_name)
        .replace("__DECODER_JS__", decoder_js)
        .replace("__JXR_BASE64__", jxr_b64)
    )


def decode_jpeg_preview_base64(payload: str) -> bytes:
    """Validate and decode a JPEG emitted by the local WebView preview."""
    if not payload or len(payload) > 16 * 1024 * 1024:
        raise ValueError("Prévia JPEG vazia ou maior que o limite permitido.")
    try:
        data = base64.b64decode(payload, validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise ValueError("O WebView enviou dados JPEG inválidos.") from exc
    if len(data) < 4 or not data.startswith(b"\xff\xd8\xff"):
        raise ValueError("O conteúdo recebido não é um JPEG válido.")
    return data
