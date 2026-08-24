import { useEffect, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useSession } from "../auth/session";
import { useResource } from "../shared/hooks/use-resource";
import {
  Button,
  Card,
  ErrorState,
  Field,
  LoadingState,
  PageHeader,
  Textarea,
} from "../shared/ui";
import { useWorkspace } from "../workspace/workspace-context";

export function SecurityPage() {
  const { api } = useSession();
  const { workspace, role, canManageSecurity } = useWorkspace();
  const navigate = useNavigate();
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<Error | null>(null);

  async function deleteWorkspace(): Promise<void> {
    const confirmed = window.confirm(
      `"${workspace.name}" workspace를 삭제할까요?\n` +
        "마운트, Risk, 근거, 이력이 모두 지워지며 되돌릴 수 없습니다.",
    );
    if (!confirmed) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      await api.deleteWorkspace(workspace.id);
      navigate("/");
    } catch (reason) {
      setDeleteError(
        reason instanceof Error ? reason : new Error("Workspace를 삭제하지 못했습니다."),
      );
      setDeleting(false);
    }
  }
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
  return (
    <div className="content">
      <PageHeader
        eyebrow="Transparency & control"
        title="Security & data access"
        description="보호 정책과 보존 원칙을 관리합니다. 실제 원문 접근 기록은 Activity & audit의 Source access 탭에 있습니다."
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
      {/* "Actual reads recorded" 섹션은 뺐다 — 같은 기록이 Activity & audit 의
          Source access 탭에 있고, 여기서는 id 표라 사람이 읽지 못했다. */}
      {role === "OWNER" ? (
        <Card className="danger-zone">
          <p className="eyebrow">Danger zone</p>
          <h2>Workspace 삭제</h2>
          <p>
            이 workspace의 마운트, Risk, 근거, 이력이 모두 지워집니다. 되돌릴 수
            없습니다.
          </p>
          {deleteError === null ? null : <ErrorState error={deleteError} />}
          <Button
            variant="danger"
            disabled={deleting}
            onClick={() => void deleteWorkspace()}
          >
            {deleting ? "Deleting…" : "Delete workspace"}
          </Button>
        </Card>
      ) : null}
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
