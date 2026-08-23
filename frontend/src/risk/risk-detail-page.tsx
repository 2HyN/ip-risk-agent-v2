import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useSession } from "../auth/session";
import { formatDate, humanize, shortRevision } from "../shared/format";
import { useResource } from "../shared/hooks/use-resource";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  Field,
  LoadingState,
  PageHeader,
  Select,
  Textarea,
  toneFor,
} from "../shared/ui";
import type { Evidence, Risk, RiskDetail } from "../shared/api/types";
import { EvidenceExcerpt } from "./evidence-highlight.js";
import { useWorkspace } from "../workspace/workspace-context";
import { useIntegration } from "../app/integration-context";

export function RiskDetailPage() {
  const { riskId = "" } = useParams();
  const { api } = useSession();
  const { workspace, canReview } = useWorkspace();
  const integration = useIntegration();
  const resource = useResource(
    () => api.risk(workspace.id, riskId),
    [api, workspace.id, riskId],
  );
  // v1(integration) 의 Reviewer decision 형태를 그대로 쓴다 — 처분 선택,
  // Comment, Save decision. 처분만 v3 도메인에 맞춘다 (EXCLUDED 는 시스템 전용).
  const [disposition, setDisposition] =
    useState<Risk["review_disposition"]>("UNREVIEWED");
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [mutationError, setMutationError] = useState<Error | null>(null);
  const [openNotice, setOpenNotice] = useState<string | null>(null);

  async function review(disposition: Risk["review_disposition"]) {
    if (resource.data === null) return;
    setBusy(true);
    setMutationError(null);
    try {
      await api.reviewRisk(workspace.id, riskId, {
        expected_review_version: resource.data.risk.review_version,
        disposition,
        comment: comment.trim() === "" ? null : comment,
      });
      setComment("");
      resource.reload();
    } catch (reason) {
      setMutationError(
        reason instanceof Error
          ? reason
          : new Error("Review could not be saved"),
      );
    } finally {
      setBusy(false);
    }
  }

  function openOriginal(): void {
    setOpenNotice(null);
    const handler = integration.openOriginal;
    if (handler === undefined || resource.data === null) return;
    // 실패를 삼키면 버튼이 "안 눌리는" 것처럼 보인다 — Local 원문은 등록된
    // 데스크톱에서만 열리므로, 웹에서는 그 사실을 말해 준다.
    void Promise.resolve(
      handler({
        workspaceId: workspace.id,
        artifactId: resource.data.open_original.artifact_id,
        action: resource.data.open_original.action,
        sourceType: resource.data.risk.source_type,
      }),
    ).catch((reason: unknown) => {
      setOpenNotice(
        resource.data?.risk.source_type === "LOCAL"
          ? "Local 파일의 원문은 그 파일을 등록한 데스크톱 앱에서만 열 수 있습니다."
          : reason instanceof Error
            ? reason.message
            : "원문을 여는 데 실패했습니다.",
      );
    });
  }

  if (resource.loading) return <LoadingState label="Loading risk detail" />;
  if (resource.error !== null)
    return <ErrorState error={resource.error} retry={resource.reload} />;
  const detail = resource.data;
  if (detail === null) return null;
  const risk = detail.risk;
  const openLabel =
    risk.source_type === "GOOGLE_DRIVE"
      ? "Open in Google Drive"
      : risk.source_type === "GITHUB"
        ? "Open on GitHub"
        : risk.source_type === "LOCAL"
          ? "Open on owning desktop"
          : "Open original";
  return (
    <div className="content risk-detail">
      <PageHeader
        eyebrow={`${risk.analysis_type} · ${risk.artifact_display_name ?? risk.artifact_id}`}
        title={risk.summary}
        description={`First detected ${formatDate(risk.first_seen_at)}`}
        actions={
          <div className="button-row">
            <Button
              variant="secondary"
              disabled={integration.openOriginal === undefined}
              title={
                integration.openOriginal === undefined
                  ? "Source resolver is connected by Integration"
                  : undefined
              }
              onClick={openOriginal}
            >
              {openLabel} ↗
            </Button>
            <Link
              className="button button--secondary"
              to={`/w/${workspace.id}/risks/${risk.id}/timeline`}
            >
              Full timeline
            </Link>
          </div>
        }
      />
      {openNotice === null ? null : (
        <p className="source-selection" role="status">{openNotice}</p>
      )}
      {mutationError === null ? null : <ErrorState error={mutationError} />}
      <div className="detail-grid">
        <div className="detail-main">
          <Card>
            <div className="status-grid">
              <Status label="Priority" value={risk.review_priority} />
              <Status label="Machine lifecycle" value={risk.lifecycle_state} />
              <Status
                label="Reviewer decision"
                value={risk.review_disposition}
              />
              <Status label="Last seen" value={formatDate(risk.last_seen_at)} />
            </div>
          </Card>
          <EvidenceComparison
            detail={detail}
            openLabel={openLabel}
            onOpenOriginal={openOriginal}
          />
          {risk.explanation_safe === null && risk.recommendation_safe === null ? null : (
            <Card>
              <p className="eyebrow">설명 · 권고</p>
              {risk.explanation_safe === null ? null : (
                <>
                  <h2>왜 검토가 필요한가</h2>
                  <p>{risk.explanation_safe}</p>
                </>
              )}
              {risk.recommendation_safe === null ? null : (
                <>
                  <h2>무엇을 하면 되는가</h2>
                  <p>{risk.recommendation_safe}</p>
                </>
              )}
              <p className="fine-print">
                모델이 근거를 읽고 쓴 설명입니다. 판정을 바꾸지 않으며 법적 결론이
                아닙니다. 실제 판단은 사람과 전문가의 검토가 필요합니다.
              </p>
            </Card>
          )}
          {/* Analysis metadata 카드는 뺐다 — 실행 id·판본은 사람의 판단에 쓰이지
              않고, 경로는 이미 머리글에 있다. */}
        </div>
        <aside>
          {risk.review_disposition === "EXCLUDED" ? (
            <Card>
              <p className="eyebrow">Excluded</p>
              <h2>추적이 끝난 Risk</h2>
              <p>
                이 Risk 가 나온 파일은 더 이상 추적되지 않습니다. 파일 추적을 끊었거나
                소스 연결을 일시중지했을 때 이렇게 됩니다. 근거와 이력은 그대로 남아
                있어 언제든 다시 볼 수 있습니다.
              </p>
              <p className="fine-print">
                다시 검토하려면 그 파일을 다시 추적하세요. 그러면 이 Risk 가 미검토
                상태로 되살아납니다.
              </p>
            </Card>
          ) : canReview ? (
            <Card className="review-card">
              <p className="eyebrow">Reviewer decision</p>
              <h2>Record disposition</h2>
              <form
                onSubmit={(event) => {
                  event.preventDefault();
                  void review(disposition);
                }}
              >
                <Field label="Disposition">
                  <Select
                    value={disposition}
                    onChange={(event) =>
                      setDisposition(
                        event.target.value as Risk["review_disposition"],
                      )
                    }
                  >
                    {/*
                      Excluded 는 여기에 없다. 파일 추적 중단처럼 사용자 판단 밖의
                      요인으로 관리가 끝났다는 뜻이라 시스템만 붙인다. 스스로
                      감시를 그만두는 것은 Accepted risk 다.
                    */}
                    <option value="UNREVIEWED">Unreviewed</option>
                    <option value="MONITORING">Monitoring</option>
                    <option value="ACCEPTED_RISK">Accepted risk</option>
                  </Select>
                </Field>
                <Field
                  label="Comment"
                  hint="Optional · retained in append-only history"
                >
                  <Textarea
                    rows={5}
                    maxLength={2000}
                    value={comment}
                    onChange={(event) => setComment(event.target.value)}
                  />
                </Field>
                <Button disabled={busy}>
                  {busy ? "Saving…" : "Save decision"}
                </Button>
              </form>
              <p className="fine-print">
                This changes human disposition only. Machine lifecycle is
                controlled by authoritative analysis.
              </p>
            </Card>
          ) : (
            <Card>
              <h2>Read-only access</h2>
              <p>
                Your role can inspect risk and evidence but cannot submit
                reviewer decisions.
              </p>
            </Card>
          )}
        </aside>
      </div>
    </div>
  );
}

/**
 * 원본 ↔ 근거 대조.
 *
 * 특허는 **좌우**다 — 내 문서의 어느 문장이 어느 청구항·초록과 겹치는지를 나란히
 * 놓고 본다. 라이선스는 **상하**다 — 패키지 정보는 짧고 라이선스 전문은 길어서,
 * 옆에 붙이면 한쪽이 짜부라진다. 문제가 된 구간은 두 쪽 모두 하이라이트로 짚는다
 * (EvidenceExcerpt). 원문 전체는 여기 없다 — 남긴 발췌만 보여 주고, 실제 원본과
 * 근거 문서는 아래 링크로 나간다.
 */
function EvidenceComparison({
  detail,
  openLabel,
  onOpenOriginal,
}: {
  detail: RiskDetail;
  openLabel: string;
  onOpenOriginal: () => void;
}) {
  const risk = detail.risk;
  const source = detail.evidence.filter(
    (item) => item.evidence_type === "SOURCE_EXCERPT",
  );
  const patent = detail.evidence.filter((item) =>
    ["PATENT_CLAIM", "PATENT_ABSTRACT"].includes(item.evidence_type),
  );
  const license = detail.evidence.filter(
    (item) => item.evidence_type === "LICENSE_REFERENCE",
  );
  const packageMetadata = detail.evidence.filter(
    (item) => item.evidence_type === "PACKAGE_METADATA",
  );
  const references = detail.evidence.filter(
    (item) => item.evidence_type === "RAG_REFERENCE",
  );

  if (detail.evidence.length === 0) {
    return (
      <Card>
        <p className="eyebrow">Why this risk</p>
        <h2>Minimal retained evidence</h2>
        <EmptyState
          title="No retained excerpt"
          description="The risk remains canonical, but no safe evidence excerpt is available."
        />
      </Card>
    );
  }

  const originalEvidence = [
    ...source,
    ...(risk.analysis_type === "LICENSE" ? packageMetadata : []),
  ];
  // 내용 없는 칸은 그리지 않는다 — "발췌가 없습니다" 를 칸마다 적으면 빈 안내가
  // 실제 근거보다 자리를 더 차지한다. 특허의 좌우 대조만 예외다: 비교라는 형식
  // 자체가 두 칸을 요구한다.
  const originalColumn =
    originalEvidence.length === 0 && risk.analysis_type !== "PATENT" ? null : (
      <section className="compare-pane">
        <h3>원본 문서</h3>
        {originalEvidence.map((evidence) => (
          <EvidenceBlock key={evidence.id} evidence={evidence} />
        ))}
        {originalEvidence.length === 0 ? (
          <p className="fine-print">원본 쪽 발췌가 남아 있지 않습니다.</p>
        ) : null}
        <p className="compare-pane__link">
          <button type="button" className="text-link" onClick={onOpenOriginal}>
            {openLabel} ↗
          </button>
        </p>
      </section>
    );

  if (risk.analysis_type === "PATENT") {
    return (
      <Card>
        <p className="eyebrow">Why this risk</p>
        <h2>원본 ↔ 근거 대조</h2>
        <div className="compare-grid">
          {originalColumn}
          <section className="compare-pane">
            <h3>근거 문서 (특허)</h3>
            {patent.map((evidence) => (
              <EvidenceBlock key={evidence.id} evidence={evidence} />
            ))}
            {patent.length === 0 ? (
              <p className="fine-print">특허 쪽 발췌가 남아 있지 않습니다.</p>
            ) : null}
            <PatentReferenceLinks evidence={patent} />
          </section>
        </div>
      </Card>
    );
  }

  return (
    <Card>
      <p className="eyebrow">Why this risk</p>
      <h2>원본 · 근거 라이선스 대조</h2>
      <div className="compare-stack">
        {originalColumn}
        {license.length === 0 ? null : (
          <section className="compare-pane">
            <h3>근거 라이선스 전문</h3>
            {/* 전문은 길다 — 스크롤 상자에 가두고 문제가 된 조항만 하이라이트로 짚는다. */}
            <div className="license-text">
              {license.map((evidence) => (
                <EvidenceBlock key={evidence.id} evidence={evidence} />
              ))}
            </div>
          </section>
        )}
        {references.length === 0 ? null : (
          <p className="fine-print">
            참고 근거: {references.map((item) => item.reference).join(" · ")}
          </p>
        )}
      </div>
    </Card>
  );
}

function EvidenceBlock({ evidence }: { evidence: Evidence }) {
  return (
    <article className="evidence-block">
      <div className="card-row">
        <Badge tone="info">{evidence.evidence_type}</Badge>
        <small>Revision {shortRevision(evidence.source_revision)}</small>
      </div>
      <EvidenceExcerpt excerpt={evidence.excerpt} metadata={evidence.metadata_safe} />
      <p className="evidence-block__reference">{evidence.reference}</p>
    </article>
  );
}

/**
 * 근거 특허로 나가는 링크. reference 는 "KIPRIS Plus 출원번호 …" 형식이다.
 * 출원번호를 읽지 못하면 링크를 지어내지 않는다.
 *
 * KIPRIS 신형 검색은 `searchQuery=AN=<출원번호>` 필드 질의를 받는다.
 * 출원번호는 숫자만 남긴다 — 붙임표가 섞이면 AN 질의가 빈다.
 */
function PatentReferenceLinks({ evidence }: { evidence: Evidence[] }) {
  // KIPRIS 검색 화면이 URL 질의를 항상 실행해 주지는 않는다 — 링크로 화면까지
  // 데려다 주되, 번호를 복사해 검색창에 붙여 넣을 수 있게 함께 둔다.
  const [copied, setCopied] = useState<string | null>(null);
  const numbers = [
    ...new Set(
      evidence
        .map((item) => /출원번호\s*([0-9][0-9-]*)/u.exec(item.reference)?.[1])
        .filter((value): value is string => value !== undefined),
    ),
  ];
  if (numbers.length === 0) return null;
  return (
    <p className="compare-pane__link">
      {numbers.map((number) => (
        <span key={number} className="compare-pane__reference">
          <a
            className="text-link"
            href={`https://www.kipris.or.kr/khome/search/searchResult.do?searchQuery=${encodeURIComponent(`AN=${number.replaceAll("-", "")}`)}&tab=patent`}
            target="_blank"
            rel="noreferrer"
          >
            KIPRIS 출원번호 {number} ↗
          </a>
          <button
            type="button"
            className="text-link"
            onClick={() => {
              void navigator.clipboard?.writeText(number.replaceAll("-", ""));
              setCopied(number);
            }}
          >
            {copied === number ? "복사됨" : "번호 복사"}
          </button>
        </span>
      ))}
    </p>
  );
}

function Status({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <span>{label}</span>
      <Badge tone={toneFor(value)}>
        {value.includes("_") ? humanize(value) : value}
      </Badge>
    </div>
  );
}
