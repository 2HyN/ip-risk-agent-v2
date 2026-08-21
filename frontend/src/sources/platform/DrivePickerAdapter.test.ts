import { afterEach, describe, expect, test, vi } from "vitest";

import { GoogleDrivePickerAdapter } from "./DrivePickerAdapter.js";

const responseFields = { ACTION: "action", DOCUMENTS: "docs" };
const documentFields = { ID: "id", MIME_TYPE: "mimeType", NAME: "name" };
const actions = { CANCEL: "cancel", ERROR: "error", PICKED: "picked" };
const picked = (documents: unknown) => ({
  [responseFields.ACTION]: actions.PICKED,
  [responseFields.DOCUMENTS]: documents,
});

afterEach(() => {
  delete window.google;
  delete window.gapi;
  vi.restoreAllMocks();
});

function installPicker(
  callbackSequence: readonly unknown[],
  observed: Record<string, string> = {},
): void {
  class DocsView {
    setIncludeFolders() { return this; }
    setSelectFolderEnabled() { return this; }
  }
  class PickerBuilder {
    private callback: ((data: unknown) => void) | null = null;
    addView() { return this; }
    enableFeature() { return this; }
    setOAuthToken(value: string) { observed["token"] = value; return this; }
    setDeveloperKey(value: string) { observed["key"] = value; return this; }
    setAppId(value: string) { observed["appId"] = value; return this; }
    setOrigin(value: string) { observed["origin"] = value; return this; }
    setCallback(value: (data: unknown) => void) {
      this.callback = value;
      return this;
    }
    build() {
      return {
        setVisible: () => queueMicrotask(() => {
          for (const data of callbackSequence) this.callback?.(data);
        }),
      };
    }
  }
  window.google = { picker: {
    Action: actions,
    Response: responseFields,
    Document: documentFields,
    Feature: { MULTISELECT_ENABLED: "multiselectEnabled" },
    ViewId: { DOCS: "all" },
    DocsView,
    PickerBuilder,
  } };
}

function adapter(): GoogleDrivePickerAdapter {
  return new GoogleDrivePickerAdapter(async () => ({
    enabled: true,
    browserApiKey: "restricted-browser-key",
    cloudProjectNumber: "123456789012",
  }));
}

const validDocuments = [
  {
    [documentFields.ID]: "file-1",
    [documentFields.NAME]: "Design",
    [documentFields.MIME_TYPE]: "text/plain",
  },
  {
    [documentFields.ID]: "file-2",
    [documentFields.NAME]: "Claims",
    [documentFields.MIME_TYPE]: "application/pdf",
  },
];

test("Google Picker parses the official PICKED response and document fields", async () => {
  const observed: Record<string, string> = {};
  vi.spyOn(console, "info").mockImplementation(() => undefined);
  installPicker([picked(validDocuments)], observed);

  const files = await adapter().pick("short-lived-oauth-token");

  expect(files).toEqual([
    { id: "file-1", name: "Design", mimeType: "text/plain" },
    { id: "file-2", name: "Claims", mimeType: "application/pdf" },
  ]);
  expect(observed).toMatchObject({
    token: "short-lived-oauth-token",
    key: "restricted-browser-key",
    appId: "123456789012",
  });
});

test("Google Picker CANCEL is a terminal empty selection", async () => {
  const diagnostic = vi.spyOn(console, "info").mockImplementation(() => undefined);
  installPicker([{ [responseFields.ACTION]: actions.CANCEL }]);

  await expect(adapter().pick("short-lived-oauth-token")).resolves.toEqual([]);
  expect(diagnostic).toHaveBeenCalledOnce();
});

test("Google Picker ERROR is a terminal failure", async () => {
  vi.spyOn(console, "info").mockImplementation(() => undefined);
  vi.spyOn(console, "error").mockImplementation(() => undefined);
  installPicker([{ [responseFields.ACTION]: actions.ERROR }]);

  await expect(adapter().pick("short-lived-oauth-token")).rejects.toThrow(
    "reported an error",
  );
});

test("an intermediate unknown action does not settle before PICKED", async () => {
  const diagnostic = vi.spyOn(console, "info").mockImplementation(() => undefined);
  installPicker([
    { [responseFields.ACTION]: "loaded", view: "all" },
    picked(validDocuments),
  ]);

  await expect(adapter().pick("short-lived-oauth-token")).resolves.toHaveLength(2);

  expect(diagnostic).toHaveBeenCalledTimes(2);
  expect(diagnostic.mock.calls[0]?.[1]).toEqual({
    payloadType: "object",
    keys: ["action", "view"],
    action: "loaded",
    responseActionKey: "action",
    pickedAction: "picked",
  });
});

test("a malformed payload is ignored until a terminal callback arrives", async () => {
  const diagnostic = vi.spyOn(console, "info").mockImplementation(() => undefined);
  installPicker([null, picked(validDocuments)]);

  await expect(adapter().pick("short-lived-oauth-token")).resolves.toHaveLength(2);

  expect(diagnostic.mock.calls[0]?.[1]).toEqual({
    payloadType: "object",
    keys: [],
    action: null,
    responseActionKey: "action",
    pickedAction: "picked",
  });
});

describe.each([
  ["PICKED without documents", picked(undefined)],
  ["PICKED with empty documents", picked([])],
  ["PICKED with malformed document", picked([
    { [documentFields.NAME]: "Missing ID" },
  ])],
] as const)("invalid terminal callback: %s", (_label, callbackData) => {
  test("rejects invalid PICKED documents", async () => {
    vi.spyOn(console, "info").mockImplementation(() => undefined);
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    installPicker([callbackData]);

    await expect(adapter().pick("short-lived-oauth-token")).rejects.toThrow(
      "invalid documents",
    );
  });
});

test("callback diagnostics never include the token, docs, or raw Drive metadata", async () => {
  const callbackDiagnostic = vi.spyOn(console, "info").mockImplementation(() => undefined);
  const failureDiagnostic = vi.spyOn(console, "error").mockImplementation(() => undefined);
  installPicker([picked([{
    [documentFields.ID]: "",
    [documentFields.NAME]: "confidential-acquisition-plan.docx",
    access_token: "short-lived-oauth-token",
  }])]);

  await expect(adapter().pick("short-lived-oauth-token")).rejects.toThrow();

  const logged = JSON.stringify([
    callbackDiagnostic.mock.calls,
    failureDiagnostic.mock.calls,
  ]);
  expect(logged).toContain("invalid_documents");
  expect(logged).toContain("docs");
  expect(logged).not.toContain("short-lived-oauth-token");
  expect(logged).not.toContain("confidential-acquisition-plan.docx");
});
