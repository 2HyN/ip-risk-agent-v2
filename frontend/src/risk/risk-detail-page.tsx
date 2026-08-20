import { useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { useSession } from "../auth/session";
import { formatDate, humanize } from "../shared/format";
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
import type { Risk } from "../shared/api/types";
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
  const [disposition, setDisposition] =
    useState<Risk["review_disposition"]>("UNREVIEWED");
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [mutationError, setMutationError] = useState<Error | null>(null);

  async function review(event: FormEvent) {
    event.preventDefault();
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
    <div className="content">
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
              onClick={() => {
                void integration.openOriginal?.({
                  workspaceId: workspace.id,
                  artifactId: detail.open_original.artifact_id,
                  action: detail.open_original.action,
                  sourceType: risk.source_type,
                });
              }}
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
          <Card>
            <p className="eyebrow">Why this risk</p>
            <h2>Minimal retained evidence</h2>
            {detail.evidence.length === 0 ? (
              <EmptyState
                title="No retained excerpt"
                description="The risk remains canonical, but no safe evidence excerpt is available."
              />
            ) : (
              <div className="evidence-list">
                {detail.evidence.map((evidence) => (
                  <article key={evidence.id}>
                    <div className="card-row">
                      <Badge tone="info">{evidence.evidence_type}</Badge>
                      <small>Revision {evidence.source_revision}</small>
                    </div>
                    <blockquote>{evidence.excerpt}</blockquote>
                    <p>
                      <strong>Reference:</strong> {evidence.reference}
                    </p>
                  </article>
                ))}
              </div>
            )}
            <div className="source-assurance">
              <strong>No raw source preview</strong>
              <span>
                Use “{openLabel}” to continue through provider or owning-device
                authorization.
              </span>
            </div>
          </Card>
          <Card>
            <p className="eyebrow">Analysis metadata</p>
            <dl className="metadata-list">
              <div>
                <dt>Analysis job</dt>
                <dd>{risk.latest_analysis_job_id}</dd>
              </div>
              <div>
                <dt>Evidence revision</dt>
                <dd>{risk.latest_evidence_revision ?? "Not retained"}</dd>
              </div>
              <div>
                <dt>Artifact path</dt>
                <dd>{risk.artifact_logical_path ?? "Not available"}</dd>
              </div>
              <div>
                <dt>Source mount</dt>
                <dd>{risk.mount_alias ?? "Not available"}</dd>
              </div>
            </dl>
          </Card>
        </div>
        <aside>
          {canReview ? (
            <Card className="review-card">
              <p className="eyebrow">Reviewer decision</p>
              <h2>Record disposition</h2>
              <form
                onSubmit={(event) => {
                  void review(event);
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
                    <option value="UNREVIEWED">Unreviewed</option>
                    <option value="MONITORING">Monitoring</option>
                    <option value="ACCEPTED_RISK">Accepted risk</option>
                    <option value="EXCLUDED">Excluded</option>
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
