/**
 * GitHub App 설치 직후 무엇을 감시할지 고르는 단계.
 *
 * App 설치는 "이 계정의 이 저장소들에 접근해도 좋다"까지만 정한다. 그중
 * 무엇을 실제로 감시할지는 별도 결정이며, Mount 를 만들어야 파이프라인이
 * 돈다. 이 단계가 없으면 연결은 됐는데 아무 일도 일어나지 않는다.
 */

import { useEffect, useState } from "react";

import type { GithubRepository, SourcesApi } from "./api/sourcesClient.js";

export type GithubRepositoryPickerProps = {
  api: SourcesApi;
  connectionId: string;
  riskWorkspaceId: string;
  onMounted: () => void;
};

export function GithubRepositoryPicker({
  api,
  connectionId,
  riskWorkspaceId,
  onMounted,
}: GithubRepositoryPickerProps) {
  const [repositories, setRepositories] = useState<GithubRepository[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    setRepositories(null);

    api
      .listGithubRepositories(connectionId)
      .then((repos) => {
        if (!cancelled) setRepositories(repos);
      })
      .catch((cause) => {
        // 원인을 삼키면 권한 문제인지 연결이 사라진 것인지 구분할 수 없다.
        console.error(cause);
        if (cancelled) return;
        const reason = cause instanceof Error ? cause.message : "";
        setError(
          reason.includes("404")
            ? "이 연결을 찾을 수 없습니다. GitHub 연결을 다시 시작해 주세요."
            : reason.includes("401") || reason.includes("403")
              ? "저장소 목록을 볼 권한이 없습니다."
              : "저장소 목록을 불러오지 못했습니다."
        );
      });

    return () => {
      cancelled = true;
    };
  }, [api, connectionId]);

  const mount = async (repository: GithubRepository) => {
    setError(null);
    setPending(repository.fullName);
    try {
      await api.createGithubMount({
        connectionId,
        riskWorkspaceId,
        owner: repository.owner,
        repo: repository.name,
      });
      onMounted();
    } catch (cause) {
      console.error(cause);
      const reason = cause instanceof Error ? cause.message : "";
      setError(
        reason.includes("409")
          ? "이미 감시 중인 저장소입니다."
          : `${repository.fullName} 를 연결하지 못했습니다.`
      );
    } finally {
      setPending(null);
    }
  };

  return (
    <section>
      <h2>감시할 저장소 선택</h2>
      <p>
        설치한 GitHub App 이 접근할 수 있는 저장소입니다. 고른 저장소만
        분석 대상이 됩니다.
      </p>

      {error && <p style={{ color: "red" }}>{error}</p>}

      {repositories === null && !error && <p>저장소를 불러오는 중입니다…</p>}

      {repositories?.length === 0 && (
        <p>
          이 설치에 포함된 저장소가 없습니다. GitHub 설정에서 저장소를 추가한
          뒤 다시 시도해 주세요.
        </p>
      )}

      <ul>
        {repositories?.map((repository) => (
          <li key={repository.id}>
            <button
              type="button"
              onClick={() => void mount(repository)}
              disabled={pending !== null}
            >
              {repository.fullName}
              {repository.private ? " (private)" : ""}
            </button>
            {pending === repository.fullName && <span> 연결 중…</span>}
          </li>
        ))}
      </ul>
    </section>
  );
}
