import type { ApiTextResponse } from "./api";

export function downloadApiTextResponse(
  response: ApiTextResponse,
  fallbackFilename: string,
) {
  const blob = new Blob([response.body], {
    type: response.contentType || "text/plain;charset=utf-8",
  });
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement("a");

  anchor.href = objectUrl;
  anchor.download = response.filename?.trim() || fallbackFilename;
  anchor.style.display = "none";

  document.body.appendChild(anchor);
  try {
    anchor.click();
  } finally {
    anchor.remove();
    URL.revokeObjectURL(objectUrl);
  }
}
