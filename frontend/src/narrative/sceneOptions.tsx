import { createContext } from "react";
import type { ReactNode } from "react";

// Route pickers list scenes, not every line. The Studio builds these <option>
// elements once per scene list so typing never re-renders thousands of options.
export interface SceneOptions { ids: Set<string>; options: ReactNode }
export const SceneOptionsContext = createContext<SceneOptions | null>(null);
