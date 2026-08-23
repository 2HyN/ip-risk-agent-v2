import { useEffect, useState, type FormEvent } from "react";
import { useSession } from "../auth/session";
import { formatBytes, formatDate, humanize, shortRevision } from "../shared/format";
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
  Textarea,
} from "../shared/ui";
import { useWorkspace } from "../workspace/workspace-context";

export function SecurityPage() {
  const { api } = useSession();
  const { workspace, canManageSecurity } = useWorkspace();
  const settings = useResource(
    () => api.security(workspace.id),
    [api, workspace.id],
  );
  const access = useResource(
    () => api.dataAccess(workspace.id),
    [api, workspace.id],
  );
  const [ignoreText, setIgnoreText] = useState("");
  const [error, setError] = useState<Error | null>(null);
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    if (settings.data !== null) setIgnoreText(settings.data.global_ignore_text);
  }, [settings.data]);

  async function save(event: FormEvent) {
    event.preventDefault();
    if (settings.data === null) return;
    setSaving(true);
    setError(null);
    try {
      await api.updateIgnore(workspace.id, {
        expected_policy_version: settings.data.policy_version,
        global_ignore_text: ignoreText,
      });
      settings.reload();
      access.reload();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason
          : new Error("Policy could not be saved"),
      );
    } finally {
      setSaving(false);
    }
  }

  if (settings.loading || access.loading)
    return <LoadingState label="Loading security posture" />;
  if (settings.error !== null)
    return <ErrorState error={settings.error} retry={settings.reload} />;
  if (access.error !== null)
    return <ErrorState error={access.error} retry={access.reload} />;
  if (settings.data === null || access.data === null) return null;
  const mountAliases = new Map(
    access.data.mounts.map((mount) => [mount.id, mount.alias]),
  );
  return (
    <div className="content">
      <PageHeader
        eyebrow="Transparency & control"
        title="Security & data access"
        description="Connected scope, protection policy, retention, and actual source reads are shown separately."
      />
      {error === null ? null : <ErrorState error={error} />}
      {/* "Connected sources / Authorized collection scope" 섹션은 뺐다 —
          연결과 범위는 Files 화면이 보여 주는 것이고, 여기 남겨 두면 같은 사실이
          두 화면에서 다르게 늙는다. */}
      <div className="security-grid">
        <Card>
          <p className="eyebrow">Global protection</p>
          <h2>.ipriskignore</h2>
          <form
            onSubmit={(event) => {
              void save(event);
            }}
          >
            <Field
              label="Deny-only logical path rules"
              hint={`${settings.data.rule_count} active rules · 분석 직전에 적용 · 경로는 마운트 폴더 기준(폴더 이름 제외) · 걸린 파일의 기존 Risk는 '제외됨'으로 닫힙니다`}
            >
              <Textarea
                className="input textarea code-input"
                rows={12}
                spellCheck={false}
                readOnly={!canManageSecurity}
                value={ignoreText}
                onChange={(event) => setIgnoreText(event.target.value)}
                placeholder="/backend/**/.env*"
              />
            </Field>
            {canManageSecurity ? (
              <Button
                disabled={
                  saving || ignoreText === settings.data.global_ignore_text
                }
              >
                {saving ? "Saving…" : "Save policy"}
              </Button>
            ) : (
              <p className="fine-print">
                Only the workspace Owner can change this policy.
              </p>
            )}
          </form>
        </Card>
        <Card>
          <p className="eyebrow">Retention assurances</p>
          <h2>What Control retains</h2>
          <div className="assurance-list">
            <Assurance
              label="Raw source snapshots"
              value={
                access.data.raw_source_persisted
                  ? "Persisted"
                  : "Never persisted"
              }
              safe={!access.data.raw_source_persisted}
            />
            <Assurance
              label="Approved analysis artifacts"
              value={
                access.data.analysis_artifact_persisted
                  ? "Persisted"
                  : "Transient"
              }
              safe={!access.data.analysis_artifact_persisted}
            />
            <Assurance
              label="Evidence retention"
              value={access.data.retention_policy_version}
              safe
            />
            <Assurance
              label="External RAG"
              value={
                access.data.external_rag_reference_only
                  ? "Reference knowledge only"
                  : "Review required"
              }
              safe={access.data.external_rag_reference_only}
            />
            <Assurance
              label="Secret filtering"
              value="Enabled before analysis"
              safe
            />
          </div>
        </Card>
      </div>
      <section className="section">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Recent source access</p>
            <h2>Actual reads recorded</h2>
          </div>
          <Badge tone="neutral">
            {access.data.recent_access.length} recent
          </Badge>
        </div>
        {access.data.recent_access.length === 0 ? (
          <EmptyState
            title="No source reads recorded"
            description="SourceAccessEvents will appear after analysis collection begins."
          />
        ) : (
          <Card className="table-card">
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Mount</th>
                    <th>Artifact</th>
                    <th>Access</th>
                    <th>Bytes</th>
                    <th>Occurred</th>
                  </tr>
                </thead>
                <tbody>
                  {access.data.recent_access.map((event) => (
                    <tr key={event.id}>
                      <td>
                        {mountAliases.get(event.mount_id) ?? event.mount_id}
                      </td>
                      <td>
                        {event.artifact_id}
                        <small>Revision {shortRevision(event.revision)}</small>
                      </td>
                      <td>{humanize(event.access_type)}</td>
                      <td>{formatBytes(event.content_bytes)}</td>
                      <td>{formatDate(event.occurred_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        )}
      </section>
    </div>
  );
}

function Assurance({
  label,
  value,
  safe,
}: {
  label: string;
  value: string;
  safe: boolean;
}) {
  return (
    <div>
      <span
        className={
          safe ? "assurance-icon" : "assurance-icon assurance-icon--warn"
        }
        aria-hidden="true"
      >
        {safe ? "✓" : "!"}
      </span>
      <div>
        <strong>{label}</strong>
        <span>{value}</span>
      </div>
    </div>
  );
}
