export type CardImageUris = {
  image_uri_art_crop: string | null;
  image_uri_normal: string | null;
  image_uri_small: string | null;
};

export type CardThumbnailImageUrls = {
  fallbackImageUrl: string | null;
  imageUrl: string | null;
  imageUrlLarge: string | null;
};

function uniqueFallbackUrl(
  primaryUrl: string | null,
  fallbackUrl: string | null,
): string | null {
  if (!fallbackUrl || fallbackUrl === primaryUrl) {
    return null;
  }
  return fallbackUrl;
}

export function getCroppedCardThumbnailUrls(
  imageUris: CardImageUris,
): CardThumbnailImageUrls {
  const imageUrl =
    imageUris.image_uri_art_crop ??
    imageUris.image_uri_normal ??
    imageUris.image_uri_small;
  const fallbackImageUrl = imageUris.image_uri_art_crop
    ? imageUris.image_uri_normal ?? imageUris.image_uri_small
    : imageUris.image_uri_small;

  return {
    fallbackImageUrl: uniqueFallbackUrl(imageUrl, fallbackImageUrl),
    imageUrl,
    imageUrlLarge: null,
  };
}

export function getFullCardThumbnailUrls(
  imageUris: CardImageUris,
): CardThumbnailImageUrls {
  const imageUrl =
    imageUris.image_uri_normal ??
    imageUris.image_uri_small ??
    imageUris.image_uri_art_crop;
  const fallbackImageUrl = imageUris.image_uri_normal
    ? imageUris.image_uri_small ?? imageUris.image_uri_art_crop
    : imageUris.image_uri_art_crop;

  return {
    fallbackImageUrl: uniqueFallbackUrl(imageUrl, fallbackImageUrl),
    imageUrl,
    imageUrlLarge: null,
  };
}
