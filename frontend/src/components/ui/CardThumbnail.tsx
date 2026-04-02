import { useEffect, useState } from "react";

export function CardThumbnail(props: {
  imageUrl: string | null;
  imageUrlLarge: string | null;
  name: string;
  variant: "search" | "owned";
}) {
  const [didFail, setDidFail] = useState(false);

  useEffect(() => {
    setDidFail(false);
  }, [props.imageUrl]);

  const hasImage = Boolean(props.imageUrl) && !didFail;
  const className = `card-thumb card-thumb-${props.variant}`;

  return (
    <div className={className}>
      {hasImage ? (
        <img
          alt={`${props.name} card art`}
          className="card-thumb-image"
          decoding="async"
          loading="lazy"
          onError={() => setDidFail(true)}
          src={props.imageUrl || undefined}
        />
      ) : (
        <div className="card-thumb-fallback">
          <span>Card Art</span>
          <strong>{props.imageUrlLarge ? "Preview unavailable" : "No image data"}</strong>
        </div>
      )}
    </div>
  );
}
