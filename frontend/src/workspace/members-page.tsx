import { useState, type FormEvent } from "react";
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
  Select,
  toneFor,
} from "../shared/ui";
import type { Role } from "../shared/api/types";
import { useWorkspace } from "./workspace-context";

const assignableRoles: Role[] = ["SOURCE_MANAGER", "RISK_REVIEWER", "VIEWER"];

export function MembersPage() {
  const { api, user } = useSession();
  const { workspace, canManageMembers } = useWorkspace();
  const resource = usePagedResource(
    (cursor) => api.members(workspace.id, cursor),
    [api, workspace.id],
  );
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("VIEWER");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  async function invite(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.invite(workspace.id, { email, role });
      setEmail("");
      resource.reload();
    } catch (reason) {
      setError(
        reason instanceof Error ? reason : new Error("Invitation failed"),
      );
    } finally {
      setBusy(false);
    }
  }

  async function update(userId: string, nextRole: Role) {
    setError(null);
    try {
      await api.updateMember(workspace.id, userId, nextRole);
      resource.reload();
    } catch (reason) {
      setError(
        reason instanceof Error ? reason : new Error("Role update failed"),
      );
    }
  }

  async function remove(userId: string) {
    if (
      !window.confirm(
        "Remove this member? Their source mounts and risk history will be preserved.",
      )
    )
      return;
    setError(null);
    try {
      await api.removeMember(workspace.id, userId);
      resource.reload();
    } catch (reason) {
      setError(
        reason instanceof Error ? reason : new Error("Member removal failed"),
      );
    }
  }

  return (
    <div className="content">
      <PageHeader
        eyebrow="Workspace administration"
        title="Members & roles"
        description="Application permissions do not grant raw-source access. Provider authority is always checked separately."
      />
      {error === null ? null : <ErrorState error={error} />}
      {canManageMembers ? (
        <Card className="inline-form-card">
          <form
            className="inline-form"
            onSubmit={(event) => {
              void invite(event);
            }}
          >
            <Field label="Verified email">
              <Input
                type="email"
                required
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="colleague@example.com"
              />
            </Field>
            <Field label="Role">
              <Select
                value={role}
                onChange={(event) => setRole(event.target.value as Role)}
              >
                {assignableRoles.map((item) => (
                  <option value={item} key={item}>
                    {humanize(item)}
                  </option>
                ))}
              </Select>
            </Field>
            <Button disabled={busy}>
              {busy ? "Inviting…" : "Invite member"}
            </Button>
          </form>
        </Card>
      ) : null}
      {resource.loading ? (
        <LoadingState label="Loading members" />
      ) : resource.error !== null ? (
        <ErrorState error={resource.error} retry={resource.reload} />
      ) : resource.data?.items.length === 0 ? (
        <EmptyState
          title="No active members"
          description="Invite a collaborator to this workspace."
        />
      ) : (
        <Card className="table-card">
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Member</th>
                  <th>Role</th>
                  <th>Status</th>
                  <th>Joined</th>
                  {canManageMembers ? (
                    <th>
                      <span className="sr-only">Actions</span>
                    </th>
                  ) : null}
                </tr>
              </thead>
              <tbody>
                {resource.data?.items.map((member) => (
                  <tr key={member.id}>
                    <td>
                      <strong>
                        {member.user_id === user?.id
                          ? `${user.display_name} (you)`
                          : member.user_display_name ??
                            member.user_email ??
                            "알 수 없는 사용자"}
                      </strong>
                      {member.user_email === null ||
                      member.user_email === undefined ? null : (
                        <small>{member.user_email}</small>
                      )}
                      <small>
                        {member.user_id === workspace.owner_user_id
                          ? "Workspace owner"
                          : `Invited by ${member.invited_by_email ?? "알 수 없음"}`}
                      </small>
                    </td>
                    <td>
                      {canManageMembers && member.role !== "OWNER" ? (
                        <Select
                          aria-label={`Role for ${member.user_id}`}
                          value={member.role}
                          onChange={(event) => {
                            void update(
                              member.user_id,
                              event.target.value as Role,
                            );
                          }}
                        >
                          {assignableRoles.map((item) => (
                            <option key={item} value={item}>
                              {humanize(item)}
                            </option>
                          ))}
                        </Select>
                      ) : (
                        humanize(member.role)
                      )}
                    </td>
                    <td>
                      <Badge tone={toneFor(member.status)}>
                        {member.status}
                      </Badge>
                    </td>
                    <td>{formatDate(member.created_at)}</td>
                    {canManageMembers ? (
                      <td>
                        {member.role === "OWNER" ? null : (
                          <Button
                            variant="danger"
                            onClick={() => {
                              void remove(member.user_id);
                            }}
                          >
                            Remove
                          </Button>
                        )}
                      </td>
                    ) : null}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
      {resource.data?.next_cursor === null || resource.data === null ? null : (
        <div className="pagination-actions">
          <Button
            variant="secondary"
            disabled={resource.loadingMore}
            onClick={resource.loadMore}
          >
            {resource.loadingMore ? "Loading…" : "Load more members"}
          </Button>
        </div>
      )}
    </div>
  );
}
