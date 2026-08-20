import { shell } from "electron";

import type { ArtifactOpener } from "../core/local-source-service.js";

export class ElectronArtifactOpener implements ArtifactOpener {
  async openPath(absolutePath: string): Promise<string> {
    return shell.openPath(absolutePath);
  }

  showInFolder(absolutePath: string): void {
    shell.showItemInFolder(absolutePath);
  }
}
