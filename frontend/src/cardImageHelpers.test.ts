import { describe, expect, it } from "vitest";

import {
  getCroppedCardThumbnailUrls,
  getFullCardThumbnailUrls,
} from "./cardImageHelpers";

describe("cardImageHelpers", () => {
  it("prefers art crop for cropped thumbnails and keeps full-card images as fallback", () => {
    expect(
      getCroppedCardThumbnailUrls({
        image_uri_art_crop: "https://example.test/art.jpg",
        image_uri_normal: "https://example.test/normal.jpg",
        image_uri_small: "https://example.test/small.jpg",
      }),
    ).toEqual({
      fallbackImageUrl: "https://example.test/normal.jpg",
      imageUrl: "https://example.test/art.jpg",
      imageUrlLarge: null,
    });
  });

  it("falls back to normal before small for cropped thumbnails without art crop", () => {
    expect(
      getCroppedCardThumbnailUrls({
        image_uri_art_crop: null,
        image_uri_normal: "https://example.test/normal.jpg",
        image_uri_small: "https://example.test/small.jpg",
      }),
    ).toEqual({
      fallbackImageUrl: "https://example.test/small.jpg",
      imageUrl: "https://example.test/normal.jpg",
      imageUrlLarge: null,
    });
  });

  it("preserves normal-first ordering for full-card image contexts", () => {
    expect(
      getFullCardThumbnailUrls({
        image_uri_art_crop: "https://example.test/art.jpg",
        image_uri_normal: "https://example.test/normal.jpg",
        image_uri_small: "https://example.test/small.jpg",
      }),
    ).toEqual({
      fallbackImageUrl: "https://example.test/small.jpg",
      imageUrl: "https://example.test/normal.jpg",
      imageUrlLarge: null,
    });
  });
});
