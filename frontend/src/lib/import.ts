/**
 * Importação de livros a partir de ZIP.
 *
 * Formato esperado: ZIP plano contendo `book.json` na raiz + arquivos
 * referenciados pelos campos `mp3_path`, `vtt_path`, `text_path` de cada
 * capítulo. Estrutura da pasta `library/<livro>/` no backend, zipada.
 *
 * O ZIP pode opcionalmente vir com tudo dentro de uma pasta raiz (gerada
 * por `zip -r livro.zip livro/`) — detectamos e descontamos o prefixo.
 */
import JSZip from "jszip";

import { saveAsset, saveBook } from "./storage";
import { validateManifest, type BookManifest } from "./types";

export type ImportProgress = {
  phase: "reading" | "validating" | "extracting" | "done";
  current: number;
  total: number;
  filename?: string;
};

/**
 * Importa um livro de um File (`<input type="file">`).
 *
 * @param file ZIP contendo `book.json` + assets.
 * @param onProgress callback opcional para feedback na UI.
 * @returns o manifest do livro importado.
 * @throws Error com mensagem orientada ao usuário se o ZIP é inválido.
 */
export async function importBookFromZip(
  file: File,
  onProgress?: (p: ImportProgress) => void,
): Promise<BookManifest> {
  if (!/\.zip$/i.test(file.name)) {
    throw new Error(`Arquivo deve ser um .zip — recebi '${file.name}'.`);
  }
  onProgress?.({ phase: "reading", current: 0, total: 1 });

  const zip = await JSZip.loadAsync(file);
  const prefix = detectRootPrefix(zip);

  const bookJsonEntry = zip.file(`${prefix}book.json`);
  if (!bookJsonEntry) {
    throw new Error(
      "ZIP inválido: 'book.json' não encontrado na raiz. " +
        "Verifique se o livro foi gerado pelo backend ReaderFree.",
    );
  }

  onProgress?.({ phase: "validating", current: 0, total: 1 });
  const bookJsonText = await bookJsonEntry.async("string");
  let raw: unknown;
  try {
    raw = JSON.parse(bookJsonText);
  } catch (e) {
    throw new Error(`book.json não é JSON válido: ${(e as Error).message}`);
  }
  const manifest = validateManifest(raw);

  // Coleta de assets esperados — cada capítulo aponta para 3 arquivos.
  const expectedFiles = new Set<string>();
  for (const ch of manifest.chapters) {
    expectedFiles.add(ch.mp3_path);
    expectedFiles.add(ch.vtt_path);
    expectedFiles.add(ch.text_path);
  }

  // Confirma que todos os arquivos referenciados existem no ZIP.
  const missing: string[] = [];
  for (const filename of expectedFiles) {
    if (!zip.file(`${prefix}${filename}`)) {
      missing.push(filename);
    }
  }
  if (missing.length > 0) {
    throw new Error(
      `ZIP incompleto. Arquivos referenciados pelo book.json não encontrados:\n  ` +
        missing.slice(0, 5).join("\n  ") +
        (missing.length > 5 ? `\n  ... (+${missing.length - 5})` : ""),
    );
  }

  // Extrai e persiste cada asset.
  const total = expectedFiles.size;
  let current = 0;
  for (const filename of expectedFiles) {
    onProgress?.({ phase: "extracting", current, total, filename });
    const entry = zip.file(`${prefix}${filename}`)!;
    const blob = await entry.async("blob");
    // Force MIME type para o player tocar (jszip retorna octet-stream).
    const typedBlob = retypeBlob(blob, filename);
    await saveAsset(manifest.id, filename, typedBlob);
    current += 1;
  }

  await saveBook(manifest);
  onProgress?.({ phase: "done", current: total, total });
  return manifest;
}

/**
 * Detecta se o ZIP tem todo conteúdo dentro de uma pasta raiz (caso comum
 * quando o usuário roda `zip -r livro.zip livro/`). Retorna o prefixo a
 * remover (ex: `"livro/"`) ou string vazia se já está plano.
 */
function detectRootPrefix(zip: JSZip): string {
  // Se book.json está na raiz, sem prefixo.
  if (zip.file("book.json")) return "";
  // Senão, procura o primeiro `*/book.json` e usa o segmento como prefixo.
  let prefix = "";
  zip.forEach((path) => {
    if (prefix) return;
    const m = path.match(/^([^/]+\/)book\.json$/);
    if (m) prefix = m[1];
  });
  return prefix;
}

/**
 * Garante que o Blob tem MIME type apropriado para o `<audio>` reproduzir
 * (jszip por default retorna `application/octet-stream`).
 */
function retypeBlob(blob: Blob, filename: string): Blob {
  const ext = filename.split(".").pop()?.toLowerCase();
  const mime: Record<string, string> = {
    mp3: "audio/mpeg",
    vtt: "text/vtt",
    txt: "text/plain",
    json: "application/json",
  };
  const type = ext ? mime[ext] : undefined;
  return type ? blob.slice(0, blob.size, type) : blob;
}
