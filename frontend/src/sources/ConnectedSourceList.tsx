/**
 * 이 워크스페이스가 실제로 감시하고 있는 대상 목록.
 *
 * 연결만 만들고 Mount 가 없으면 아무것도 감시하지 않는다. 그런데 화면에
 * 아무 표시가 없으면 사용자는 연결이 실패했다고 오해한다. 그래서 "없음"도
 * 명시적으로 말한다.
 */

import type { Mount } from "./api/sourcesClient.js";

const STATUS_LABEL: Record<string, string> = {
  ACTIVE: "감시 중",
  SOURCE_OFFLINE: "원본에 접근할 수 없음",
  DISABLED: "중지됨",
  REVOKED: "권한이 회수됨",
};

export type ConnectedSourceListProps = {
  mounts: Mount[];
  loading: boolean;
  error: string | null;
  /** 없으면 제거 열을 그리지 않는다. 권한 판단은 backend 가 한다. */
  onRemove?: (mount: Mount) => void;
};

export function ConnectedSourceList({
  mounts,
  loading,
  error,
  onRemove,
}: ConnectedSourceListProps) {
  if (loading) {
    return <p>연결된 Source 를 불러오는 중입니다…</p>;
  }
  if (error) {
    return <p style={{ color: "red" }}>{error}</p>;
  }
  if (mounts.length === 0) {
    return (
      <p>
        아직 감시 중인 대상이 없습니다. 아래에서 Source 를 연결하고 저장소나
        폴더를 고르면 분석이 시작됩니다.
      </p>
    );
  }

  return (
    <table>
      <thead>
        <tr>
          <th scope="col">이름</th>
          <th scope="col">상태</th>
          <th scope="col">연결된 시각</th>
          {onRemove && <th scope="col">관리</th>}
        </tr>
      </thead>
      <tbody>
        {mounts.map((mount) => (
          <tr key={mount.id}>
            <td>{mount.alias}</td>
            {/* 모르는 상태값을 빈칸으로 두면 장애를 정상으로 오해한다. */}
            <td>{STATUS_LABEL[mount.status] ?? mount.status}</td>
            <td>{new Date(mount.createdAt).toLocaleString()}</td>
            {onRemove && (
              <td>
                <button type="button" onClick={() => onRemove(mount)}>
                  감시 중단
                </button>
              </td>
            )}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
