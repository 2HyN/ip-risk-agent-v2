import { afterEach, describe, expect, test, vi } from "vitest";

import { GoogleDrivePickerAdapter } from "./DrivePickerAdapter.js";

const responseFields = { ACTION: "action", DOCUMENTS: "docs" };
const documentFields = { ID: "id", MIME_TYPE: "mimeType", NAME: "name" };
const actions = { CANCEL: "cancel", ERROR: "error", PICKED: "picked" };

afterEach(() => {
  delete window.google;
  delete window.gapi;
  vi.restoreAllMocks();
});

function installPicker(
  callbackData: Record<string, unknown>,
  observed: Record<string, string> = {},
): void {
  class DocsView {
    setIncludeFolders() { return this; }
    setSelectFolderEnabled() { return this; }
  }
  class PickerBuilder {
    private callback: ((data: Record<string, unknown>) => void) | null = null;
    addView() { return this; }
    enableFeature() { return this; }
    setOAuthToken(value: string) { observed["token"] = value; return this; }
    setDeveloperKey(value: string) { observed["key"] = value; return this; }
    setAppId(value: string) { observed["appId"] = value; return this; }
    setOrigin(value: string) { observed["origin"] = value; return this; }
    setCallback(value: (data: Record<string, unknown>) => void) {
      this.callback = value;
      return this;
    }
    build() {
      return {
        setVisible: () => queueMicrotask(() => this.callback?.(callbackData)),
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

test("Google Picker parses the official PICKED response and document fields", async () => {
  const observed: Record<string, string> = {};
  installPicker({
    [responseFields.ACTION]: actions.PICKED,
    [responseFields.DOCUMENTS]: [
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
    ],
  }, observed);

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

test("Google Picker CANCEL resolves without a selection or diagnostic", async () => {
  const diagnostic = vi.spyOn(console, "error").mockImplementation(() => undefined);
  installPicker({ [responseFields.ACTION]: actions.CANCEL });

  await expect(adapter().pick("short-lived-oauth-token")).resolves.toEqual([]);
  expect(diagnostic).not.toHaveBeenCalled();
});

describe.each([
  ["missing action", {}],
  ["Picker error", { [responseFields.ACTION]: actions.ERROR }],
  ["PICKED without documents", { [responseFields.ACTION]: actions.PICKED }],
  ["PICKED with empty documents", {
    [responseFields.ACTION]: actions.PICKED,
    [responseFields.DOCUMENTS]: [],
  }],
  ["PICKED with malformed document", {
    [responseFields.ACTION]: actions.PICKED,
    [responseFields.DOCUMENTS]: [{ [documentFields.NAME]: "Missing ID" }],
  }],
] as const)("invalid callback: %s", (_label, callbackData) => {
  test("rejects instead of silently returning zero selected IDs", async () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    installPicker(callbackData);

    await expect(adapter().pick("short-lived-oauth-token")).rejects.toThrow();
  });
});

test("callback diagnostics never include the token or raw Drive metadata", async () => {
  const diagnostic = vi.spyOn(console, "error").mockImplementation(() => undefined);
  installPicker({
    [responseFields.ACTION]: actions.PICKED,
    [responseFields.DOCUMENTS]: [{
      [documentFields.ID]: "",
      [documentFields.NAME]: "confidential-acquisition-plan.docx",
      access_token: "short-lived-oauth-token",
    }],
  });

  await expect(adapter().pick("short-lived-oauth-token")).rejects.toThrow();

  const logged = JSON.stringify(diagnostic.mock.calls);
  expect(logged).toContain("invalid_documents");
  expect(logged).not.toContain("short-lived-oauth-token");
  expect(logged).not.toContain("confidential-acquisition-plan.docx");
});
