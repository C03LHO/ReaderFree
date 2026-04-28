/**
 * Wrapper IndexedDB para a biblioteca local do ReaderFree.
 *
 * Stores:
 *   - `books`     : key=bookId, value=BookManifest (JSON inteiro do book.json).
 *   - `assets`    : key=`${bookId}/${filename}`, value={bookId, filename, blob}.
 *                   Guarda MP3/VTT/TXT por arquivo.
 *   - `progress`  : key=bookId, value=BookProgress.
 *   - `prefs`     : key="prefs" (singleton), value=Prefs.
 *
 * O quota do IndexedDB no iOS Safari aguenta livros grandes — Safari 17+ com
 * PWA instalada permite até 60% do disco. Ver:
 * https://webkit.org/blog/14403/updates-to-storage-policy/
 */
import { openDB, type DBSchema, type IDBPDatabase } from "idb";

import type { BookManifest, BookProgress, Prefs } from "./types";
import { DEFAULT_PREFS } from "./types";

const DB_NAME = "readerfree";
const DB_VERSION = 1;

interface ReaderFreeDB extends DBSchema {
  books: {
    key: string; // bookId
    value: BookManifest;
  };
  assets: {
    key: string; // `${bookId}/${filename}`
    value: {
      bookId: string;
      filename: string;
      blob: Blob;
    };
    indexes: { "by-book": string };
  };
  progress: {
    key: string; // bookId
    value: BookProgress;
  };
  prefs: {
    key: string; // "prefs"
    value: Prefs;
  };
}

let _dbPromise: Promise<IDBPDatabase<ReaderFreeDB>> | null = null;

function getDB(): Promise<IDBPDatabase<ReaderFreeDB>> {
  if (_dbPromise) return _dbPromise;
  _dbPromise = openDB<ReaderFreeDB>(DB_NAME, DB_VERSION, {
    upgrade(db) {
      if (!db.objectStoreNames.contains("books")) {
        db.createObjectStore("books", { keyPath: "id" });
      }
      if (!db.objectStoreNames.contains("assets")) {
        const assetsStore = db.createObjectStore("assets");
        assetsStore.createIndex("by-book", "bookId");
      }
      if (!db.objectStoreNames.contains("progress")) {
        db.createObjectStore("progress", { keyPath: "bookId" });
      }
      if (!db.objectStoreNames.contains("prefs")) {
        db.createObjectStore("prefs");
      }
    },
  });
  return _dbPromise;
}

// -------------------------------------------------------------------------
// books
// -------------------------------------------------------------------------

export async function listBooks(): Promise<BookManifest[]> {
  const db = await getDB();
  return db.getAll("books");
}

export async function getBook(bookId: string): Promise<BookManifest | undefined> {
  const db = await getDB();
  return db.get("books", bookId);
}

export async function saveBook(manifest: BookManifest): Promise<void> {
  const db = await getDB();
  await db.put("books", manifest);
}

export async function deleteBook(bookId: string): Promise<void> {
  const db = await getDB();
  const tx = db.transaction(["books", "assets", "progress"], "readwrite");
  await tx.objectStore("books").delete(bookId);
  // Apaga todos os assets que pertencem ao livro.
  const assetsStore = tx.objectStore("assets");
  const idx = assetsStore.index("by-book");
  let cursor = await idx.openCursor(IDBKeyRange.only(bookId));
  while (cursor) {
    await cursor.delete();
    cursor = await cursor.continue();
  }
  await tx.objectStore("progress").delete(bookId);
  await tx.done;
}

// -------------------------------------------------------------------------
// assets (mp3, vtt, txt)
// -------------------------------------------------------------------------

export async function saveAsset(
  bookId: string,
  filename: string,
  blob: Blob,
): Promise<void> {
  const db = await getDB();
  const key = `${bookId}/${filename}`;
  await db.put("assets", { bookId, filename, blob }, key);
}

export async function getAsset(
  bookId: string,
  filename: string,
): Promise<Blob | undefined> {
  const db = await getDB();
  const entry = await db.get("assets", `${bookId}/${filename}`);
  return entry?.blob;
}

/**
 * Soma de bytes ocupados por um livro (mp3 + vtt + txt). Útil para a
 * tela "downloads" que vai aparecer na Fase 6.
 */
export async function bookSizeBytes(bookId: string): Promise<number> {
  const db = await getDB();
  const tx = db.transaction("assets");
  const idx = tx.store.index("by-book");
  let cursor = await idx.openCursor(IDBKeyRange.only(bookId));
  let total = 0;
  while (cursor) {
    total += cursor.value.blob.size;
    cursor = await cursor.continue();
  }
  return total;
}

// -------------------------------------------------------------------------
// progress
// -------------------------------------------------------------------------

export async function getProgress(bookId: string): Promise<BookProgress | undefined> {
  const db = await getDB();
  return db.get("progress", bookId);
}

export async function saveProgress(progress: BookProgress): Promise<void> {
  const db = await getDB();
  await db.put("progress", progress);
}

// -------------------------------------------------------------------------
// prefs (singleton)
// -------------------------------------------------------------------------

const PREFS_KEY = "prefs";

export async function getPrefs(): Promise<Prefs> {
  const db = await getDB();
  const stored = await db.get("prefs", PREFS_KEY);
  return stored ?? DEFAULT_PREFS;
}

export async function savePrefs(prefs: Prefs): Promise<void> {
  const db = await getDB();
  await db.put("prefs", prefs, PREFS_KEY);
}
