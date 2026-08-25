import { useEffect, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useSession } from "../auth/session";
import { useResource } from "../shared/hooks/use-resource";
import type { LicenseProfile } from "../shared/api/types";
import {
  Button,
  Card,
  ErrorState,
  Field,
  LoadingState,
  PageHeader,
  Select,
  Textarea,
} from "../shared/ui";
import { useWorkspace } from "../workspace/workspace-context";

const DISTRIBUTION_FORMS: [LicenseProfile["distribution_form"], string][] = [
  ["SAAS", "SaaS — 네트워크로 서비스 제공"],
  ["BINARY", "바이너리 배포 — 실행 파일을 전달"],
  ["INTERNAL_ONLY", "사내 전용 — 외부 배포 없음"],
  ["LIBRARY_REDISTRIBUTION", "라이브러리 재배포"],
  ["EMBEDDED", "임베디드 — 기기에 탑재"],
];
const MODIFICATIONS: [LicenseProfile["modification"], string][] = [
  ["UNMODIFIED", "수정 없이 사용"],
  ["MODIFIED", "코드를 수정해 사용"],
];
const LINKINGS: [LicenseProfile["linking"], string][] = [
  ["DYNAMIC", "동적 링크"],
  ["STATIC", "정적 링크"],
  ["NOT_APPLICABLE", "해당 없음"],
];

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
        title="Security & data access"
        description="보호 정책과 보존 원칙을 관리합니다. 실제 원문 접근 기록은 Activity & audit의 Source access 탭에 있습니다."
      />
      {error === null ? null : <ErrorState error={error} />}
      {/* "Connected sources / Authorized collection scope" 섹션은 뺐다 —
          연결과 범위는 Files 화면이 보여 주는 것이고, 여기 남겨 두면 같은 사실이
          두 화면에서 다르게 늙는다. */}
      <LicenseProfileCard
        profile={settings.data.license_profile ?? null}
        canManage={canManageSecurity}
        onSaved={() => {
          settings.reload();
        }}
      />
      <div className="security-grid">
        <Card>
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
          <h2>데이터 처리 원칙</h2>
          <div className="assurance-list">
            <Assurance
              label="원본 소스"
              value="화면에 표시되지 않고, 분석 시에만 읽으며 저장하지 않습니다"
              safe={!access.data.raw_source_persisted}
            />
            <Assurance
              label="분석 산출물"
              value="검토하는 동안만 유지됩니다"
              safe={!access.data.analysis_artifact_persisted}
            />
            <Assurance
              label="판정 근거"
              value="필요한 최소 발췌만 보관합니다"
              safe
            />
            <Assurance
              label="외부 특허·라이선스 지식"
              value="참조 전용이며, 내 코드는 전송되지 않습니다"
              safe={access.data.external_rag_reference_only}
            />
            <Assurance
              label="시크릿(API 키 등)"
              value="분석 전에 자동 제거됩니다"
              safe
            />
          </div>
        </Card>
      </div>
      {/* "Actual reads recorded" 섹션은 뺐다 — 같은 기록이 Activity & audit 의
          Source access 탭에 있고, 여기서는 id 표라 사람이 읽지 못했다. */}
      {role === "OWNER" ? (
        <Card className="danger-zone">
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

/**
 * 라이선스 배포 프로파일 — 같은 라이선스가 배포 형태에 따라 다른 의무를 만든다.
 *
 * 이것이 정해지기 전에는 서버가 등급을 짐작하지 않고 라이선스 Risk 를 전부
 * "확인 필요(INDETERMINATE)" 로 둔다. 그래서 기본값을 미리 골라 두지 않는다 —
 * 화면을 지나쳤다고 "SaaS 로 정했다" 가 되면 안 된다. 저장하면 서버가 라이선스
 * 재평가를 이어서 돌린다.
 */
function LicenseProfileCard({
  profile,
  canManage,
  onSaved,
}: {
  profile: LicenseProfile | null;
  canManage: boolean;
  onSaved: () => void;
}) {
  const { api } = useSession();
  const { workspace } = useWorkspace();
  const [distribution, setDistribution] = useState<string>(
    profile?.distribution_form ?? "",
  );
  const [modification, setModification] = useState<string>(
    profile?.modification ?? "",
  );
  const [linking, setLinking] = useState<string>(profile?.linking ?? "");
  const [redistributes, setRedistributes] = useState<string>(
    profile === null ? "" : profile.redistributes ? "yes" : "no",
  );
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const complete =
    distribution !== "" && modification !== "" && linking !== "" && redistributes !== "";

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!complete) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await api.updateLicenseProfile(workspace.id, {
        distribution_form: distribution as LicenseProfile["distribution_form"],
        modification: modification as LicenseProfile["modification"],
        linking: linking as LicenseProfile["linking"],
        redistributes: redistributes === "yes",
      });
      setNotice(
        "저장되었습니다. 라이선스 재평가가 진행 중입니다 — 잠시 후 Review 에서 등급이 갱신됩니다.",
      );
      onSaved();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason
          : new Error("배포 프로파일을 저장하지 못했습니다."),
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="license-profile-card">
      <h2>라이선스 배포 프로파일</h2>
      {profile === null ? (
        <p className="analysis-notice analysis-notice--warning" role="status">
          배포 형태가 아직 설정되지 않아 라이선스 위험이 전부{" "}
          <strong>확인 필요(INDETERMINATE)</strong>로 표시됩니다. 같은 라이선스라도
          배포 형태에 따라 의무가 달라서, 정해지기 전에는 등급을 짐작하지 않습니다.
        </p>
      ) : (
        <p>
          현재 설정을 바꾸면 저장 시 라이선스 위험이 자동으로 다시 평가됩니다.
        </p>
      )}
      {notice === null ? null : (
        <p className="source-success" role="status">
          {notice}
        </p>
      )}
      {error === null ? null : <ErrorState error={error} />}
      <form className="license-profile-form" onSubmit={(event) => void save(event)}>
        <Field label="배포 형태">
          <Select
            value={distribution}
            disabled={!canManage}
            onChange={(event) => setDistribution(event.target.value)}
          >
            <option value="" disabled>
              선택하세요
            </option>
            {DISTRIBUTION_FORMS.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="수정 여부">
          <Select
            value={modification}
            disabled={!canManage}
            onChange={(event) => setModification(event.target.value)}
          >
            <option value="" disabled>
              선택하세요
            </option>
            {MODIFICATIONS.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="링크 방식">
          <Select
            value={linking}
            disabled={!canManage}
            onChange={(event) => setLinking(event.target.value)}
          >
            <option value="" disabled>
              선택하세요
            </option>
            {LINKINGS.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="외부 재배포 여부">
          <Select
            value={redistributes}
            disabled={!canManage}
            onChange={(event) => setRedistributes(event.target.value)}
          >
            <option value="" disabled>
              선택하세요
            </option>
            <option value="yes">재배포함</option>
            <option value="no">재배포하지 않음</option>
          </Select>
        </Field>
        {canManage ? (
          <Button disabled={busy || !complete}>
            {busy ? "Saving…" : "저장하고 재평가"}
          </Button>
        ) : (
          <p className="fine-print">Owner만 이 설정을 바꿀 수 있습니다.</p>
        )}
      </form>
    </Card>
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
