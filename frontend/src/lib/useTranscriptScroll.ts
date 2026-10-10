import { useLayoutEffect, useRef, useState } from "react";
import type { QueryRunResponse } from "./types";

// Only authoritative turn changes can auto-follow. Lazy evidence expansion is
// deliberately not observed as a resize that could move the reader.
export function useTranscriptScroll(tail?: QueryRunResponse) {
  const element = useRef<HTMLDivElement | null>(null);
  const following = useRef(true);
  const [showLatest, setShowLatest] = useState(false);
  function onScroll() {
    const node = element.current;
    if (!node) return;
    following.current = node.scrollHeight - node.clientHeight - node.scrollTop < 96;
    setShowLatest(!following.current);
  }
  function reset() { following.current = true; setShowLatest(false); }
  function hold() { following.current = false; }
  function jump() {
    following.current = true; setShowLatest(false);
    element.current?.scrollTo({ top: element.current.scrollHeight,
      behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
  }
  useLayoutEffect(() => {
    const node = element.current;
    if (!node) return;
    if (following.current) { node.scrollTop = node.scrollHeight; setShowLatest(false); }
    else setShowLatest(node.scrollHeight - node.clientHeight - node.scrollTop > 4);
  }, [tail?.id, tail?.status, tail?.answer_text]);
  return { element, onScroll, reset, hold, jump, showLatest };
}
