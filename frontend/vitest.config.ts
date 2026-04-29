import { defineConfig } from "vitest/config";

/**
 * Config mínima do Vitest. Por design, só testamos código de `src/lib/**`
 * (funções puras: parser VTT, busca binária, validação de manifest etc.).
 *
 * Componentes React (`src/components/**`) não são testados aqui — a unidade
 * útil é o smoke test no browser via `pnpm dev`. Vale a pena adicionar
 * testing-library + jsdom só quando virar problema concreto.
 */
export default defineConfig({
  test: {
    include: ["src/lib/**/*.test.ts"],
    environment: "node",
  },
  resolve: {
    alias: {
      "@": new URL("./src", import.meta.url).pathname,
    },
  },
});
