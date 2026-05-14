import { useEffect, useState } from "react";
import type { FormEvent } from "react";

import {
  ApiClientError,
  createInventoryShareLink,
  getInventoryShareLinkStatus,
  grantInventoryMember,
  listInventoryMembers,
  removeInventoryMember,
  revokeInventoryShareLink,
  rotateInventoryShareLink,
  updateInventoryMember,
} from "../api";
import type {
  InventoryMembership,
  InventoryMembershipRole,
  InventoryShareLinkStatusResponse,
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
type ShareLinkAction = "create" | "rotate" | "revoke" | null;

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

function formatShareLinkTimestamp(value: string | null) {
  if (!value) {
    return "Not recorded";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function getPublicShareUrl(publicPath: string) {
  return new URL(publicPath, window.location.origin).toString();
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
  const [shareLink, setShareLink] =
    useState<InventoryShareLinkStatusResponse | null>(null);
  const [shareLinkBusy, setShareLinkBusy] = useState<ShareLinkAction>(null);
  const [shareLinkError, setShareLinkError] = useState<string | null>(null);
  const [shareLinkStatus, setShareLinkStatus] =
    useState<"loading" | "ready" | "error">("loading");

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

  useEffect(() => {
    let canceled = false;

    async function loadShareLinkStatus() {
      if (!props.canManageShare) {
        setShareLinkStatus("ready");
        return;
      }

      setShareLinkStatus("loading");
      setShareLinkError(null);
      try {
        const response = await getInventoryShareLinkStatus(props.inventory.slug);
        if (canceled) {
          return;
        }
        setShareLink(response);
        setShareLinkStatus("ready");
      } catch (error) {
        await refreshPermissionsAfterForbidden(error);
        if (canceled) {
          return;
        }
        const message = toUserMessage(
          error,
          "Could not load public share link status.",
        );
        setShareLinkError(message);
        props.onNotice(message, "error");
        setShareLinkStatus("error");
      }
    }

    void loadShareLinkStatus();

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

  async function handleCreateShareLink() {
    if (!props.canManageShare) {
      return;
    }

    setShareLinkBusy("create");
    setShareLinkError(null);
    try {
      const response = await createInventoryShareLink(props.inventory.slug);
      setShareLink(response);
      props.onNotice("Created a public read-only share link.", "success");
      await props.onPermissionsChanged(props.inventory.slug);
    } catch (error) {
      await refreshPermissionsAfterForbidden(error);
      const message = toUserMessage(error, "Could not create the public share link.");
      setShareLinkError(message);
      props.onNotice(message, "error");
    } finally {
      setShareLinkBusy(null);
    }
  }

  async function handleRotateShareLink() {
    if (!props.canManageShare) {
      return;
    }

    const confirmed = window.confirm(
      `Rotate the public share link for ${props.inventory.display_name}? Existing public links will stop working.`,
    );
    if (!confirmed) {
      return;
    }

    setShareLinkBusy("rotate");
    setShareLinkError(null);
    try {
      const response = await rotateInventoryShareLink(props.inventory.slug);
      setShareLink(response);
      props.onNotice("Rotated the public share link.", "success");
      await props.onPermissionsChanged(props.inventory.slug);
    } catch (error) {
      await refreshPermissionsAfterForbidden(error);
      const message = toUserMessage(error, "Could not rotate the public share link.");
      setShareLinkError(message);
      props.onNotice(message, "error");
    } finally {
      setShareLinkBusy(null);
    }
  }

  async function handleRevokeShareLink() {
    if (!props.canManageShare) {
      return;
    }

    const confirmed = window.confirm(
      `Revoke the public share link for ${props.inventory.display_name}? Public read-only access will stop immediately.`,
    );
    if (!confirmed) {
      return;
    }

    setShareLinkBusy("revoke");
    setShareLinkError(null);
    try {
      const response = await revokeInventoryShareLink(props.inventory.slug);
      setShareLink(response);
      props.onNotice("Revoked the public share link.", "success");
      await props.onPermissionsChanged(props.inventory.slug);
    } catch (error) {
      await refreshPermissionsAfterForbidden(error);
      const message = toUserMessage(error, "Could not revoke the public share link.");
      setShareLinkError(message);
      props.onNotice(message, "error");
    } finally {
      setShareLinkBusy(null);
    }
  }

  async function handleCopyShareLink(publicPath: string) {
    const shareUrl = getPublicShareUrl(publicPath);
    if (!navigator.clipboard?.writeText) {
      props.onNotice(
        "Copy is not available in this browser. Select the link text instead.",
        "error",
      );
      return;
    }

    try {
      await navigator.clipboard.writeText(shareUrl);
      props.onNotice("Copied the public share link.", "success");
    } catch {
      props.onNotice("Could not copy the public share link.", "error");
    }
  }

  const formDisabled = busyAction !== null || !props.canManageShare;
  const shareLinkControlsDisabled = shareLinkBusy !== null || !props.canManageShare;
  const activeShareLink = Boolean(shareLink?.active && shareLink.public_path);
  const publicShareUrl =
    shareLink?.active && shareLink.public_path
      ? getPublicShareUrl(shareLink.public_path)
      : null;

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
        <section className="form-section form-section-muted access-dialog-section">
          <div className="form-section-header">
            <strong>Public link</strong>
            <span>Public links are read-only and can be rotated or revoked by owners.</span>
          </div>

          {shareLinkStatus === "loading" ? (
            <PanelState
              body="Checking whether this collection already has a public link."
              eyebrow="Public link"
              title="Loading share link"
              variant="loading"
            />
          ) : shareLinkStatus === "error" ? (
            <PanelState
              body={shareLinkError || "Could not load public share link status."}
              eyebrow="Public link"
              title="Share link unavailable"
              variant="error"
            />
          ) : activeShareLink ? (
            <div className="access-share-link-card">
              <div className="access-share-link-copy">
                <span>Public URL</span>
                <code>{publicShareUrl}</code>
              </div>
              <div className="mini-grid">
                <div className="meta-line">
                  <span>Created</span>
                  <strong>
                    {formatShareLinkTimestamp(shareLink?.created_at ?? null)}
                  </strong>
                </div>
                <div className="meta-line">
                  <span>Updated</span>
                  <strong>
                    {formatShareLinkTimestamp(shareLink?.updated_at ?? null)}
                  </strong>
                </div>
              </div>
              {shareLinkError ? (
                <p className="field-hint field-hint-error">{shareLinkError}</p>
              ) : null}
              <div className="table-bulk-pane-actions">
                {shareLink?.public_path ? (
                  <>
                    <button
                      className="secondary-button"
                      disabled={shareLinkControlsDisabled}
                      onClick={() => {
                        if (shareLink.public_path) {
                          void handleCopyShareLink(shareLink.public_path);
                        }
                      }}
                      type="button"
                    >
                      Copy link
                    </button>
                    <a
                      className="secondary-button access-share-link-action"
                      href={shareLink.public_path}
                      rel="noreferrer"
                      target="_blank"
                    >
                      Open link
                    </a>
                  </>
                ) : null}
                <button
                  className="secondary-button"
                  disabled={shareLinkControlsDisabled}
                  onClick={() => void handleRotateShareLink()}
                  type="button"
                >
                  {shareLinkBusy === "rotate" ? "Rotating..." : "Rotate link"}
                </button>
                <button
                  className="danger-button"
                  disabled={shareLinkControlsDisabled}
                  onClick={() => void handleRevokeShareLink()}
                  type="button"
                >
                  {shareLinkBusy === "revoke" ? "Revoking..." : "Revoke link"}
                </button>
              </div>
            </div>
          ) : (
            <div className="access-share-link-card">
              <p className="panel-hint">
                No active public link. Create one when you want read-only access outside the member list.
              </p>
              {shareLinkError ? (
                <p className="field-hint field-hint-error">{shareLinkError}</p>
              ) : null}
              <div className="table-bulk-pane-actions">
                <button
                  className="primary-button"
                  disabled={shareLinkControlsDisabled}
                  onClick={() => void handleCreateShareLink()}
                  type="button"
                >
                  {shareLinkBusy === "create" ? "Creating..." : "Create share link"}
                </button>
              </div>
            </div>
          )}
        </section>
      ) : null}

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
