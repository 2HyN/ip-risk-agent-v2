import { useEffect, useState, type FormEvent } from "react";
import { useSession } from "../auth/session";
import { formatBytes, formatDate, humanize } from "../shared/format";
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
  toneFor,
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
      <section className="section">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Connected sources</p>
            <h2>Authorized collection scope</h2>
          </div>
        </div>
        {access.data.connected_sources.length === 0 ? (
          <EmptyState
            title="No connected sources"
            description="A Source Manager can connect a provider through the Source Plane."
          />
        ) : (
          <div className="card-grid">
            {access.data.connected_sources.map((source) => (
              <Card key={source.mount_id}>
                <div className="card-row">
                  <div>
                    <h3>{source.alias}</h3>
                    <p>
                      {source.source_type === null
                        ? "Unknown provider"
                        : humanize(source.source_type)}
                    </p>
                  </div>
                  <Badge tone={toneFor(source.status)}>
                    {humanize(source.status)}
                  </Badge>
                </div>
                <dl className="compact-dl">
                  <div>
                    <dt>Provider account</dt>
                    <dd>{source.provider_account_label ?? "Not disclosed"}</dd>
                  </div>
                  <div>
                    <dt>Mounted by</dt>
                    <dd>{source.mounted_by_user_id}</dd>
                  </div>
                  <div>
                    <dt>Tracking scope</dt>
                    <dd>
                      {Object.keys(source.tracking_scope_summary).length === 0
                        ? "Provider-defined scope"
                        : JSON.stringify(source.tracking_scope_summary)}
                    </dd>
                  </div>
                </dl>
              </Card>
            ))}
          </div>
        )}
      </section>
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
              hint={`${settings.data.rule_count} active rules · applied before analysis`}
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
                        <small>Revision {event.revision}</small>
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
