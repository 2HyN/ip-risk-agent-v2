import { dialog } from "electron";

import type { DirectoryPicker } from "../core/local-source-service.js";

export class ElectronDirectoryPicker implements DirectoryPicker {
  async pickDirectory(): Promise<string | null> {
    const result = await dialog.showOpenDialog({ properties: ["openDirectory"] });
    if (result.canceled || result.filePaths.length === 0) {
      return null;
    }
    return result.filePaths[0] ?? null;
  }
}
