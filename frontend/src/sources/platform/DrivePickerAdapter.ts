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

type PickerDocument = Record<string, unknown>;
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
  setCallback(callback: (data: unknown) => void): PickerBuilderInstance;
  build(): PickerInstance;
}

interface DocsViewInstance {
  setIncludeFolders(value: boolean): DocsViewInstance;
  setSelectFolderEnabled(value: boolean): DocsViewInstance;
}

interface GooglePickerRuntime {
  Action: { CANCEL: string; ERROR: string; PICKED: string };
  Response: { ACTION: string; DOCUMENTS: string };
  Document: { ID: string; MIME_TYPE: string; NAME: string };
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
            const callbackData = asRecord(data);
            const action = callbackData?.[picker.Response.ACTION];
            reportPickerCallbackDiagnostic(data, action, picker);
            if (action === picker.Action.CANCEL) {
              resolve([]);
              return;
            }
            if (action === picker.Action.ERROR) {
              reportPickerFailure("picker_error");
              reject(new Error("Google Drive Picker reported an error"));
              return;
            }
            if (action !== picker.Action.PICKED) {
              // Runtime callbacks that are not one of Picker's documented terminal
              // actions must not settle the selection before PICKED/CANCEL/ERROR.
              return;
            }
            try {
              resolve(
                validateDocuments(
                  callbackData?.[picker.Response.DOCUMENTS],
                  picker.Document,
                ),
              );
            } catch {
              reportPickerFailure("invalid_documents");
              reject(new Error("Google Drive Picker returned invalid documents"));
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

function validateDocuments(
  value: unknown,
  fields: GooglePickerRuntime["Document"],
): DrivePickerFile[] {
  if (!Array.isArray(value) || value.length === 0) {
    throw new Error("Drive Picker returned no documents for PICKED action");
  }
  const ids = new Set<string>();
  return value.map((raw) => {
    if (typeof raw !== "object" || raw === null) {
      throw new Error("Drive Picker returned an invalid document");
    }
    const item = raw as PickerDocument;
    const id = item[fields.ID];
    const name = item[fields.NAME];
    const mimeType = item[fields.MIME_TYPE];
    if (typeof id !== "string" || !id || ids.has(id)) {
      throw new Error("Drive Picker returned an invalid or duplicate file ID");
    }
    ids.add(id);
    return {
      id,
      name: typeof name === "string" && name ? name : "Selected Drive file",
      mimeType: typeof mimeType === "string" ? mimeType : null,
    };
  });
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function reportPickerCallbackDiagnostic(
  payload: unknown,
  action: unknown,
  picker: GooglePickerRuntime,
): void {
  const record = asRecord(payload);
  console.info("[DrivePicker] callback diagnostic", {
    payloadType: typeof payload,
    keys: record === null ? [] : Object.keys(record),
    action: typeof action === "string" ? action : null,
    responseActionKey: picker.Response.ACTION,
    pickedAction: picker.Action.PICKED,
  });
}

function reportPickerFailure(code: string): void {
  console.error(`[DrivePicker] callback rejected: ${code}`);
}
