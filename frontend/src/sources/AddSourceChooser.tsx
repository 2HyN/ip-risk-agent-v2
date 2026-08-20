/**
 * Agent 2 Spec §39 "Add Source chooser". 지금은 기능 위주 — 스타일은
 * 다음 단계에서. Google Drive / GitHub는 실제 연결 라우터(OAuth/App
 * install 시작점)가 아직 없어서 onSelect 콜백만 호출하고, 실제 처리는
 * 상위 컴포넌트(또는 나중에 만들 라우터)가 담당한다.
 */

export type SourceProviderType = "GOOGLE_DRIVE" | "GITHUB" | "LOCAL";

export interface AddSourceChooserProps {
  onSelect: (type: SourceProviderType) => void;
  isDesktop: boolean;
}

export function AddSourceChooser({ onSelect, isDesktop }: AddSourceChooserProps) {
  return (
    <div>
      <h2>Add Source</h2>
      <button type="button" onClick={() => onSelect("GOOGLE_DRIVE")}>
        Google Drive
      </button>
      <button type="button" onClick={() => onSelect("GITHUB")}>
        GitHub Repository
      </button>
      <button type="button" onClick={() => onSelect("LOCAL")} disabled={!isDesktop}>
        Local Folder{isDesktop ? "" : " (Desktop only)"}
      </button>
    </div>
  );
}
