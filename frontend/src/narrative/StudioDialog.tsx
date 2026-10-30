import { useEffect, useRef } from "react";
import type { ReactNode } from "react";

// Native modality traps focus, makes the rest of the app inert, and restores
// focus to the opener. Escape always has a visible, equivalent Close action.
export function StudioDialog({ label, onClose, children }: {
  label: string; onClose: () => void; children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current!;
    dialog.showModal();
    return () => dialog.close();
  }, []);
  return <dialog ref={ref} className="studio-peek" aria-label={label}
    onCancel={event => { event.preventDefault(); onClose(); }}>{children}</dialog>;
}
