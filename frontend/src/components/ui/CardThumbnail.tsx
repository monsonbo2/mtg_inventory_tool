import { useEffect, useState } from "react";

type ImageCandidate = {
  includeInSrcSet: boolean;
  url: string;
  width: number;
};

export function CardThumbnail(props: {
  fallbackImageUrl?: string | null;
  imageSizes?: string;
  imageUrl: string | null;
  imageUrlLarge: string | null;
  name: string;
  variant: "search" | "owned";
}) {
  const [failedImageUrls, setFailedImageUrls] = useState<string[]>([]);

  useEffect(() => {
    setFailedImageUrls([]);
  }, [props.fallbackImageUrl, props.imageUrl, props.imageUrlLarge]);

  const imageCandidates = [
    { includeInSrcSet: true, url: props.imageUrl, width: 146 },
    { includeInSrcSet: true, url: props.imageUrlLarge, width: 488 },
    { includeInSrcSet: false, url: props.fallbackImageUrl ?? null, width: 488 },
  ]
    .filter((image): image is ImageCandidate => {
      if (!image.url) {
        return false;
      }
      return !failedImageUrls.includes(image.url);
    })
    .filter((image, index, images) => {
      return images.findIndex((candidate) => candidate.url === image.url) === index;
    });
  const activeImageUrl = imageCandidates[0]?.url || null;
  const hasImage = Boolean(activeImageUrl);
  const srcSetCandidates = imageCandidates.filter((image) => image.includeInSrcSet);
  const srcSet =
    props.imageSizes && srcSetCandidates.length > 1
      ? srcSetCandidates.map((image) => `${image.url} ${image.width}w`).join(", ")
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
