import { useEffect, useState } from "react";
import type { FormEvent } from "react";

import {
  ApiClientError,
  grantInventoryMember,
  listInventoryMembers,
  removeInventoryMember,
  updateInventoryMember,
} from "../api";
import type {
  InventoryMembership,
  InventoryMembershipRole,
  InventorySummary,
} from "../types";
import type { NoticeTone } from "../uiTypes";
import { toUserMessage } from "../uiHelpers";
import { ModalDialog } from "./ui/ModalDialog";
import { PanelState } from "./ui/PanelState";

const MEMBERSHIP_ROLES: Array<{ value: InventoryMembershipRole; label: string }> = [
  { value: "viewer", label: "Viewer" },
  { value: "editor", label: "Editor" },
  { value: "owner", label: "Owner" },
];

type MemberAction =
  | "grant"
  | `remove:${string}`
  | `role:${string}`
  | null;

function sortMembers(members: InventoryMembership[]) {
  return [...members].sort((left, right) =>
    left.actor_id.localeCompare(right.actor_id),
  );
}

function upsertMember(
  members: InventoryMembership[],
  nextMember: InventoryMembership,
) {
  const memberExists = members.some(
    (member) => member.actor_id === nextMember.actor_id,
  );
  return sortMembers(
    memberExists
      ? members.map((member) =>
          member.actor_id === nextMember.actor_id ? nextMember : member,
        )
      : [...members, nextMember],
  );
}

function formatRoleLabel(role: InventoryMembershipRole) {
  return MEMBERSHIP_ROLES.find((option) => option.value === role)?.label ?? role;
}

export function InventoryAccessDialog(props: {
  canManageShare: boolean;
  inventory: InventorySummary;
  onClose: () => void;
  onNotice: (message: string, tone?: NoticeTone) => void;
  onPermissionsChanged: (preferredSlug?: string | null) => Promise<boolean>;
}) {
  const [actorId, setActorId] = useState("");
  const [busyAction, setBusyAction] = useState<MemberAction>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [members, setMembers] = useState<InventoryMembership[]>([]);
  const [membersError, setMembersError] = useState<string | null>(null);
  const [membersStatus, setMembersStatus] =
    useState<"loading" | "ready" | "error">("loading");
  const [role, setRole] = useState<InventoryMembershipRole>("viewer");

  async function refreshPermissionsAfterForbidden(error: unknown) {
    if (!(error instanceof ApiClientError) || error.status !== 403) {
      return;
    }

    try {
      await props.onPermissionsChanged(props.inventory.slug);
    } catch {
      // Keep the original permission error as the user-facing message.
    }
  }

  useEffect(() => {
    let canceled = false;

    async function loadMembers() {
      if (!props.canManageShare) {
        setMembersStatus("ready");
        return;
      }

      setMembersStatus("loading");
      setMembersError(null);
      try {
        const response = await listInventoryMembers(props.inventory.slug);
        if (canceled) {
          return;
        }
        setMembers(sortMembers(response));
        setMembersStatus("ready");
      } catch (error) {
        await refreshPermissionsAfterForbidden(error);
        if (canceled) {
          return;
        }
        const message = toUserMessage(error, "Could not load collection members.");
        setMembersError(message);
        props.onNotice(message, "error");
        setMembersStatus("error");
      }
    }

    void loadMembers();

    return () => {
      canceled = true;
    };
  }, [props.canManageShare, props.inventory.slug]);

  async function handleGrantSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!props.canManageShare) {
      return;
    }

    const nextActorId = actorId.trim();
    if (!nextActorId) {
      setFormError("Enter a user email or actor ID before granting access.");
      return;
    }

    setBusyAction("grant");
    setFormError(null);
    try {
      const response = await grantInventoryMember(props.inventory.slug, {
        actor_id: nextActorId,
        role,
      });
      setMembers((currentMembers) => upsertMember(currentMembers, response));
      setActorId("");
      setRole("viewer");
      props.onNotice(
        `Granted ${formatRoleLabel(response.role)} access to ${response.actor_id}.`,
        "success",
      );
      await props.onPermissionsChanged(props.inventory.slug);
    } catch (error) {
      await refreshPermissionsAfterForbidden(error);
      const message = toUserMessage(error, "Could not grant collection access.");
      setFormError(message);
      props.onNotice(message, "error");
    } finally {
      setBusyAction(null);
    }
  }

  async function handleRoleChange(
    member: InventoryMembership,
    nextRole: InventoryMembershipRole,
  ) {
    if (!props.canManageShare || nextRole === member.role) {
      return;
    }

    const action: MemberAction = `role:${member.actor_id}`;
    setBusyAction(action);
    setFormError(null);
    try {
      const response = await updateInventoryMember(
        props.inventory.slug,
        member.actor_id,
        { role: nextRole },
      );
      setMembers((currentMembers) => upsertMember(currentMembers, response));
      props.onNotice(
        `Updated ${response.actor_id} to ${formatRoleLabel(response.role)}.`,
        "success",
      );
      await props.onPermissionsChanged(props.inventory.slug);
    } catch (error) {
      await refreshPermissionsAfterForbidden(error);
      props.onNotice(
        toUserMessage(error, "Could not update collection access."),
        "error",
      );
    } finally {
      setBusyAction(null);
    }
  }

  async function handleRemove(member: InventoryMembership) {
    if (!props.canManageShare) {
      return;
    }

    const confirmed = window.confirm(
      `Remove ${member.actor_id} from ${props.inventory.display_name}?`,
    );
    if (!confirmed) {
      return;
    }

    const action: MemberAction = `remove:${member.actor_id}`;
    setBusyAction(action);
    setFormError(null);
    try {
      const response = await removeInventoryMember(
        props.inventory.slug,
        member.actor_id,
      );
      setMembers((currentMembers) =>
        currentMembers.filter(
          (currentMember) => currentMember.actor_id !== response.actor_id,
        ),
      );
      props.onNotice(
        `Removed ${response.actor_id} from ${props.inventory.display_name}.`,
        "success",
      );
      await props.onPermissionsChanged(props.inventory.slug);
    } catch (error) {
      await refreshPermissionsAfterForbidden(error);
      props.onNotice(
        toUserMessage(error, "Could not remove collection access."),
        "error",
      );
    } finally {
      setBusyAction(null);
    }
  }

  const formDisabled = busyAction !== null || !props.canManageShare;

  return (
    <ModalDialog
      isOpen
      kicker="Collection Access"
      onClose={props.onClose}
      size="wide"
      subtitle={`Manage who can use ${props.inventory.display_name}.`}
      title="Manage access"
    >
      <section className="form-section form-section-muted access-dialog-section">
        <div className="form-section-header">
          <strong>Members</strong>
          <span>Owner access can grant, change, or remove collection members.</span>
        </div>

        {!props.canManageShare ? (
          <PanelState
            body="Owner access is required to manage collection members."
            eyebrow="Access"
            title="Management unavailable"
          />
        ) : membersStatus === "loading" ? (
          <PanelState
            body="Loading current collection members."
            eyebrow="Access"
            title="Loading members"
            variant="loading"
          />
        ) : membersStatus === "error" ? (
          <PanelState
            body={membersError || "Could not load collection members."}
            eyebrow="Access"
            title="Members unavailable"
            variant="error"
          />
        ) : members.length ? (
          <div aria-label="Current members" className="access-member-list">
            {members.map((member) => {
              const roleBusy = busyAction === `role:${member.actor_id}`;
              const removeBusy = busyAction === `remove:${member.actor_id}`;

              return (
                <article className="access-member-row" key={member.actor_id}>
                  <div className="access-member-copy">
                    <strong>{member.actor_id}</strong>
                    <span>{formatRoleLabel(member.role)} access</span>
                  </div>

                  <label className="field access-member-role-field">
                    <span>Role for {member.actor_id}</span>
                    <select
                      className="text-input"
                      disabled={formDisabled || roleBusy || removeBusy}
                      onChange={(event) =>
                        void handleRoleChange(
                          member,
                          event.target.value as InventoryMembershipRole,
                        )
                      }
                      value={member.role}
                    >
                      {MEMBERSHIP_ROLES.map((option) => (
                        <option key={option.value} value={option.value}>
                          {option.label}
                        </option>
                      ))}
                    </select>
                  </label>

                  <button
                    className="danger-button"
                    disabled={formDisabled || roleBusy || removeBusy}
                    onClick={() => void handleRemove(member)}
                    type="button"
                  >
                    {removeBusy ? "Removing..." : "Remove"}
                  </button>
                </article>
              );
            })}
          </div>
        ) : (
          <p className="panel-hint">No explicit members are assigned yet.</p>
        )}
      </section>

      {props.canManageShare ? (
        <form className="form-section access-grant-form" onSubmit={handleGrantSubmit}>
          <div className="form-section-header">
            <strong>Grant access</strong>
            <span>Use the authenticated user email or actor ID from the proxy.</span>
          </div>

          <div className="access-grant-grid">
            <label className="field">
              <span>User email or actor ID</span>
              <input
                className="text-input"
                data-autofocus
                disabled={formDisabled}
                onChange={(event) => {
                  setActorId(event.target.value);
                  if (formError) {
                    setFormError(null);
                  }
                }}
                placeholder="viewer@example.com"
                value={actorId}
              />
            </label>

            <label className="field">
              <span>Role</span>
              <select
                className="text-input"
                disabled={formDisabled}
                onChange={(event) =>
                  setRole(event.target.value as InventoryMembershipRole)
                }
                value={role}
              >
                {MEMBERSHIP_ROLES.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
          </div>

          {formError ? <p className="field-hint field-hint-error">{formError}</p> : null}

          <div className="table-bulk-pane-actions">
            <button className="primary-button" disabled={formDisabled} type="submit">
              {busyAction === "grant" ? "Granting..." : "Grant access"}
            </button>
          </div>
        </form>
      ) : null}
    </ModalDialog>
  );
}
