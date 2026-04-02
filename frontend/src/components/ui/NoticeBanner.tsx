import type { NoticeState } from "../../uiTypes";

export function NoticeBanner(props: { notice: NoticeState }) {
  return (
    <div
      aria-live={props.notice.tone === "error" ? "assertive" : "polite"}
      className={`notice-banner notice-banner-${props.notice.tone}`}
      role={props.notice.tone === "error" ? "alert" : "status"}
    >
      {props.notice.message}
    </div>
  );
}
