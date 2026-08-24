import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // 기본값은 README 의 로컬 실행 그대로다. 8000 이 이미 쓰이고 있을 때
      // (v1 데스크톱 앱이 그렇다) 백엔드를 다른 포트로 띄우기 위해서만 바꾼다.
      "/api": process.env.IPRISK_API_PROXY ?? "http://127.0.0.1:8000",
    },
  },
  build: { sourcemap: true },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: true,
  },
});
