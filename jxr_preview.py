from __future__ import annotations

import base64
import html
import json
import os
import re
from pathlib import Path

MAX_PNG_BASE64_CHARS = 64 * 1024 * 1024
MAX_PNG_TRANSFER_CHUNKS = 4096


def build_jxr_viewer_html(
    jxr_path: str, display_name: str | None = None, result_token: str = "preview"
) -> str:
    """Build a self-contained WebView page that decodes a PS5 JPEG XR capture.

    The bundled jpegxr.js is a single-file WebAssembly build of the BSD-licensed
    jxrlib decoder. The original .jxr file is only read; it is never modified.
    """
    path = Path(jxr_path)
    if not path.is_file():
        raise FileNotFoundError(path)

    if path.stat().st_size > 40 * 1024 * 1024:
        raise ValueError("A captura JXR excede o limite de 40 MB para pré-visualização.")
    if not result_token or not result_token.isalnum() or len(result_token) > 40:
        raise ValueError("Invalid preview token.")

    bundle_path = Path(__file__).resolve().parent / "assets" / "jpegxr.js"
    if not bundle_path.is_file():
        raise FileNotFoundError(
            "Decodificador JPEG XR não foi incluído no APK: assets/jpegxr.js"
        )

    jxr_b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    decoder_js = bundle_path.read_text(encoding="utf-8")
    wasm_match = re.search(
        r'var wasmBinaryFile="data:application/octet-stream;base64,([^"]+)";',
        decoder_js,
    )
    if not wasm_match:
        raise ValueError("O binário WebAssembly do decoder JPEG XR não foi encontrado.")
    wasm_base64 = wasm_match.group(1)
    decoder_js, replacements = re.subn(
        r'var wasmBinaryFile="data:application/octet-stream;base64,[^"]+";',
        'var wasmBinaryFile="";',
        decoder_js,
        count=1,
    )
    if replacements != 1:
        raise ValueError("Não foi possível preparar o binário WebAssembly do decoder.")
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
#error { color:#fca5a5; font-size:12px; white-space:pre-wrap; text-align:center; }
</style>
</head>
<body>
<div id="name">__DISPLAY_NAME__</div>
<div id="status">Baixando e decodificando a captura HDR…</div>
<canvas id="preview"></canvas>
<div id="error"></div>
<script>
__DECODER_JS__
</script>
<script>
(async function () {
  const encoded = "__JXR_BASE64__";
  const wasmEncoded = "__WASM_BASE64__";
  const status = document.getElementById("status");
  const errorBox = document.getElementById("error");
  const canvas = document.getElementById("preview");
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

  // SMPTE ST 2084 (PQ): encoded value -> luminance as a fraction of 10,000 nits.
  function pqEotf(value) {
    const m1 = 2610 / 16384;
    const m2 = 2523 / 4096 * 128;
    const c1 = 3424 / 4096;
    const c2 = 2413 / 4096 * 32;
    const c3 = 2392 / 4096 * 32;
    const n = Math.max(0, Math.min(1, value));
    const np = Math.pow(n, 1 / m2);
    const den = c2 - c3 * np;
    if (den <= 0) return 0;
    return Math.pow(Math.max(0, np - c1) / den, 1 / m1);
  }

  function rec2020ToRec709(r, g, b) {
    return [
      1.6605 * r - 0.5876 * g - 0.0728 * b,
      -0.1246 * r + 1.1329 * g - 0.0083 * b,
      -0.0182 * r - 0.1006 * g + 1.1187 * b
    ];
  }

  function reinhardExtended(value, white) {
    const w2 = white * white;
    const c = Math.max(0, value);
    return (c * (1 + c / w2)) / (1 + c);
  }

  try {
    const binary = atob(encoded);
    const input = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) input[i] = binary.charCodeAt(i);

    status.textContent = "Preparando o decoder JPEG XR...";
    // Pass the embedded WASM bytes directly. Android WebView can reject fetch(data:...).
    const wasmBinary = Uint8Array.from(atob(wasmEncoded), ch => ch.charCodeAt(0));
    const decoderPromise = jpegxr({ wasmBinary });
    const decoder = await Promise.race([
      decoderPromise,
      new Promise((_, reject) => setTimeout(
        () => reject(new Error("Tempo esgotado ao inicializar o decoder JPEG XR.")),
        60000
      ))
    ]);
    status.textContent = "Decodificando a captura JPEG XR...";
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

    const isSdr8 = bitDepth === "8";
    const isPqInteger = bitDepth === "10" || bitDepth === "16";
    const isScRgb = bitDepth === "16Float" || bitDepth === "32Float" ||
                    bitDepth === "16Fixed" || bitDepth === "32Fixed";
    if (!isSdr8 && !isPqInteger && !isScRgb) {
      throw new Error("Formato JPEG XR sem perfil de cor validado: " + bitDepth);
    }

    function readSourceRgb(pixelIndex) {
      return [
        componentAt(pixelIndex, info.bgr ? 2 : 0),
        componentAt(pixelIndex, 1),
        componentAt(pixelIndex, info.bgr ? 0 : 2)
      ];
    }

    // PS5Upload's PS5-specific pipeline: 8-bit RGB is already display-referred
    // sRGB and must pass through untouched. 10/16-bit integer data is PQ/BT.2020;
    // half/float/fixed data is linear scRGB. Never apply gamma twice to SDR.
    function readLinearRgb(pixelIndex) {
      const rgb = readSourceRgb(pixelIndex);
      if (isPqInteger) {
        const r = pqEotf(rgb[0]) * 100;
        const g = pqEotf(rgb[1]) * 100;
        const b = pqEotf(rgb[2]) * 100;
        return rec2020ToRec709(r, g, b);
      }
      return rgb;
    }

    // Full-resolution export canvas. The visible preview is separately scaled;
    // PNG export therefore contains only the screenshot pixels, never page chrome.
    const exportCanvas = document.createElement("canvas");
    exportCanvas.width = image.width;
    exportCanvas.height = image.height;
    const exportContext = exportCanvas.getContext("2d", { alpha: false });
    if (!exportContext) throw new Error("Nao foi possivel criar a imagem de exportacao.");
    let peak = 1.0;

    if (!isSdr8) {
      status.textContent = "Analisando luminancia HDR " + image.width + " x " + image.height + "...";
      for (let pixel = 0; pixel < pixelCount; pixel++) {
        const rgb = readLinearRgb(pixel);
        peak = Math.max(peak, rgb[0], rgb[1], rgb[2]);
      }
    }

    status.textContent = "Convertendo " + image.width + " x " + image.height + " pixels...";
    // Work in 64-row strips to avoid a second full-size RGBA ImageData allocation.
    const stripHeight = 64;
    for (let startY = 0; startY < image.height; startY += stripHeight) {
      const rows = Math.min(stripHeight, image.height - startY);
      const strip = exportContext.createImageData(image.width, rows);
      const output = strip.data;
      for (let y = 0; y < rows; y++) {
        const rowStart = (startY + y) * image.width;
        for (let x = 0; x < image.width; x++) {
          const pixel = rowStart + x;
          let r, g, b;
          if (isSdr8) {
            // Already encoded 8-bit SDR: only reorder BGR -> RGB and preserve values.
            const rgb = readSourceRgb(pixel);
            r = Math.round(Math.max(0, Math.min(1, rgb[0])) * 255);
            g = Math.round(Math.max(0, Math.min(1, rgb[1])) * 255);
            b = Math.round(Math.max(0, Math.min(1, rgb[2])) * 255);
          } else {
            const rgb = readLinearRgb(pixel);
            r = srgbByte(reinhardExtended(rgb[0], peak));
            g = srgbByte(reinhardExtended(rgb[1], peak));
            b = srgbByte(reinhardExtended(rgb[2], peak));
          }
          const target = (y * image.width + x) * 4;
          output[target] = r;
          output[target + 1] = g;
          output[target + 2] = b;
          // PS5 captures expose an all-zero alpha plane; screenshots are opaque.
          output[target + 3] = 255;
        }
      }
      exportContext.putImageData(strip, 0, startY);
    }

    const scale = Math.min(1, 1280 / image.width, 720 / image.height);
    const outWidth = Math.max(1, Math.round(image.width * scale));
    const outHeight = Math.max(1, Math.round(image.height * scale));
    canvas.width = outWidth;
    canvas.height = outHeight;
    const context = canvas.getContext("2d", { alpha: false });
    context.drawImage(exportCanvas, 0, 0, outWidth, outHeight);
    jpegUrl = canvas.toDataURL("image/jpeg", 0.92);
    status.textContent = "Previa " + outWidth + "x" + outHeight + " - captura original " +
                         image.width + "x" + image.height + (isSdr8 ? " - SDR 8-bit preservado" : " - HDR convertido para SDR");
    console.log("PS5_JXR_PREVIEW:__RESULT_TOKEN__:" + jpegUrl.split(",", 2)[1]);

    // Transfer the full-resolution PNG in bounded console events. A single
    // large console message can be truncated by Android WebView / Flutter.
    window.ps5SavePng = function () {
      status.textContent = "Gerando PNG " + image.width + " x " + image.height + "...";
      exportCanvas.toBlob(function (blob) {
        if (!blob) {
          console.log("PS5_JXR_ERROR:__RESULT_TOKEN__:O WebView nao conseguiu gerar o PNG.");
          return;
        }
        const reader = new FileReader();
        reader.onerror = function () {
          console.log("PS5_JXR_ERROR:__RESULT_TOKEN__:Falha ao ler o PNG gerado.");
        };
        reader.onload = function () {
          const dataUrl = String(reader.result || "");
          const comma = dataUrl.indexOf(",");
          if (comma < 0) {
            console.log("PS5_JXR_ERROR:__RESULT_TOKEN__:Dados PNG invalidos.");
            return;
          }
          const payload = dataUrl.slice(comma + 1);
          const chunkSize = 16384;
          const chunkCount = Math.ceil(payload.length / chunkSize);
          if (!payload.length || payload.length > 67108864 || chunkCount > 4096) {
            console.log("PS5_JXR_ERROR:__RESULT_TOKEN__:PNG excede o limite de transferencia do aplicativo.");
            return;
          }
          console.log("PS5_JXR_SAVE_START:__RESULT_TOKEN__:" + payload.length + ":" + chunkCount);
          let index = 0;
          function sendChunkBatch() {
            const batchEnd = Math.min(index + 32, chunkCount);
            while (index < batchEnd) {
              console.log("PS5_JXR_SAVE_CHUNK:__RESULT_TOKEN__:" + index + ":" +
                          payload.slice(index * chunkSize, (index + 1) * chunkSize));
              index++;
            }
            if (index < chunkCount) {
              setTimeout(sendChunkBatch, 0);
            } else {
              console.log("PS5_JXR_SAVE_END:__RESULT_TOKEN__:" + chunkCount);
            }
          }
          setTimeout(sendChunkBatch, 0);
        };
        reader.readAsDataURL(blob);
      }, "image/png");
    };
  } catch (error) {
    const message = error && error.message ? error.message : String(error);
    fail(message);
    console.log("PS5_JXR_ERROR:__RESULT_TOKEN__:" + message);
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
        .replace("__WASM_BASE64__", wasm_base64)
        .replace("__RESULT_TOKEN__", result_token)
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


def decode_png_preview_base64(payload: str) -> bytes:
    """Validate and decode a PNG emitted by the local WebView preview."""
    if not payload or len(payload) > MAX_PNG_BASE64_CHARS:
        raise ValueError("O PNG estÃ¡ vazio ou excede 48 MB de dados binÃ¡rios.")
    try:
        data = base64.b64decode(payload, validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise ValueError("O WebView enviou dados PNG invÃ¡lidos.") from exc
    if len(data) < 24 or not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("O conteÃºdo recebido nÃ£o Ã© um PNG vÃ¡lido.")
    return data


def assemble_png_preview_chunks(chunks: list[str | None], expected_length: int) -> bytes:
    """Join the ordered WebView chunks and validate the resulting full-resolution PNG."""
    if not chunks or len(chunks) > MAX_PNG_TRANSFER_CHUNKS:
        raise ValueError("Quantidade de blocos PNG invÃ¡lida.")
    if not isinstance(expected_length, int) or not 1 <= expected_length <= MAX_PNG_BASE64_CHARS:
        raise ValueError("Tamanho declarado do PNG invÃ¡lido.")
    if any(not isinstance(chunk, str) for chunk in chunks):
        raise ValueError("A transferÃªncia do PNG estÃ¡ incompleta.")
    payload = "".join(chunks)
    if len(payload) != expected_length:
        raise ValueError(
            f"TransferÃªncia incompleta: {len(payload)} de {expected_length} caracteres."
        )
    return decode_png_preview_base64(payload)
