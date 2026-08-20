import type { DrivePickerRuntimeConfig } from "../api/connectionClient.js";

export interface DrivePickerFile {
  id: string;
  name: string;
  mimeType: string | null;
}

export interface DrivePickerAdapter {
  readonly available: boolean;
  pick(accessToken: string): Promise<DrivePickerFile[]>;
}

type RuntimeConfigProvider = () => Promise<DrivePickerRuntimeConfig>;

type PickerDocument = {
  id?: unknown;
  name?: unknown;
  mimeType?: unknown;
};

type PickerCallbackData = {
  action?: unknown;
  docs?: unknown;
};

interface PickerInstance {
  setVisible(visible: boolean): void;
}

interface PickerBuilderInstance {
  addView(view: unknown): PickerBuilderInstance;
  enableFeature(feature: string): PickerBuilderInstance;
  setOAuthToken(token: string): PickerBuilderInstance;
  setDeveloperKey(key: string): PickerBuilderInstance;
  setAppId(appId: string): PickerBuilderInstance;
  setOrigin(origin: string): PickerBuilderInstance;
  setCallback(callback: (data: PickerCallbackData) => void): PickerBuilderInstance;
  build(): PickerInstance;
}

interface DocsViewInstance {
  setIncludeFolders(value: boolean): DocsViewInstance;
  setSelectFolderEnabled(value: boolean): DocsViewInstance;
}

interface GooglePickerRuntime {
  Action: { PICKED: string };
  Feature: { MULTISELECT_ENABLED: string };
  ViewId: { DOCS: string };
  DocsView: new (viewId: string) => DocsViewInstance;
  PickerBuilder: new () => PickerBuilderInstance;
}

declare global {
  interface Window {
    gapi?: { load(name: string, callback: () => void): void };
    google?: { picker?: GooglePickerRuntime };
  }
}

let pickerScript: Promise<void> | null = null;

export class GoogleDrivePickerAdapter implements DrivePickerAdapter {
  readonly available = true;

  constructor(private readonly runtimeConfig: RuntimeConfigProvider) {}

  async pick(accessToken: string): Promise<DrivePickerFile[]> {
    const config = await this.runtimeConfig();
    if (
      !config.enabled ||
      config.browserApiKey === null ||
      config.cloudProjectNumber === null
    ) {
      throw new Error("Google Drive Picker runtime is not configured");
    }
    await loadPickerRuntime();
    const picker = window.google?.picker;
    if (picker === undefined) throw new Error("Google Drive Picker failed to load");
    return new Promise((resolve, reject) => {
      try {
        const view = new picker.DocsView(picker.ViewId.DOCS)
          .setIncludeFolders(true)
          .setSelectFolderEnabled(false);
        new picker.PickerBuilder()
          .addView(view)
          .enableFeature(picker.Feature.MULTISELECT_ENABLED)
          .setOAuthToken(accessToken)
          .setDeveloperKey(config.browserApiKey!)
          .setAppId(config.cloudProjectNumber!)
          .setOrigin(window.location.origin)
          .setCallback((data) => {
            if (data.action !== picker.Action.PICKED) {
              resolve([]);
              return;
            }
            try {
              resolve(validateDocuments(data.docs));
            } catch (reason) {
              reject(reason);
            }
          })
          .build()
          .setVisible(true);
      } catch (reason) {
        reject(reason);
      }
    });
  }
}

function loadPickerRuntime(): Promise<void> {
  if (window.google?.picker !== undefined) return Promise.resolve();
  if (window.gapi !== undefined) {
    return new Promise((resolve) => window.gapi!.load("picker", resolve));
  }
  pickerScript ??= new Promise((resolve, reject) => {
    const existing = document.querySelector<HTMLScriptElement>("script[data-iprisk-google-picker]");
    const script = existing ?? document.createElement("script");
    script.addEventListener("error", () => reject(new Error("Google Picker script failed to load")), { once: true });
    script.addEventListener("load", () => {
      if (window.gapi === undefined) {
        reject(new Error("Google Picker loader is unavailable"));
        return;
      }
      window.gapi.load("picker", resolve);
    }, { once: true });
    if (existing === null) {
      script.src = "https://apis.google.com/js/api.js";
      script.async = true;
      script.dataset["ipriskGooglePicker"] = "true";
      document.head.append(script);
    }
  });
  return pickerScript;
}

function validateDocuments(value: unknown): DrivePickerFile[] {
  if (!Array.isArray(value)) throw new Error("Drive Picker returned invalid documents");
  const ids = new Set<string>();
  return value.map((raw) => {
    const item = raw as PickerDocument;
    if (typeof item.id !== "string" || !item.id || ids.has(item.id)) {
      throw new Error("Drive Picker returned an invalid or duplicate file ID");
    }
    ids.add(item.id);
    return {
      id: item.id,
      name: typeof item.name === "string" && item.name ? item.name : "Selected Drive file",
      mimeType: typeof item.mimeType === "string" ? item.mimeType : null,
    };
  });
}
