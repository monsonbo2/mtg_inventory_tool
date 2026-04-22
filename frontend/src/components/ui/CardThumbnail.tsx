import { useEffect, useState } from "react";

export function CardThumbnail(props: {
  imageUrl: string | null;
  imageUrlLarge: string | null;
  name: string;
  variant: "search" | "owned";
}) {
  const [failedImageUrls, setFailedImageUrls] = useState<string[]>([]);

  useEffect(() => {
    setFailedImageUrls([]);
  }, [props.imageUrl, props.imageUrlLarge]);

  const imageCandidates = [props.imageUrl, props.imageUrlLarge].filter(
    (imageUrl): imageUrl is string => Boolean(imageUrl),
  );
  const activeImageUrl =
    imageCandidates.find((imageUrl) => !failedImageUrls.includes(imageUrl)) || null;
  const hasImage = Boolean(activeImageUrl);
  const className = `card-thumb card-thumb-${props.variant}`;
  const fallbackInitials =
    props.name
      .split(/\s+/)
      .map((word) => word.match(/[A-Za-z0-9]/)?.[0] || "")
      .join("")
      .slice(0, 2)
      .toUpperCase() || "?";
  const fallbackLabel = imageCandidates.length
    ? "Preview unavailable"
    : "No image data";

  return (
    <div className={className}>
      {hasImage ? (
        <img
          alt={`${props.name} card art`}
          className="card-thumb-image"
          decoding="async"
          loading="lazy"
          onError={() => {
            if (!activeImageUrl) {
              return;
            }
            setFailedImageUrls((current) =>
              current.includes(activeImageUrl) ? current : [...current, activeImageUrl],
            );
          }}
          src={activeImageUrl || undefined}
        />
      ) : (
        <div className="card-thumb-fallback" title={props.name}>
          <span aria-hidden="true" className="card-thumb-fallback-mark">
            {fallbackInitials}
          </span>
          <strong>{fallbackLabel}</strong>
        </div>
      )}
    </div>
  );
}
