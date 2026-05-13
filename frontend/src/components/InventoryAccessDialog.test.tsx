import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
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
import { InventoryAccessDialog } from "./InventoryAccessDialog";

vi.mock("../api", async () => {
  const actual = await vi.importActual<typeof import("../api")>("../api");
  return {
    ...actual,
    grantInventoryMember: vi.fn(),
    listInventoryMembers: vi.fn(),
    removeInventoryMember: vi.fn(),
    updateInventoryMember: vi.fn(),
  };
});

function buildInventory(overrides: Partial<InventorySummary> = {}): InventorySummary {
  return {
    acquisition_currency: null,
    acquisition_price: null,
    can_manage_share: true,
    can_read: true,
    can_transfer_to: true,
    can_write: true,
    default_location: null,
    default_tags: null,
    description: null,
    display_name: "Personal",
    item_rows: 2,
    notes: null,
    role: "owner",
    slug: "personal",
    total_cards: 4,
    ...overrides,
  };
}

function buildMember(
  actorId: string,
  role: InventoryMembershipRole,
): InventoryMembership {
  return {
    actor_id: actorId,
    created_at: "2026-05-01T00:00:00Z",
    inventory: "personal",
    role,
    updated_at: "2026-05-01T00:00:00Z",
  };
}

function renderDialog(
  options: {
    canManageShare?: boolean;
    inventory?: InventorySummary;
    onNotice?: (message: string, tone?: NoticeTone) => void;
    onPermissionsChanged?: (preferredSlug?: string | null) => Promise<boolean>;
  } = {},
) {
  const onNotice = vi.fn(options.onNotice);
  const onPermissionsChanged = vi.fn(
    options.onPermissionsChanged ?? (async () => true),
  );

  render(
    <InventoryAccessDialog
      canManageShare={options.canManageShare ?? true}
      inventory={options.inventory ?? buildInventory()}
      onClose={() => {}}
      onNotice={onNotice}
      onPermissionsChanged={onPermissionsChanged}
    />,
  );

  return { onNotice, onPermissionsChanged };
}

describe("InventoryAccessDialog", () => {
  beforeEach(() => {
    vi.mocked(grantInventoryMember).mockReset();
    vi.mocked(listInventoryMembers).mockReset();
    vi.mocked(removeInventoryMember).mockReset();
    vi.mocked(updateInventoryMember).mockReset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("loads members and grants access to a new actor", async () => {
    const user = userEvent.setup();
    const newMember = buildMember("new-viewer@example.com", "viewer");
    vi.mocked(listInventoryMembers).mockResolvedValue([
      buildMember("owner@example.com", "owner"),
    ]);
    vi.mocked(grantInventoryMember).mockResolvedValue(newMember);
    const { onNotice, onPermissionsChanged } = renderDialog();

    expect(await screen.findByText("owner@example.com")).toBeInTheDocument();

    await user.type(
      screen.getByLabelText("User email or actor ID"),
      "new-viewer@example.com",
    );
    await user.click(screen.getByRole("button", { name: "Grant access" }));

    await waitFor(() => {
      expect(grantInventoryMember).toHaveBeenCalledWith("personal", {
        actor_id: "new-viewer@example.com",
        role: "viewer",
      });
    });
    expect(await screen.findByText("new-viewer@example.com")).toBeInTheDocument();
    expect(onNotice).toHaveBeenCalledWith(
      "Granted Viewer access to new-viewer@example.com.",
      "success",
    );
    expect(onPermissionsChanged).toHaveBeenCalledWith("personal");
  });

  it("updates roles and removes members", async () => {
    const user = userEvent.setup();
    vi.mocked(listInventoryMembers).mockResolvedValue([
      buildMember("viewer@example.com", "viewer"),
    ]);
    vi.mocked(updateInventoryMember).mockResolvedValue(
      buildMember("viewer@example.com", "editor"),
    );
    vi.mocked(removeInventoryMember).mockResolvedValue(
      buildMember("viewer@example.com", "editor"),
    );
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const { onPermissionsChanged } = renderDialog();

    expect(await screen.findByText("viewer@example.com")).toBeInTheDocument();

    await user.selectOptions(
      screen.getByLabelText("Role for viewer@example.com"),
      "editor",
    );

    await waitFor(() => {
      expect(updateInventoryMember).toHaveBeenCalledWith(
        "personal",
        "viewer@example.com",
        { role: "editor" },
      );
    });

    const memberList = screen.getByLabelText("Current members");
    await user.click(within(memberList).getByRole("button", { name: "Remove" }));

    await waitFor(() => {
      expect(removeInventoryMember).toHaveBeenCalledWith(
        "personal",
        "viewer@example.com",
      );
    });
    expect(screen.queryByText("viewer@example.com")).not.toBeInTheDocument();
    expect(onPermissionsChanged).toHaveBeenCalledTimes(2);
  });

  it("shows unavailable state without loading members when management is not allowed", async () => {
    renderDialog({
      canManageShare: false,
      inventory: buildInventory({
        can_manage_share: false,
        role: "editor",
      }),
    });

    expect(screen.getByText("Management unavailable")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Grant access" })).not.toBeInTheDocument();
    expect(listInventoryMembers).not.toHaveBeenCalled();
  });
});
