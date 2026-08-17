import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useSession } from "../auth/session";
import { formatDate } from "../shared/format";
import { useResource } from "../shared/hooks/use-resource";
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
  const { api, user } = useSession();
  const navigate = useNavigate();
  const resource = useResource(() => api.workspaces(), [api]);
  const invitations = useResource(() => api.invitations(), [api]);
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
        eyebrow={`Welcome, ${user?.display_name ?? "there"}`}
        title="Risk Workspaces"
        description="Each workspace is an independent collaboration, security, and risk boundary."
      />
      {mutationError === null ? null : <ErrorState error={mutationError} />}
      {invitations.data !== null && invitations.data.items.length > 0 ? (
        <section className="section">
          <div className="section-heading">
            <div>
              <p className="eyebrow">Pending access</p>
              <h2>Workspace invitations</h2>
            </div>
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
                <p className="muted">
                  Expires {formatDate(invitation.expires_at)}
                </p>
              <Button
                disabled={!invitation.acceptance_available}
                onClick={() => {
                  void accept(invitation.id);
                }}
              >
                {invitation.acceptance_available ? "Accept invitation" : "Invitation expired"}
              </Button>
              </Card>
            ))}
          </div>
        </section>
      ) : null}
      <div className="workspace-grid">
        <section>
          <div className="section-heading">
            <div>
              <p className="eyebrow">Your portfolio</p>
              <h2>Available workspaces</h2>
            </div>
          </div>
          {resource.loading ? (
            <LoadingState label="Loading workspaces" />
          ) : resource.error !== null ? (
            <ErrorState error={resource.error} retry={resource.reload} />
          ) : resource.data?.items.length === 0 ? (
            <EmptyState
              title="No workspace yet"
              description="Create the first workspace to start organizing source and risk activity."
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
                      <Badge tone={toneFor(workspace.status)}>
                        {workspace.status}
                      </Badge>
                    </span>
                    <span>{workspace.description ?? "No description"}</span>
                    <small>Updated {formatDate(workspace.updated_at)}</small>
                  </span>
                  <span aria-hidden="true">→</span>
                </button>
              ))}
            </div>
          )}
        </section>
        <Card className="create-card">
          <p className="eyebrow">New boundary</p>
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
        </Card>
      </div>
    </main>
  );
}
