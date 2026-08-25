import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useSession } from "../auth/session";
import { formatDate, humanize } from "../shared/format";
import { usePagedResource } from "../shared/hooks/use-paged-resource";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  Field,
  Input,
  LoadingState,
  PageHeader,
  Textarea,
  toneFor,
} from "../shared/ui";

export function WorkspaceListPage() {
  const { api } = useSession();
  const navigate = useNavigate();
  const resource = usePagedResource((cursor) => api.workspaces(cursor), [api]);
  const invitations = usePagedResource((cursor) => api.invitations(cursor), [api]);
  const [createOpen, setCreateOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [mutationError, setMutationError] = useState<Error | null>(null);

  async function create(event: FormEvent) {
    event.preventDefault();
    setCreating(true);
    setMutationError(null);
    try {
      const workspace = await api.createWorkspace({
        name,
        description: description.trim() === "" ? null : description,
      });
      navigate(`/w/${workspace.id}`);
    } catch (reason) {
      setMutationError(
        reason instanceof Error
          ? reason
          : new Error("Workspace could not be created"),
      );
    } finally {
      setCreating(false);
    }
  }

  async function accept(id: string) {
    setMutationError(null);
    try {
      const result = await api.acceptInvitation(id);
      navigate(`/w/${result.workspace.id}`);
    } catch (reason) {
      setMutationError(
        reason instanceof Error
          ? reason
          : new Error("Invitation could not be accepted"),
      );
    }
  }

  return (
    <main className="content content--wide">
      <PageHeader
        title="Risk Workspaces"
        description="Each workspace is an independent collaboration, security, and risk boundary."
        actions={
          // Add source · Reviewer decision 과 같은 결 — 폼은 상시 카드가 아니라
          // 버튼이 여는 작은 창이다.
          <Button onClick={() => setCreateOpen(true)}>Create workspace</Button>
        }
      />
      {mutationError === null ? null : <ErrorState error={mutationError} />}
      {invitations.data !== null && invitations.data.items.length > 0 ? (
        <section className="section">
          <div className="section-heading">
            <h2>Workspace invitations</h2>
          </div>
          <div className="card-grid">
            {invitations.data.items.map((invitation) => (
              <Card key={invitation.id}>
                <div className="card-row">
                  <div>
                    <h3>{invitation.workspace_name}</h3>
                    <p>
                      Invited as{" "}
                      {invitation.role.replaceAll("_", " ").toLowerCase()}
                    </p>
                  </div>
                  <Badge tone="info">{invitation.role}</Badge>
                </div>
                {invitation.invited_by_email === null ||
                invitation.invited_by_email === undefined ? null : (
                  <p className="muted">Invited by {invitation.invited_by_email}</p>
                )}
                {/* 수락 기한이다. 기한 없는 초대에 "Expires —" 를 띄우면
                    만료됐다는 말처럼 읽힌다. */}
                <p className="muted">
                  {invitation.expires_at === null
                    ? "만료 기한 없음"
                    : `수락 기한 ${formatDate(invitation.expires_at)}`}
                </p>
                <Button
                  disabled={!invitation.acceptance_available}
                  onClick={() => {
                    void accept(invitation.id);
                  }}
                >
                  {invitation.acceptance_available
                    ? "Accept invitation"
                    : "Invitation expired"}
                </Button>
              </Card>
            ))}
          </div>
          {invitations.data.next_cursor === null ? null : (
            <div className="pagination-actions">
              <Button
                variant="secondary"
                disabled={invitations.loadingMore}
                onClick={invitations.loadMore}
              >
                {invitations.loadingMore ? "Loading…" : "Load more invitations"}
              </Button>
            </div>
          )}
        </section>
      ) : null}
      <section>
        <div className="section-heading">
          <h2>Available workspaces</h2>
        </div>
        {resource.loading ? (
          <LoadingState label="Loading workspaces" />
        ) : resource.error !== null ? (
          <ErrorState error={resource.error} retry={resource.reload} />
        ) : resource.data?.items.length === 0 ? (
          <EmptyState
            title="No workspace yet"
            description="Create the first workspace to start organizing source and risk activity."
            action={
              <Button onClick={() => setCreateOpen(true)}>Create workspace</Button>
            }
          />
        ) : (
          <div className="workspace-list">
            {resource.data?.items.map((workspace) => (
              <button
                className="workspace-card"
                key={workspace.id}
                onClick={() => navigate(`/w/${workspace.id}`)}
              >
                <span className="workspace-card__icon" aria-hidden="true">
                  {workspace.name.slice(0, 2).toUpperCase()}
                </span>
                <span className="workspace-card__body">
                  <span className="workspace-card__top">
                    <strong>{workspace.name}</strong>
                    <span className="workspace-card__badges">
                      {/* 내가 이 workspace 에서 무엇을 할 수 있는지 — 목록에서 바로 본다. */}
                      {workspace.my_role === null ||
                      workspace.my_role === undefined ? null : (
                        <Badge tone="info">{humanize(workspace.my_role)}</Badge>
                      )}
                      <Badge tone={toneFor(workspace.status)}>
                        {workspace.status}
                      </Badge>
                    </span>
                  </span>
                  <span>{workspace.description ?? "No description"}</span>
                  <small>Updated {formatDate(workspace.updated_at)}</small>
                </span>
                <span aria-hidden="true">→</span>
              </button>
            ))}
          </div>
        )}
        {resource.data?.next_cursor === null || resource.data === null ? null : (
          <div className="pagination-actions">
            <Button
              variant="secondary"
              disabled={resource.loadingMore}
              onClick={resource.loadMore}
            >
              {resource.loadingMore ? "Loading…" : "Load more workspaces"}
            </Button>
          </div>
        )}
      </section>
      {createOpen ? (
        <div
          className="modal-backdrop"
          role="presentation"
          onClick={() => setCreateOpen(false)}
        >
          <div
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-label="Create workspace"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="modal__head">
              <Button
                type="button"
                variant="ghost"
                onClick={() => setCreateOpen(false)}
              >
                닫기 ✕
              </Button>
            </div>
            <h2>Create workspace</h2>
            <p>Start with isolated membership, policy, and risk history.</p>
            <form
              onSubmit={(event) => {
                void create(event);
              }}
            >
              <Field label="Workspace name">
                <Input
                  required
                  maxLength={200}
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  placeholder="Product counsel"
                />
              </Field>
              <Field
                label="Description"
                hint="Optional · visible to workspace members"
              >
                <Textarea
                  maxLength={2000}
                  rows={4}
                  value={description}
                  onChange={(event) => setDescription(event.target.value)}
                  placeholder="What this workspace protects"
                />
              </Field>
              <Button disabled={creating || name.trim() === ""}>
                {creating ? "Creating…" : "Create workspace"}
              </Button>
            </form>
          </div>
        </div>
      ) : null}
    </main>
  );
}
