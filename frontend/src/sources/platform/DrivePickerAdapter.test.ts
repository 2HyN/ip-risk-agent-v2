import { afterEach, expect, test } from "vitest";

import { GoogleDrivePickerAdapter } from "./DrivePickerAdapter.js";

afterEach(() => {
  delete window.google;
  delete window.gapi;
});

test("Google Picker receives only runtime config/token and returns explicit file IDs", async () => {
  const observed: Record<string, string> = {};
  class DocsView {
    setIncludeFolders() { return this; }
    setSelectFolderEnabled() { return this; }
  }
  class PickerBuilder {
    private callback: ((data: { action?: unknown; docs?: unknown }) => void) | null = null;
    addView() { return this; }
    enableFeature() { return this; }
    setOAuthToken(value: string) { observed["token"] = value; return this; }
    setDeveloperKey(value: string) { observed["key"] = value; return this; }
    setAppId(value: string) { observed["appId"] = value; return this; }
    setOrigin(value: string) { observed["origin"] = value; return this; }
    setCallback(value: (data: { action?: unknown; docs?: unknown }) => void) { this.callback = value; return this; }
    build() {
      return { setVisible: () => this.callback?.({ action: "picked", docs: [{ id: "file-1", name: "Design", mimeType: "text/plain" }] }) };
    }
  }
  window.google = { picker: {
    Action: { PICKED: "picked" },
    Feature: { MULTISELECT_ENABLED: "multi" },
    ViewId: { DOCS: "docs" },
    DocsView,
    PickerBuilder,
  } };
  const picker = new GoogleDrivePickerAdapter(async () => ({
    enabled: true,
    browserApiKey: "restricted-browser-key",
    cloudProjectNumber: "123456789012",
  }));

  const files = await picker.pick("short-lived-oauth-token");

  expect(files).toEqual([{ id: "file-1", name: "Design", mimeType: "text/plain" }]);
  expect(observed).toMatchObject({
    token: "short-lived-oauth-token",
    key: "restricted-browser-key",
    appId: "123456789012",
  });
});
