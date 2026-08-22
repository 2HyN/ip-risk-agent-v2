/**
 * 이 워크스페이스가 실제로 감시하고 있는 대상 목록.
 *
 * 연결만 만들고 Mount 가 없으면 아무것도 감시하지 않는다. 그런데 화면에
 * 아무 표시가 없으면 사용자는 연결이 실패했다고 오해한다. 그래서 "없음"도
 * 명시적으로 말한다.
 *
 * 각 Mount 는 펼쳐서 감시 중인 파일 목록을 볼 수 있다. 폴더를 연결한 뒤
 * "무엇이 인식됐는지" 확인할 수 있는 유일한 자리다.
 */

import { useState } from "react";

import type { Mount, TrackedFiles } from "./api/sourcesClient.js";

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
  /** 표시 이름 변경. 실제 폴더/저장소 이름은 건드리지 않는다. */
  onRename?: (mount: Mount) => void;
  /** 없으면 파일 펼침을 그리지 않는다. */
  loadFiles?: (mount: Mount) => Promise<TrackedFiles>;
};

function TrackedFilesPanel({ data }: { data: TrackedFiles }) {
  if (data.descriptor) {
    return <p className="tracked-files__descriptor">{data.descriptor}</p>;
  }
  if (data.files.length === 0) {
    return <p>감시 중인 파일이 없습니다.</p>;
  }
  return (
    <>
      <p className="tracked-files__count">파일 {data.files.length}개</p>
      <ul className="tracked-files__list">
        {data.files.map((file) => (
          <li key={file.id}>
            <code>{file.path}</code>
          </li>
        ))}
      </ul>
    </>
  );
}

export function ConnectedSourceList({
  mounts,
  loading,
  error,
  onRemove,
  onRename,
  loadFiles,
}: ConnectedSourceListProps) {
  const [expanded, setExpanded] = useState<string | null>(null);
  const [filesByMount, setFilesByMount] = useState<Record<string, TrackedFiles>>({});
  const [filesError, setFilesError] = useState<string | null>(null);

  const toggle = async (mount: Mount) => {
    if (expanded === mount.id) {
      setExpanded(null);
      return;
    }
    setExpanded(mount.id);
    setFilesError(null);
    if (!loadFiles || filesByMount[mount.id]) return;
    try {
      const data = await loadFiles(mount);
      setFilesByMount((prev) => ({ ...prev, [mount.id]: data }));
    } catch (cause) {
      console.error(cause);
      setFilesError("파일 목록을 불러오지 못했습니다.");
    }
  };

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

  const columns = 3 + (loadFiles ? 1 : 0) + (onRemove ? 1 : 0);

  return (
    <table>
      <thead>
        <tr>
          <th scope="col">이름</th>
          <th scope="col">상태</th>
          <th scope="col">연결된 시각</th>
          {loadFiles && <th scope="col">파일</th>}
          {onRemove && <th scope="col">관리</th>}
        </tr>
      </thead>
      <tbody>
        {mounts.map((mount) => (
          <>
            <tr key={mount.id}>
              <td>{mount.alias}</td>
              {/* 모르는 상태값을 빈칸으로 두면 장애를 정상으로 오해한다. */}
              <td>{STATUS_LABEL[mount.status] ?? mount.status}</td>
              <td>{new Date(mount.createdAt).toLocaleString()}</td>
              {loadFiles && (
                <td>
                  <button type="button" onClick={() => void toggle(mount)}>
                    {expanded === mount.id ? "접기" : "파일 보기"}
                  </button>
                </td>
              )}
              {onRemove && (
                <td>
                  {onRename && (
                    <button
                      type="button"
                      onClick={() => onRename(mount)}
                      title="표시 이름 변경 (실제 폴더 이름은 그대로)"
                    >
                      이름 변경
                    </button>
                  )}{" "}
                  <button type="button" onClick={() => onRemove(mount)}>
                    감시 중단
                  </button>
                </td>
              )}
            </tr>
            {expanded === mount.id && (
              <tr key={`${mount.id}-files`}>
                <td colSpan={columns}>
                  {(() => {
                    const data = filesByMount[mount.id];
                    if (filesError) {
                      return <p style={{ color: "red" }}>{filesError}</p>;
                    }
                    if (data) return <TrackedFilesPanel data={data} />;
                    return <p>불러오는 중…</p>;
                  })()}
                </td>
              </tr>
            )}
          </>
        ))}
      </tbody>
    </table>
  );
}
