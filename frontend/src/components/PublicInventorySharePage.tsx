import { useEffect, useMemo, useState } from "react";

import { getPublicInventoryShare } from "../api";
import type { PublicInventoryShareResponse } from "../types";
import { formatFinishLabel, formatLanguageCode } from "../uiHelpers";
import { CardThumbnail } from "./ui/CardThumbnail";
import { PanelState } from "./ui/PanelState";

type PublicShareState =
  | { status: "loading"; data: null; error: null }
  | { status: "ready"; data: PublicInventoryShareResponse; error: null }
  | { status: "error"; data: null; error: string };

function formatPublicShareError(error: unknown) {
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return "This public inventory link could not be loaded.";
}

function getVisiblePublicItems(data: PublicInventoryShareResponse) {
  return [...data.items].sort(
    (left, right) =>
      left.name.localeCompare(right.name) ||
      left.set_code.localeCompare(right.set_code) ||
      left.collector_number.localeCompare(right.collector_number),
  );
}

export function PublicInventorySharePage(props: { shareToken: string }) {
  const [state, setState] = useState<PublicShareState>({
    status: "loading",
    data: null,
    error: null,
  });

  useEffect(() => {
    let canceled = false;

    async function loadPublicShare() {
      setState({ status: "loading", data: null, error: null });
      try {
        const response = await getPublicInventoryShare(props.shareToken);
        if (canceled) {
          return;
        }
        setState({ status: "ready", data: response, error: null });
      } catch (error) {
        if (canceled) {
          return;
        }
        setState({
          status: "error",
          data: null,
          error: formatPublicShareError(error),
        });
      }
    }

    void loadPublicShare();

    return () => {
      canceled = true;
    };
  }, [props.shareToken]);

  const visibleItems = useMemo(
    () => (state.data ? getVisiblePublicItems(state.data) : []),
    [state.data],
  );

  return (
    <main className="app-shell public-share-shell">
      <header className="public-share-header">
        <div className="hero-copy-block">
          <p className="eyebrow">Public Collection</p>
          <h1>{state.data?.inventory.display_name || "Shared Inventory"}</h1>
          {state.data?.inventory.description ? (
            <p className="hero-copy">{state.data.inventory.description}</p>
          ) : (
            <p className="hero-copy">
              This is a read-only public view of a shared inventory.
            </p>
          )}
        </div>

        {state.data ? (
          <div className="public-share-summary">
            <div className="summary-chip">
              <span>Entries</span>
              <strong>{state.data.inventory.item_rows}</strong>
            </div>
            <div className="summary-chip">
              <span>Total cards</span>
              <strong>{state.data.inventory.total_cards}</strong>
            </div>
            <div className="summary-chip">
              <span>Access</span>
              <strong>Read-only</strong>
            </div>
          </div>
        ) : null}
      </header>

      {state.status === "loading" ? (
        <PanelState
          body="Loading the public read-only inventory view."
          eyebrow="Public Collection"
          title="Loading shared inventory"
          variant="loading"
        />
      ) : state.status === "error" ? (
        <PanelState
          body={state.error}
          eyebrow="Public Collection"
          title="Shared inventory unavailable"
          variant="error"
        />
      ) : visibleItems.length ? (
        <section className="panel public-share-panel">
          <div className="panel-heading">
            <div>
              <p className="section-kicker">Cards</p>
              <h2>Shared Cards</h2>
            </div>
            <span className="status-pill status-ready">Read-only</span>
          </div>

          <div className="public-share-list">
            {visibleItems.map((item) => (
              <article
                className="public-share-row"
                key={`${item.scryfall_id}:${item.condition_code}:${item.finish}:${item.language_code}`}
              >
                <CardThumbnail
                  imageUrl={item.image_uri_small}
                  imageUrlLarge={item.image_uri_normal}
                  name={item.name}
                  variant="owned"
                />
                <div className="public-share-row-copy">
                  <h3>{item.name}</h3>
                  <p>
                    {item.set_name} - {item.set_code.toUpperCase()} #
                    {item.collector_number}
                  </p>
                  <div className="tag-row">
                    <span className="tag-chip">Qty {item.quantity}</span>
                    <span className="tag-chip subdued">{item.condition_code}</span>
                    <span className="tag-chip subdued">
                      {formatFinishLabel(item.finish)}
                    </span>
                    <span className="tag-chip subdued">
                      {formatLanguageCode(item.language_code)}
                    </span>
                  </div>
                </div>
              </article>
            ))}
          </div>
        </section>
      ) : (
        <PanelState
          body="This public collection has no shared cards yet."
          eyebrow="Public Collection"
          title="No cards shared"
        />
      )}
    </main>
  );
}
