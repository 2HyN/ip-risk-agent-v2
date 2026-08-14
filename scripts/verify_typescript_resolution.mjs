import { createRequire } from "node:module";
import path from "node:path";

const requireFromWorkspace = createRequire(path.join(process.cwd(), "package.json"));
const target = requireFromWorkspace.resolve("@iprisk/contracts");
if (!target.replaceAll("\\", "/").endsWith("shared/contracts/typescript/dist/index.js")) {
  throw new Error(`Unexpected contract resolution: ${target}`);
}
console.log(target);
