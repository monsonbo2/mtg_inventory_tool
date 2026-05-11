import { useEffect, useState } from "react";

export function CardThumbnail(props: {
  imageSizes?: string;
  imageUrl: string | null;
  imageUrlLarge: string | null;
  name: string;
  variant: "search" | "owned";
}) {
  const [failedImageUrls, setFailedImageUrls] = useState<string[]>([]);

  useEffect(() => {
    setFailedImageUrls([]);
  }, [props.imageUrl, props.imageUrlLarge]);

  const imageCandidates = [
    { url: props.imageUrl, width: 146 },
    { url: props.imageUrlLarge, width: 488 },
  ].filter((image): image is { url: string; width: number } => {
    if (!image.url) {
      return false;
    }
    return !failedImageUrls.includes(image.url);
  });
  const activeImageUrl =
    imageCandidates.find((image) => !failedImageUrls.includes(image.url))?.url || null;
  const hasImage = Boolean(activeImageUrl);
  const srcSet =
    props.imageSizes && imageCandidates.length > 1
      ? imageCandidates.map((image) => `${image.url} ${image.width}w`).join(", ")
      : undefined;
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
          onError={(event) => {
            if (!activeImageUrl) {
              return;
            }
            const failedImageUrl = event.currentTarget.currentSrc || activeImageUrl;
            setFailedImageUrls((current) =>
              current.includes(failedImageUrl) ? current : [...current, failedImageUrl],
            );
          }}
          sizes={srcSet ? props.imageSizes : undefined}
          src={activeImageUrl || undefined}
          srcSet={srcSet}
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
