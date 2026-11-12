import type { ComponentType } from "react";
import type { Block } from "../lib/store";

/** Custom chat renderers for specific tools (subagent cards, audio players, …). */
export const toolRenderers: Record<string, ComponentType<{ b: Block; result?: Block }>> = {};
