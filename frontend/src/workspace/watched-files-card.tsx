/**
 * Overview 의 "감시 중인 파일" 카드.
 *
 * 연결 화면은 Mount 단위까지만 보여준다. 그런데 사용자가 폴더를 통째로
 * 연결하면 정작 "그 안의 어떤 파일이 인식됐는지"가 어디에도 없다 — Drive
 * 화면을 다시 열어 눈으로 대조하는 수밖에 없었다. 여기서 Mount 별로 감시
 * 파일 목록을 폴더 경로 순으로 펼쳐 보여준다.
 *
 * 목록은 Control 의 mounts(canonical)에서 시작하고, 파일 상세는 Integration
 * 의 추적 스코프에서 온다. 원문이 아니라 경로와 개수뿐이다.
 */

import { useEffect, useState } from "react";

import { useSession } from "../auth/session";
import {
  HttpSourcesApi,
  type TrackedFiles,
} from "../sources/api/sourcesClient.js";
import { Badge, Card } from "../shared/ui";
import { useWorkspace } from "./workspace-context";

type MountFiles = {
  mountId: string;
  alias: string;
  tracked: TrackedFiles | null;
};

const sourcesApi = new HttpSourcesApi("");

export function WatchedFilesCard() {
  const { api } = useSession();
  const { workspace } = useWorkspace();
  const [rows, setRows] = useState<MountFiles[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setRows(null);
    setError(null);

    (async () => {
      const page = await api.mounts(workspace.id);
      const loaded = await Promise.all(
        page.items.map(async (mount) => {
          try {
            return {
              mountId: mount.id,
              alias: mount.alias,
              tracked: await sourcesApi.listTrackedFiles(mount.id),
            };
          } catch (cause) {
            // 한 Mount 의 실패가 카드 전체를 비우면 안 된다.
            console.error(cause);
            return { mountId: mount.id, alias: mount.alias, tracked: null };
          }
        }),
      );
      if (!cancelled) setRows(loaded);
    })().catch((cause) => {
      console.error(cause);
      if (!cancelled) setError("감시 중인 파일 목록을 불러오지 못했습니다.");
    });

    return () => {
      cancelled = true;
    };
  }, [api, workspace.id]);

  const totalFiles = (rows ?? []).reduce(
    (sum, row) => sum + (row.tracked?.files.length ?? 0),
    0,
  );

  return (
    <Card>
      <div className="section-heading">
        <div>
          <p className="eyebrow">Watched files</p>
          <h2>감시 중인 파일</h2>
        </div>
        {rows !== null && <Badge tone="info">{totalFiles} files</Badge>}
      </div>

      {error && <p style={{ color: "red" }}>{error}</p>}
      {rows === null && !error && <p>불러오는 중…</p>}
      {rows !== null && rows.length === 0 && (
        <p>연결된 Source 가 없습니다. Sources 화면에서 연결해 주세요.</p>
      )}

      {rows?.map((row) => (
        <details key={row.mountId} className="watched-files__mount" open>
          <summary>
            <strong>{row.alias}</strong>
            {row.tracked?.files.length ? (
              <small> · 파일 {row.tracked.files.length}개</small>
            ) : null}
          </summary>
          {row.tracked === null ? (
            <p>목록을 불러오지 못했습니다.</p>
          ) : row.tracked.descriptor ? (
            <p className="tracked-files__descriptor">{row.tracked.descriptor}</p>
          ) : row.tracked.files.length === 0 ? (
            <p>감시 중인 파일이 없습니다.</p>
          ) : (
            <ul className="tracked-files__list">
              {row.tracked.files.map((file) => (
                <li key={file.id}>
                  <code>{file.path}</code>
                </li>
              ))}
            </ul>
          )}
        </details>
      ))}
    </Card>
  );
}
