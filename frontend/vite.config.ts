import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  // tsc의 dist/(node:test용 컴파일 결과물)와 겹치지 않게 분리한다.
  build: {
    outDir: "dist/web",
  },
});
